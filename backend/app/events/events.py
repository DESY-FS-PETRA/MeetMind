from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


class TranscriptCreated:
    def __init__(
        self,
        text: str,
        meeting_id: str,
        *,
        segment_id: str | None = None,
        revision: int = 1,
        operation: str = "append",
        is_final: bool = False,
        words: list[dict] | tuple[dict, ...] | None = None,
        average_confidence: float | None = None,
        low_confidence_count: int = 0,
    ) -> None:
        self.id = str(uuid4())
        self.meeting_id = meeting_id
        self.segment_id = segment_id or self.id
        self.revision = revision
        self.operation = operation
        self.is_final = is_final
        self.text = text
        self.words = list(words or [])
        self.average_confidence = average_confidence
        self.low_confidence_count = low_confidence_count
        self.time = datetime.now(timezone.utc).isoformat()


class VocabularyUpdated:
    def __init__(self, payload: dict) -> None:
        self.meeting_id = str(payload["meeting_id"])
        self.payload = dict(payload)
        self.time = datetime.now(timezone.utc).isoformat()
