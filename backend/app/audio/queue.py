from __future__ import annotations

from dataclasses import dataclass
from queue import Queue
from threading import Condition
from time import monotonic


@dataclass(slots=True)
class AudioJob:
    meeting_id: str
    pcm_audio: bytes


class AudioQueue:
    """Thread-safe audio queue with per-meeting pending job tracking."""

    def __init__(self) -> None:
        self.queue: Queue[AudioJob | None] = Queue()
        self._condition = Condition()
        self._pending_by_meeting: dict[str, int] = {}

    def put(self, audio: bytes, meeting_id: str) -> None:
        if not audio or not meeting_id:
            return

        job = AudioJob(meeting_id=meeting_id, pcm_audio=audio)
        with self._condition:
            self._pending_by_meeting[meeting_id] = (
                self._pending_by_meeting.get(meeting_id, 0) + 1
            )
        self.queue.put(job)

    def get(self) -> AudioJob | None:
        return self.queue.get()

    def stop(self) -> None:
        self.queue.put(None)

    def task_done(self, job: AudioJob) -> None:
        self.queue.task_done()
        with self._condition:
            remaining = max(
                0,
                self._pending_by_meeting.get(job.meeting_id, 1) - 1,
            )
            if remaining:
                self._pending_by_meeting[job.meeting_id] = remaining
            else:
                self._pending_by_meeting.pop(job.meeting_id, None)
            self._condition.notify_all()

    def pending(self, meeting_id: str) -> int:
        with self._condition:
            return self._pending_by_meeting.get(meeting_id, 0)

    def wait_until_idle(self, meeting_id: str, timeout: float = 90.0) -> bool:
        """Block until all queued/in-flight jobs for a meeting are finished."""
        deadline = monotonic() + timeout
        with self._condition:
            while self._pending_by_meeting.get(meeting_id, 0) > 0:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
        return True

    def size(self) -> int:
        return self.queue.qsize()
