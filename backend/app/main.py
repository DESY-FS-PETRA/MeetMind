from __future__ import annotations

import asyncio
import os
import tempfile

import httpx
from contextlib import asynccontextmanager, suppress

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, Response, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.core.state import (  # noqa: E402
    event_bus,
    meeting_engine,
    presentation_service,
    slide_context_service,
    vocabulary_service,
)
from app.schemas.meeting import (  # noqa: E402
    SlideAutoRequest,
    StartMeetingRequest,
    UpdateMeetingRequest,
)
from app.ai.llm_service import LLMProviderError  # noqa: E402
from app.rag.service import RAGService  # noqa: E402
from app.schemas.rag import RAGAskRequest, RAGSearchRequest  # noqa: E402
from app.schemas.conference import (  # noqa: E402
    ConferenceAskRequest, ConferenceBulkImportRequest, ConferenceCreateRequest,
    ConferenceProgramImportRequest, ConferenceTalkInput, ConferenceTalkUpdateRequest,
)
from app.events.events import VocabularyUpdated  # noqa: E402
from app.presentation.extractor import PresentationExtractionError  # noqa: E402
from app.services.meeting_summary_service import MeetingSummaryService  # noqa: E402
from app.services.recorded_meeting_service import RecordedMeetingService  # noqa: E402
from app.services.conference_service import ConferenceService  # noqa: E402
from app.transcription.worker import TranscriptionWorker  # noqa: E402
from app.websocket.audio_socket import audio_stream  # noqa: E402
from app.websocket.frontend_socket import transcript_socket  # noqa: E402


worker = TranscriptionWorker()
summary_service = MeetingSummaryService(storage=meeting_engine.storage)
rag_service = RAGService(storage=meeting_engine.storage)
conference_service = ConferenceService(storage=meeting_engine.storage)

