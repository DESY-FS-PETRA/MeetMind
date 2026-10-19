from __future__ import annotations

import asyncio
import os
import tempfile

from app.audio.speech import contains_speech_energy, pcm_dbfs
from app.audio.wav_writer import WavWriter
from app.core.state import audio_queue, event_bus, slide_context_service, vocabulary_service
from app.events.events import TranscriptCreated, VocabularyUpdated
from app.transcription.hallucination_guard import TranscriptHallucinationGuard
from app.transcription.streaming_assembler import StreamingTranscriptAssembler
from app.transcription.whisper_service import WhisperService


class TranscriptionWorker:
    def __init__(self) -> None:
        self.whisper = WhisperService()
        self.writer = WavWriter()
        self.hallucination_guard = TranscriptHallucinationGuard()
        self.assembler = StreamingTranscriptAssembler(
            low_confidence_threshold=float(
                os.getenv("WHISPER_LOW_CONFIDENCE_THRESHOLD", "0.65")
            )
        )

    def stop(self) -> None:
        audio_queue.stop()

    def finalize_meeting(self, meeting_id: str) -> None:
        snapshot = self.assembler.finalize(meeting_id)
        if snapshot is not None:
            event_bus.publish(
                TranscriptCreated(
                    text=snapshot.text,
                    meeting_id=meeting_id,
                    segment_id=snapshot.segment_id,
                    revision=snapshot.revision,
                    operation="replace",
                    is_final=True,
                    words=snapshot.words,
                    average_confidence=snapshot.average_confidence,
                    low_confidence_count=snapshot.low_confidence_count,
                )
            )

    def finish_meeting(self, meeting_id: str) -> None:
        self.assembler.forget(meeting_id)

    async def start(self) -> None:
        print("Transcription worker started")

        while True:
            job = await asyncio.to_thread(audio_queue.get)
            if job is None:
                print("Transcription worker stopped")
                return

            filename: str | None = None

            try:
                pcm_audio = job.pcm_audio
                loudness = pcm_dbfs(pcm_audio)
                print(
                    f"Processing PCM chunk for meeting={job.meeting_id}: "
                    f"{len(pcm_audio)} bytes, level={loudness:.1f} dBFS"
                )

                if not contains_speech_energy(pcm_audio, threshold_dbfs=-50.0):
                    print("Chunk skipped: probable silence")
                    continue

                with tempfile.NamedTemporaryFile(
                    suffix=".wav",
                    delete=False,
                ) as temporary_file:
                    filename = temporary_file.name

                self.writer.save(filename, pcm_audio, sample_rate=16_000)

                # faster-whisper is synchronous and GPU-heavy; keep it off the
                # FastAPI event loop so WebSockets remain responsive.
                vocabulary_context = vocabulary_service.context_for(job.meeting_id)
                result = await asyncio.to_thread(
                    self.whisper.transcribe,
                    filename,
                    hotwords=vocabulary_context.hotwords,
                    initial_prompt=vocabulary_context.initial_prompt,
                )

                result, guard_report = self.hallucination_guard.sanitize(
                    result,
                    active_terms=vocabulary_context.active_terms,
                )
                if guard_report.changed:
                    print(
                        "HALLUCINATION GUARD:",
                        {
                            "removed_words": guard_report.removed_word_count,
                            "collapsed_words": guard_report.collapsed_word_count,
                            "phrases": list(guard_report.removed_phrases),
                            "character_runs": list(guard_report.removed_character_runs),
                        },
                    )
                if not result.text.strip():
                    print("Chunk skipped: hallucination guard removed all text")
                    continue

                # Match the raw, sanitized speech against the uploaded deck.
                # This happens before terminology correction so slide words do
                # not create a self-reinforcing matching loop.
                slide_update = slide_context_service.observe(
                    job.meeting_id,
                    result.text,
                )
                if slide_update is not None:
                    print(
                        "SLIDE CONTEXT:",
                        {
                            "slide": slide_update.slide_number,
                            "title": slide_update.slide_title,
                            "auto": slide_update.auto_match,
                            "score": slide_update.match_score,
                        },
                    )
                    slide_vocabulary = vocabulary_service.set_slide_context(
                        job.meeting_id,
                        slide_number=slide_update.slide_number,
                        slide_title=slide_update.slide_title,
                        slide_terms=slide_update.slide_terms,
                        auto_match=slide_update.auto_match,
                    )
                    if slide_vocabulary is not None:
                        event_bus.publish(
                            VocabularyUpdated(slide_vocabulary.to_dict())
                        )

                # Use the preliminary transcript to select relevant glossary
                # categories, then apply safe alias/confidence-aware correction
                # to this same chunk before it reaches the rolling assembler.
                vocabulary_update = vocabulary_service.observe(
                    job.meeting_id,
                    result.text,
                )
                if vocabulary_update is not None:
                    event_bus.publish(VocabularyUpdated(vocabulary_update.to_dict()))

                result, correction_update = vocabulary_service.correct_result(
                    job.meeting_id,
                    result,
                )
                if correction_update is not None:
                    event_bus.publish(VocabularyUpdated(correction_update.to_dict()))

                snapshot = self.assembler.add(job.meeting_id, result)
                print("RAW TRANSCRIPT:", result.text)
                if result.average_confidence is not None:
                    print(
                        "RAW WORD CONFIDENCE:",
                        f"{result.average_confidence:.1%}",
                    )
                if result.corrections:
                    print("VOCABULARY CORRECTIONS:", list(result.corrections))
                print(
                    "ASSEMBLED TRANSCRIPT:",
                    snapshot.text if snapshot is not None else "",
                )

                if snapshot is not None:
                    event_bus.publish(
                        TranscriptCreated(
                            text=snapshot.text,
                            meeting_id=job.meeting_id,
                            segment_id=snapshot.segment_id,
                            revision=snapshot.revision,
                            operation="replace",
                            is_final=False,
                            words=snapshot.words,
                            average_confidence=snapshot.average_confidence,
                            low_confidence_count=snapshot.low_confidence_count,
                        )
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print("Transcription error:", repr(exc))
            finally:
                if filename:
                    try:
                        os.remove(filename)
                    except OSError:
                        pass
                audio_queue.task_done(job)
