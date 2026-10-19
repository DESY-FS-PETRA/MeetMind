from __future__ import annotations

from dataclasses import dataclass
import os
import re


@dataclass(frozen=True, slots=True)
class WordResult:
    text: str
    probability: float | None = None
    start: float | None = None
    end: float | None = None

    def to_dict(self, *, low_confidence_threshold: float) -> dict:
        probability = (
            round(float(self.probability), 4)
            if self.probability is not None
            else None
        )
        normalized = re.sub(r"[^a-z']", "", self.text.casefold())
        function_words = {
            "a", "an", "the", "to", "of", "in", "on", "at", "and", "or",
            "is", "are", "was", "were", "be", "for", "it", "as", "by",
        }
        threshold = low_confidence_threshold
        if normalized in function_words:
            threshold = float(os.getenv("WHISPER_FUNCTION_WORD_THRESHOLD", "0.35"))

        return {
            "text": self.text,
            "probability": probability,
            "start": round(float(self.start), 3) if self.start is not None else None,
            "end": round(float(self.end), 3) if self.end is not None else None,
            "needs_review": (
                probability is not None
                and probability < threshold
            ),
        }


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    text: str
    words: tuple[WordResult, ...] = ()
    average_confidence: float | None = None
    corrections: tuple[dict, ...] = ()

    @classmethod
    def from_text(cls, text: str) -> "TranscriptionResult":
        words = tuple(WordResult(token) for token in text.split() if token)
        return cls(text=text.strip(), words=words, average_confidence=None)
