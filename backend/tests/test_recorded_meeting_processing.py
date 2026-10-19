from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("WHISPER_DEVICE", "cpu")

from app.schemas.summary import MeetingSummary
from app.services.recorded_meeting_service import RecordedMeetingService
from app.storage.meeting_storage import MeetingStorage
from app.transcription.result import TranscriptionResult, WordResult


@dataclass
class _TimedResult:
    start: float
    end: float
    result: TranscriptionResult


@dataclass
class _BatchResult:
    segments: tuple[_TimedResult, ...]
    duration_seconds: float
    duration_after_vad_seconds: float | None
    language: str | None


class _Snapshot:
    def __init__(self):
        self.active_terms = ()
    def to_dict(self):
        return {"meeting_id": "offline", "active_terms": [], "categories": []}


class _Context:
    hotwords = None
    initial_prompt = None
    active_terms = ()


class _Vocabulary:
    def start_meeting(self, meeting_id): return _Snapshot()
    def context_for(self, meeting_id): return _Context()
    def observe(self, meeting_id, text): return None
    def correct_result(self, meeting_id, result): return result, None
    def finalize(self, meeting_id): return _Snapshot()
    def forget(self, meeting_id): pass
    def set_slide_context(self, *args, **kwargs): return None


class _SlideContext:
    def attach(self, meeting_id, presentation_id): raise AssertionError("not expected")
    def observe(self, meeting_id, text): return None
    def forget(self, meeting_id): pass


class _Bus:
    def publish(self, event): pass


class _Whisper:
    def transcribe_batched(self, filename, **kwargs):
        self.kwargs = kwargs
        return _BatchResult(
            segments=(
                _TimedResult(
                    0.0, 4.0,
                    TranscriptionResult(
                        text="We discuss synchrotron imaging.",
                        words=(
                            WordResult("We", 0.95, 0.0, 0.2),
                            WordResult("discuss", 0.95, 0.2, 0.6),
                            WordResult("synchrotron", 0.95, 0.6, 1.2),
                            WordResult("imaging.", 0.95, 1.2, 1.8),
                        ),
                        average_confidence=0.95,
                    ),
                ),
                _TimedResult(
                    4.0, 8.0,
                    TranscriptionResult(
                        text="ASTRA Toolbox is used for tomography.",
                        words=(
                            WordResult("ASTRA", 0.9, 4.0, 4.3),
                            WordResult("Toolbox", 0.9, 4.3, 4.7),
                            WordResult("is", 0.9, 4.7, 4.8),
                            WordResult("used", 0.9, 4.8, 5.1),
                            WordResult("for", 0.9, 5.1, 5.2),
                            WordResult("tomography.", 0.9, 5.2, 5.8),
                        ),
                        average_confidence=0.9,
                    ),
                ),
            ),
            duration_seconds=8.0,
            duration_after_vad_seconds=7.5,
            language="en",
        )


class _SummaryService:
    def __init__(self, storage): self.storage = storage
    async def summarize(self, meeting_id):
        result = MeetingSummary(
            meeting_id=meeting_id,
            summary="Synchrotron imaging and tomography were discussed.",
            key_points=["ASTRA Toolbox was used."],
            decisions=[], action_items=[], open_questions=[],
            slide_summaries=[], technical_terms=["ASTRA Toolbox"],
            transcription_uncertainties=[],
            generated_at=datetime.now(timezone.utc),
            provider="test", model="fake",
            transcript_segments=2, transcript_characters=72,
        )
        self.storage.save_summary(meeting_id, result.model_dump())
        return result


class RecordedMeetingProcessingTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_file_is_processed_without_realtime_playback(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp) / 'meeting.db'}"
            storage = MeetingStorage()
            audio = Path(tmp) / "recording.wav"
            audio.write_bytes(b"fake-audio")
            whisper = _Whisper()
            service = RecordedMeetingService(
                storage=storage, whisper=whisper,
                summary=_SummaryService(storage),
                vocabulary=_Vocabulary(), slide_context=_SlideContext(),
                event_bus=_Bus(),
            )
            response = await service.process(audio, title="Imported meeting")

            self.assertEqual(response["mode"], "fast-recorded")
            self.assertEqual(response["processing"]["audio_duration_seconds"], 8.0)
            self.assertEqual(response["processing"]["segments"], 2)
            self.assertEqual(whisper.kwargs["batch_size"], service.batch_size)
            self.assertIn("ASTRA Toolbox", response["summary"]["technical_terms"])
            details = storage.get_meeting_details(response["meeting_id"])
            self.assertEqual(details["status"], "completed")
            self.assertIn("synchrotron imaging", details["final_transcript"].lower())
            self.assertIn("ASTRA Toolbox", details["final_transcript"])
            self.assertIsNotNone(details["summary"])


if __name__ == "__main__":
    unittest.main()
