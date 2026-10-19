from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


class MeetingSession:
    def __init__(self) -> None:
        self.active = False
        self.meeting_id: str | None = None
        self.title: str | None = None
        self.start_time: str | None = None
        self.end_time: str | None = None

    def start(self, title: str = "Conference Meeting") -> str:
        if self.active:
            raise RuntimeError("A meeting is already active")

        self.active = True
        self.meeting_id = str(uuid4())
        self.title = title
        self.start_time = datetime.now(timezone.utc).isoformat()
        self.end_time = None
        print("Meeting started:", self.meeting_id)
        return self.meeting_id

    def stop(self) -> dict:
        if not self.active or not self.meeting_id:
            raise RuntimeError("No active meeting")

        self.active = False
        self.end_time = datetime.now(timezone.utc).isoformat()
        print("Meeting stopped")
        return self.get_data()

    def get_data(self) -> dict:
        return {
            "meeting_id": self.meeting_id,
            "title": self.title,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "active": self.active,
        }
