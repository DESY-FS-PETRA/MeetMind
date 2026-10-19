from __future__ import annotations

import asyncio
import time

from app.audio.queue import AudioQueue
from app.events.events import TranscriptCreated, VocabularyUpdated
from app.meeting.session import MeetingSession
from app.storage.meeting_storage import MeetingStorage
from app.websocket.frontend_socket import broadcast_transcript


class MeetingEngine:
    DUPLICATE_WINDOW_SECONDS = 20.0

    def __init__(self, event_bus, audio_queue: AudioQueue) -> None:
        self.session = MeetingSession()
        self.storage = MeetingStorage()
        self.event_bus = event_bus
        self.audio_queue = audio_queue
        self.current_meeting_id: str | None = None
        self._last_transcript_by_meeting: dict[str, tuple[str, float]] = {}

        self.event_bus.subscribe(TranscriptCreated, self.handle_transcript)
        self.event_bus.subscribe(VocabularyUpdated, self.handle_vocabulary_update)

    def start_meeting(self, title: str = "Conference Meeting") -> str:
        meeting_id = self.session.start(title)
        self.current_meeting_id = meeting_id
        self._last_transcript_by_meeting.pop(meeting_id, None)
        self.storage.create_meeting(
            meeting_id,
            title,
            started_at=self.session.start_time or "",
        )
        print("ENGINE: Meeting started", meeting_id)
        return meeting_id

    async def stop_meeting(self, timeout_seconds: float = 90.0) -> dict:
        meeting_id = self.current_meeting_id
        if not meeting_id:
            raise RuntimeError("No active meeting")

        # The browser closes the audio WebSocket before calling this endpoint.
        # All final decoded PCM chunks are therefore already queued. Wait for
        # Whisper and transcript persistence before marking the meeting done.
        print(
            f"ENGINE: Waiting for {self.audio_queue.pending(meeting_id)} "
            f"pending transcription job(s)"
        )
        drained = await asyncio.to_thread(
            self.audio_queue.wait_until_idle,
            meeting_id,
            timeout_seconds,
        )
        if not drained:
            raise TimeoutError("Timed out while finalizing the meeting transcript")

        session_data = self.session.stop()
        meeting = self.storage.complete_meeting(
            meeting_id,
            end_time=session_data["end_time"],
        )
        self.current_meeting_id = None
        self._last_transcript_by_meeting.pop(meeting_id, None)
        print("ENGINE: Meeting finalized", meeting_id)
        return {
            **meeting,
            "transcript": self.storage.load_transcript(meeting_id),
        }

    def get_current(self) -> dict:
        return self.session.get_data()

    @staticmethod
    def _normalise_text(text: str) -> str:
        return " ".join(text.casefold().split())

    def handle_transcript(self, event: TranscriptCreated) -> None:
        meeting_id = event.meeting_id
        print("ENGINE RECEIVED TRANSCRIPT", event.id, "meeting=", meeting_id)

        if not self.storage.get_meeting(meeting_id):
            print("Unknown meeting. Transcript ignored:", meeting_id)
            return

        transcript_key = self._normalise_text(event.text)
        now = time.monotonic()
        previous = self._last_transcript_by_meeting.get(meeting_id)

        if (
            previous
            and transcript_key
            and transcript_key == previous[0]
            and now - previous[1] < self.DUPLICATE_WINDOW_SECONDS
            and not event.is_final
        ):
            print("Duplicate transcript ignored:", event.text)
            return

        self._last_transcript_by_meeting[meeting_id] = (transcript_key, now)
        if event.operation == "replace":
            self.storage.upsert_transcript(
                meeting_id,
                event.text,
                segment_id=event.segment_id,
                event_id=event.id,
                created_at=event.time,
                revision=event.revision,
                is_final=event.is_final,
                words=event.words,
                average_confidence=event.average_confidence,
                low_confidence_count=event.low_confidence_count,
            )
        else:
            self.storage.save_transcript(
                meeting_id,
                event.text,
                event_id=event.id,
                created_at=event.time,
            )

        # Live broadcast is useful while the meeting is stopping too; the
        # frontend keeps this socket open until finalization finishes.
        if meeting_id == self.current_meeting_id:
            asyncio.create_task(
                broadcast_transcript(
                    {
                        "id": event.id,
                        "meeting_id": meeting_id,
                        "segment_id": event.segment_id,
                        "revision": event.revision,
                        "operation": event.operation,
                        "is_final": event.is_final,
                        "text": event.text,
                        "words": event.words,
                        "average_confidence": event.average_confidence,
                        "low_confidence_count": event.low_confidence_count,
                        "time": event.time,
                    }
                )
            )
            print("Transcript broadcast scheduled")

    def handle_vocabulary_update(self, event: VocabularyUpdated) -> None:
        meeting_id = event.meeting_id
        if not self.storage.get_meeting(meeting_id):
            print("Unknown meeting. Vocabulary update ignored:", meeting_id)
            return

        self.storage.save_vocabulary_state(meeting_id, event.payload)
        if meeting_id == self.current_meeting_id:
            asyncio.create_task(
                broadcast_transcript(
                    {
                        "type": "vocabulary_update",
                        **event.payload,
                        "time": event.time,
                    }
                )
            )
            print("Vocabulary update broadcast scheduled")