recorded_meeting_service = RecordedMeetingService(
    storage=meeting_engine.storage,
    whisper=worker.whisper,
    summary=summary_service,
    vocabulary=vocabulary_service,
    slide_context=slide_context_service,
    event_bus=event_bus,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker_task = asyncio.create_task(worker.start(), name="transcription-worker")
    try:
        yield
    finally:
        worker.stop()
        with suppress(asyncio.CancelledError):
            await worker_task


app = FastAPI(
    title="MeetMind API",
    version="1.1.3",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {
        "status": "MeetMind running",
        "version": app.version,
        "storage": "SQLAlchemy database",
        "database_backend": meeting_engine.storage.database.engine.url.get_backend_name(),
    }




@app.get("/rag/status")
async def rag_status():
    return await rag_service.status()


@app.post("/rag/index")
async def rag_index(force: bool = Query(default=False)):
    return await rag_service.index_all(force=force)


@app.post("/rag/search")
async def rag_search(payload: RAGSearchRequest):
    try:
        return await rag_service.search(
            payload.query,
            top_k=payload.top_k,
            meeting_ids=payload.meeting_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        print("RAG search error:", repr(exc))
        raise HTTPException(status_code=503, detail=f"RAG search failed: {exc}") from exc


@app.post("/rag/ask")
async def rag_ask(payload: RAGAskRequest):
    try:
        return await rag_service.ask(
            payload.question,
            history=[item.model_dump() for item in payload.history],
            top_k=payload.top_k,
            latitude=payload.latitude,
            longitude=payload.longitude,
            timezone_name=payload.timezone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        print("RAG chat error:", repr(exc))
        raise HTTPException(status_code=503, detail=f"RAG chat failed: {exc}") from exc


@app.get("/llm/status")
async def llm_status():
    return (await summary_service.llm.status()).as_dict()


@app.get("/vocabulary/status")
def vocabulary_status():
    return vocabulary_service.global_status()


@app.post("/presentations/upload")
async def upload_presentation(file: UploadFile = File(...)):
    try:
        return await presentation_service.upload(file)
    except PresentationExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        print("Presentation upload error:", repr(exc))
        raise HTTPException(
            status_code=500,
            detail="Presentation upload or text extraction failed",
        ) from exc


@app.get("/presentations/{presentation_id}")
def get_presentation(presentation_id: str):
    presentation = meeting_engine.storage.get_presentation(presentation_id)
    if presentation is None:
        raise HTTPException(status_code=404, detail="Presentation not found")
    return presentation


@app.get("/meeting/{meeting_id}/presentation")
def get_meeting_presentation(meeting_id: str):
    presentation = meeting_engine.storage.get_meeting_presentation(meeting_id)
    if presentation is None:
        raise HTTPException(status_code=404, detail="Meeting presentation not found")
    return presentation


@app.post("/meeting/{meeting_id}/slides/{slide_number}/activate")
async def activate_meeting_slide(meeting_id: str, slide_number: int):
    if meeting_id != meeting_engine.current_meeting_id:
        raise HTTPException(status_code=409, detail="Only an active meeting can change slides")
    try:
        slide = slide_context_service.activate_manual(meeting_id, slide_number)
        vocabulary = vocabulary_service.set_slide_context(
            meeting_id,
            slide_number=slide.slide_number,
            slide_title=slide.slide_title,
            slide_terms=slide.slide_terms,
            auto_match=slide.auto_match,
        )
        current = vocabulary or vocabulary_service.snapshot(meeting_id)
        if current is not None:
            event_bus.publish(VocabularyUpdated(current.to_dict()))
        return {
            "slide": slide.to_dict(),
            "vocabulary": current.to_dict() if current else None,
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/meeting/{meeting_id}/slides/auto")
async def set_automatic_slide_matching(meeting_id: str, payload: SlideAutoRequest):
    if meeting_id != meeting_engine.current_meeting_id:
        raise HTTPException(status_code=409, detail="Only an active meeting can change slide mode")
    if not payload.enabled:
        raise HTTPException(
            status_code=422,
            detail="Choose a slide number to use manual mode",
        )
    try:
        slide = slide_context_service.enable_auto(meeting_id)
        vocabulary = vocabulary_service.set_slide_context(
            meeting_id,
            slide_number=slide.slide_number,
            slide_title=slide.slide_title,
            slide_terms=slide.slide_terms,
            auto_match=True,
        )
        current = vocabulary or vocabulary_service.snapshot(meeting_id)
        if current is not None:
            event_bus.publish(VocabularyUpdated(current.to_dict()))
        return {
            "slide": slide.to_dict(),
            "vocabulary": current.to_dict() if current else None,
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/meeting/{meeting_id}/vocabulary")
def meeting_vocabulary(meeting_id: str):
    current = vocabulary_service.snapshot(meeting_id)
    if current is not None:
        return current.to_dict()
    stored = meeting_engine.storage.load_vocabulary_state(meeting_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Meeting vocabulary state not found")
    return stored


@app.post("/meeting/{meeting_id}/vocabulary/refresh")
async def refresh_meeting_vocabulary(meeting_id: str):
    meeting = meeting_engine.storage.get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if vocabulary_service.snapshot(meeting_id) is None:
        vocabulary_service.start_meeting(meeting_id)
    text = meeting_engine.storage.load_final_transcript_text(meeting_id)
    update = vocabulary_service.observe(meeting_id, text)
    snapshot = update or vocabulary_service.snapshot(meeting_id)
    if snapshot is None:
        raise HTTPException(status_code=422, detail="No transcript available for vocabulary detection")
    event_bus.publish(VocabularyUpdated(snapshot.to_dict()))
    return snapshot.to_dict()


@app.post("/recorded-meetings/process")
async def process_recorded_meeting(
    file: UploadFile = File(...),
    title: str = Form(default="Recorded Meeting"),
    presentation_id: str | None = Form(default=None),
    conference_talk_id: str | None = Form(default=None),
    context_terms: str | None = Form(default=None),
):
    if meeting_engine.current_meeting_id:
        raise HTTPException(
            status_code=409,
            detail="Stop the live meeting before processing a recorded file",
        )
    if presentation_id and meeting_engine.storage.get_presentation(presentation_id) is None:
        raise HTTPException(status_code=404, detail="Presentation not found")

    original_name = file.filename or "recording"
    suffix = os.path.splitext(original_name)[1].lower()
    allowed_suffixes = {
        ".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac",
        ".mp4", ".mov", ".mkv", ".aac", ".opus",
    }
    if suffix and suffix not in allowed_suffixes:
        raise HTTPException(
            status_code=422,
            detail="Unsupported recording format",
        )

    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=suffix or ".audio",
            delete=False,
        ) as temporary_file:
            temporary_path = temporary_file.name
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                temporary_file.write(chunk)

        if not temporary_path or os.path.getsize(temporary_path) == 0:
            raise HTTPException(status_code=422, detail="The uploaded recording is empty")

        parsed_context_terms = [item.strip() for item in (context_terms or "").split("|") if item.strip()]
        result = await recorded_meeting_service.process(
            temporary_path,
            title=title,
            presentation_id=presentation_id,
            original_filename=original_name,
            context_terms=parsed_context_terms,
        )
        if conference_talk_id:
            conference_service.link_meeting(conference_talk_id, result["meeting_id"])
            result["conference_talk_id"] = conference_talk_id
        return result
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        print("Recorded meeting processing error:", repr(exc))
        raise HTTPException(
            status_code=500,
            detail="Recorded meeting processing failed",
        ) from exc
    finally:
        await file.close()
        if temporary_path:
            try:
                os.remove(temporary_path)
            except OSError:
                pass



@app.get("/conferences")
def list_conferences():
    return {"conferences": conference_service.list()}


@app.post("/conferences")
def create_conference(payload: ConferenceCreateRequest):
    return conference_service.create(payload.model_dump())


@app.get("/conferences/{conference_id}")
def get_conference(conference_id: str):
    conference = conference_service.get(conference_id)
    if conference is None:
        raise HTTPException(status_code=404, detail="Conference not found")
    return conference


@app.delete("/conferences/{conference_id}", status_code=204)
def delete_conference(conference_id: str):
    if not conference_service.delete(conference_id):
        raise HTTPException(status_code=404, detail="Conference not found")
    return Response(status_code=204)


@app.post("/conferences/{conference_id}/talks")
def add_conference_talk(conference_id: str, payload: ConferenceTalkInput):
    try:
        result = conference_service.bulk_import(conference_id, [payload.model_dump()])
        return result["talks"][-1] if result.get("talks") else result
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/conferences/{conference_id}/import")
def import_conference_talks(conference_id: str, payload: ConferenceBulkImportRequest):
    try:
        return conference_service.bulk_import(
            conference_id,
            [item.model_dump() for item in payload.talks],
            replace=payload.replace,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/conferences/{conference_id}/import-url")
async def import_conference_program_url(conference_id: str, payload: ConferenceProgramImportRequest):
    try:
        return await conference_service.import_program_url(conference_id, payload.url)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/conference-talks/{talk_id}")
def get_conference_talk(talk_id: str):
    talk = conference_service.get_talk(talk_id)
    if talk is None:
        raise HTTPException(status_code=404, detail="Conference talk not found")
    return talk


@app.patch("/conference-talks/{talk_id}")
def update_conference_talk(talk_id: str, payload: ConferenceTalkUpdateRequest):
    talk = conference_service.update_talk(talk_id, payload.model_dump())
    if talk is None:
        raise HTTPException(status_code=404, detail="Conference talk not found")
    return talk


@app.post("/conferences/{conference_id}/ask")
async def ask_conference(conference_id: str, payload: ConferenceAskRequest):
    conference = conference_service.get(conference_id)
    if conference is None:
        raise HTTPException(status_code=404, detail="Conference not found")
    meeting_ids = conference_service.scoped_meeting_ids(
        conference_id,
        scope=payload.scope,
        day_label=payload.day_label,
        session_name=payload.session_name,
        talk_ids=payload.talk_ids,
    )
    if not meeting_ids:
        return {
            "answer": "No recorded/processed talks are available in the selected conference scope yet.",
            "sources": [], "evidence_found": False, "meeting_evidence_used": False,
            "scope_meeting_count": 0,
        }
    result = await rag_service.ask(payload.question, top_k=payload.top_k, meeting_ids=meeting_ids)
    result["scope_meeting_count"] = len(meeting_ids)
    return result


@app.websocket("/ws/audio")
async def websocket_audio(websocket: WebSocket):
    await audio_stream(websocket)


@app.websocket("/ws/transcript")
async def websocket_transcript(websocket: WebSocket):
    await transcript_socket(websocket)


@app.post("/meeting/start")
async def start_meeting(payload: StartMeetingRequest | None = None):
    title = payload.title if payload else "Conference Meeting"
    presentation_id = payload.presentation_id if payload else None
    conference_talk_id = payload.conference_talk_id if payload else None
    context_terms = payload.context_terms if payload else []
    if presentation_id and meeting_engine.storage.get_presentation(presentation_id) is None:
        raise HTTPException(status_code=404, detail="Presentation not found")

    try:
        meeting_id = meeting_engine.start_meeting(title=title)
        vocabulary = vocabulary_service.start_meeting(meeting_id, custom_terms=context_terms)
        presentation = None
        if presentation_id:
            slide = slide_context_service.attach(meeting_id, presentation_id)
            update = vocabulary_service.set_slide_context(
                meeting_id,
                slide_number=slide.slide_number,
                slide_title=slide.slide_title,
                slide_terms=slide.slide_terms,
                auto_match=slide.auto_match,
            )
            vocabulary = update or vocabulary
            presentation = meeting_engine.storage.get_meeting_presentation(meeting_id)

        if conference_talk_id:
            conference_service.link_meeting(conference_talk_id, meeting_id)
        event_bus.publish(VocabularyUpdated(vocabulary.to_dict()))
        return {
            "status": "started",
            "meeting_id": meeting_id,
            "title": title,
            "vocabulary": vocabulary.to_dict(),
            "presentation": presentation,
            "conference_talk_id": conference_talk_id,
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/meeting/stop")
async def stop_meeting():
    try:
        meeting_id = meeting_engine.current_meeting_id
        meeting = await meeting_engine.stop_meeting()
        if meeting_id:
            worker.finalize_meeting(meeting_id)
            # The event bus is synchronous, so storage now contains the final
            # rolling transcript. Return that finalized snapshot to the UI.
            meeting = meeting_engine.storage.get_meeting(meeting_id) or meeting
            meeting["transcript"] = meeting_engine.storage.load_transcript(meeting_id)
            vocabulary = vocabulary_service.finalize(meeting_id)
            if vocabulary is not None:
                event_bus.publish(VocabularyUpdated(vocabulary.to_dict()))
            worker.finish_meeting(meeting_id)
            vocabulary_service.forget(meeting_id)
            slide_context_service.forget(meeting_id)
        return {
            "status": "stopped",
            **meeting,
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc


@app.get("/meeting/current")
def current_meeting():
    return meeting_engine.get_current()


@app.get("/meeting/{meeting_id}")
def get_meeting(meeting_id: str):
    meeting = meeting_engine.storage.get_meeting_details(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@app.get("/meetings")
def list_meetings(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=200),
):
    return meeting_engine.storage.list_meetings(
        limit=limit,
        offset=offset,
        search=search,
    )


@app.get("/meetings/{meeting_id}")
def get_meeting_history_item(meeting_id: str):
    meeting = meeting_engine.storage.get_meeting_details(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@app.patch("/meetings/{meeting_id}")
def update_meeting(meeting_id: str, payload: UpdateMeetingRequest):
    try:
        meeting = meeting_engine.storage.update_meeting(
            meeting_id,
            title=payload.title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@app.delete("/meetings/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: str):
    if meeting_id == meeting_engine.current_meeting_id:
        raise HTTPException(status_code=409, detail="Cannot delete an active meeting")
    deleted = meeting_engine.storage.delete_meeting(meeting_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return Response(status_code=204)


@app.post("/meeting/{meeting_id}/summarize")
async def summarize_meeting(meeting_id: str):
    try:
        return await summary_service.summarize(meeting_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        print("Summary endpoint error:", repr(exc))
        raise HTTPException(
            status_code=500,
            detail="Meeting summary generation failed",
        ) from exc


@app.get("/meeting/{meeting_id}/summary")
def get_meeting_summary(meeting_id: str):
    summary = meeting_engine.storage.load_summary(meeting_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Summary not found")
    return summary
