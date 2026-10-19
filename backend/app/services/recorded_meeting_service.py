from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from app.events.events import VocabularyUpdated
from app.presentation.slide_context import SlideContextService
from app.services.meeting_summary_service import MeetingSummaryService
from app.storage.meeting_storage import MeetingStorage
from app.transcription.hallucination_guard import TranscriptHallucinationGuard
from app.transcription.result import TranscriptionResult
from app.transcription.transcript_cleaner import TranscriptCleaner
from app.transcription.scientific_validator import ScientificTranscriptValidator
if TYPE_CHECKING:
    from app.transcription.whisper_service import WhisperService
from app.vocabulary.service import AdaptiveVocabularyService


class RecordedMeetingService:
    """Fast, non-realtime processing for an already recorded meeting.

    Unlike the browser file-stream test, this service never plays the audio.
    Faster-Whisper sees the complete source file and performs batched inference
    as fast as the available CPU/GPU can run it.
    """

    def __init__(
        self,
        *,
        storage: MeetingStorage,
        whisper: "WhisperService",
        summary: MeetingSummaryService,
        vocabulary: AdaptiveVocabularyService,
        slide_context: SlideContextService,
        event_bus,
    ) -> None:
        self.storage = storage
        self.whisper = whisper
        self.summary_service = summary
        self.vocabulary = vocabulary
        self.slide_context = slide_context
        self.event_bus = event_bus
        self.hallucination_guard = TranscriptHallucinationGuard()
        self.cleaner = TranscriptCleaner()
        self.scientific_validator = ScientificTranscriptValidator()
        self.low_confidence_threshold = float(
            os.getenv("WHISPER_LOW_CONFIDENCE_THRESHOLD", "0.65")
        )
        self.batch_size = max(1, int(os.getenv("WHISPER_OFFLINE_BATCH_SIZE", "8")))

    async def process(
        self,
        audio_path: str | Path,
        *,
        title: str,
        presentation_id: str | None = None,
        original_filename: str | None = None,
        context_terms: list[str] | None = None,
    ) -> dict:
        started_clock = time.perf_counter()
        started_at = datetime.now(timezone.utc)
        meeting_id = str(uuid4())
        clean_title = title.strip() or (original_filename or "Recorded Meeting")

        self.storage.create_meeting(
            meeting_id,
            clean_title[:200],
            started_at=started_at.isoformat(),
        )
        # Preserve compatibility with meeting-mode vocabulary implementations and
        # test doubles that only accept ``start_meeting(meeting_id)``. Conference
        # context is supplied only when we actually have talk-specific terms.
        if context_terms:
            vocabulary_snapshot = self.vocabulary.start_meeting(
                meeting_id, custom_terms=context_terms
            )
        else:
            vocabulary_snapshot = self.vocabulary.start_meeting(meeting_id)
        self.event_bus.publish(VocabularyUpdated(vocabulary_snapshot.to_dict()))

        try:
            presentation_payload = None
            if presentation_id:
                self.slide_context.attach(meeting_id, presentation_id)
                presentation_payload = self.storage.get_meeting_presentation(meeting_id)

            # Keep the batch ASR context intentionally conservative. Only the
            # always-on/core vocabulary is active here; slide-specific terms are
            # introduced after speech provides evidence, preventing over-bias.
            initial_context = self.vocabulary.context_for(meeting_id)

            transcription_started = time.perf_counter()
            batch = await asyncio.to_thread(
                self.whisper.transcribe_batched,
                str(audio_path),
                batch_size=self.batch_size,
                hotwords=initial_context.hotwords,
                initial_prompt=initial_context.initial_prompt,
            )
            transcription_seconds = time.perf_counter() - transcription_started

            persisted_segments = 0
            for index, timed in enumerate(batch.segments, start=1):
                result, _ = self.hallucination_guard.sanitize(
                    timed.result,
                    active_terms=self.vocabulary.context_for(meeting_id).active_terms,
                )
                if not result.text.strip():
                    continue

                topic_update = self.vocabulary.observe(meeting_id, result.text)
                if topic_update is not None:
                    self.event_bus.publish(VocabularyUpdated(topic_update.to_dict()))

                result, correction_update = self.vocabulary.correct_result(
                    meeting_id,
                    result,
                )
                if correction_update is not None:
                    self.event_bus.publish(VocabularyUpdated(correction_update.to_dict()))

                cleaned_words = self.cleaner.clean_words(result.words, final=False)
                if cleaned_words:
                    clean_text = self.cleaner.text(cleaned_words)
                    probabilities = [
                        word.probability
                        for word in cleaned_words
                        if word.probability is not None
                    ]
                    average_confidence = (
                        sum(probabilities) / len(probabilities)
                        if probabilities else result.average_confidence
                    )
                    cleaned_result = TranscriptionResult(
                        text=clean_text,
                        words=tuple(cleaned_words),
                        average_confidence=average_confidence,
                        corrections=result.corrections,
                    )
                else:
                    cleaned_result = result

                scientific_corrections = ()
                if presentation_payload is not None:
                    cleaned_result, scientific_corrections = self.scientific_validator.correct_result(
                        cleaned_result,
                        presentation=presentation_payload,
                    )

                if not cleaned_result.text.strip():
                    continue

                words_payload = [
                    word.to_dict(
                        low_confidence_threshold=self.low_confidence_threshold
                    )
                    for word in cleaned_result.words
                ]
                if scientific_corrections and words_payload:
                    words_payload[0]["scientific_corrections"] = [
                        item.to_dict() for item in scientific_corrections
                    ]
                    slide_confirmed_tokens = {
                        token.casefold().strip(".,;:!?()[]{}")
                        for item in scientific_corrections
                        if item.source in {"slide", "context"} and not item.requires_review
                        for token in item.replacement.split()
                    }
                    for word in words_payload:
                        token = str(word.get("text") or "").casefold().strip(".,;:!?()[]{}")
                        if token in slide_confirmed_tokens:
                            word["context_confirmed"] = True
                            word["needs_review"] = False
                low_confidence_count = sum(
                    1 for word in words_payload if word.get("needs_review")
                )
                created_at = started_at + timedelta(seconds=max(0.0, timed.start))
                self.storage.upsert_transcript(
                    meeting_id,
                    cleaned_result.text,
                    segment_id=f"offline-{index:05d}",
                    event_id=f"offline-{meeting_id}-{index:05d}",
                    created_at=created_at.isoformat(),
                    revision=1,
                    is_final=True,
                    words=words_payload,
                    average_confidence=cleaned_result.average_confidence,
                    low_confidence_count=low_confidence_count,
                )
                persisted_segments += 1

            if persisted_segments == 0:
                raise ValueError("No speech could be transcribed from the recording")

            # Whole-recording alignment is deliberately deferred until all ASR
            # text exists. It uses deck order and the complete transcript, and
            # replaces the noisy local timeline created at attachment time.
            if presentation_payload is not None:
                alignment = self.slide_context.align_offline(meeting_id)
                if alignment:
                    final_slide = self.slide_context.context_for(meeting_id)
                    if final_slide is not None:
                        update = self.vocabulary.set_slide_context(
                            meeting_id,
                            slide_number=final_slide.slide_number,
                            slide_title=final_slide.slide_title,
                            slide_terms=final_slide.slide_terms,
                            auto_match=True,
                        )
                        if update is not None:
                            self.event_bus.publish(VocabularyUpdated(update.to_dict()))

            audio_duration = max(0.0, float(batch.duration_seconds or 0.0))
            meeting_end = (
                started_at + timedelta(seconds=audio_duration)
                if audio_duration > 0
                else datetime.now(timezone.utc)
            )
            meeting = self.storage.complete_meeting(
                meeting_id,
                end_time=meeting_end.isoformat(),
            )

            final_vocabulary = self.vocabulary.finalize(meeting_id)
            if final_vocabulary is not None:
                self.event_bus.publish(VocabularyUpdated(final_vocabulary.to_dict()))

            summary_started = time.perf_counter()
            summary = await self.summary_service.summarize(meeting_id)
            summary_seconds = time.perf_counter() - summary_started
            total_seconds = time.perf_counter() - started_clock

            details = self.storage.get_meeting_details(meeting_id) or meeting
            presentation = self.storage.get_meeting_presentation(meeting_id)
            return {
                "status": "completed",
                "mode": "fast-recorded",
                "meeting_id": meeting_id,
                "title": clean_title,
                "transcript": details.get("transcript", []),
                "summary": summary.model_dump() if hasattr(summary, "model_dump") else summary,
                "presentation": presentation,
                "processing": {
                    "audio_duration_seconds": round(audio_duration, 3),
                    "duration_after_vad_seconds": (
                        round(float(batch.duration_after_vad_seconds), 3)
                        if batch.duration_after_vad_seconds is not None
                        else None
                    ),
                    "transcription_seconds": round(transcription_seconds, 3),
                    "summary_seconds": round(summary_seconds, 3),
                    "total_seconds": round(total_seconds, 3),
                    "transcription_realtime_factor": (
                        round(transcription_seconds / audio_duration, 4)
                        if audio_duration > 0
                        else None
                    ),
                    "transcription_speed_x": (
                        round(audio_duration / transcription_seconds, 2)
                        if transcription_seconds > 0 and audio_duration > 0
                        else None
                    ),
                    "batch_size": self.batch_size,
                    "segments": persisted_segments,
                },
            }
        except Exception:
            # A failed import should not leave a misleading active meeting in
            # history. Presentation rows are independent and remain reusable.
            self.storage.delete_meeting(meeting_id)
            raise
        finally:
            self.vocabulary.forget(meeting_id)
            self.slide_context.forget(meeting_id)
