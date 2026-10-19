from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.storage.meeting_storage import MeetingStorage
from app.presentation.offline_alignment import OfflineSlideAligner


_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")
_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "into", "using",
    "are", "was", "were", "will", "have", "has", "our", "their", "about",
    "slide", "figure", "result", "results", "data", "show", "shows",
}


def _normalise(value: str) -> str:
    value = value.casefold().replace("x-ray", "x ray").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+.-]+", " ", value)).strip()


def _tokens(value: str) -> set[str]:
    return {
        token for token in _TOKEN_RE.findall(_normalise(value))
        if len(token) >= 3 and token not in _STOPWORDS
    }


def _contains(text: str, phrase: str) -> bool:
    return bool(phrase) and f" {phrase} " in f" {text} "


@dataclass(frozen=True, slots=True)
class SlideContextSnapshot:
    meeting_id: str
    presentation_id: str
    presentation_title: str
    slide_number: int
    slide_count: int
    slide_title: str
    slide_terms: tuple[str, ...]
    auto_match: bool
    match_score: float | None
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "meeting_id": self.meeting_id,
            "presentation_id": self.presentation_id,
            "presentation_title": self.presentation_title,
            "slide_number": self.slide_number,
            "slide_count": self.slide_count,
            "slide_title": self.slide_title,
            "slide_terms": list(self.slide_terms),
            "slide_term_count": len(self.slide_terms),
            "auto_match": self.auto_match,
            "match_score": self.match_score,
            "updated_at": self.updated_at,
        }


class SlideContextService:
    """Tracks the current uploaded slide and matches speech to slide text.

    Matching uses the raw, hallucination-sanitized transcript. It does not use
    vocabulary-corrected text, preventing a presentation term from creating a
    self-reinforcing feedback loop.
    """

    def __init__(self, storage: MeetingStorage) -> None:
        self.storage = storage
        self.min_score = max(4.0, float(os.getenv("SLIDE_MATCH_MIN_SCORE", "5.0")))
        self.min_margin = max(0.5, float(os.getenv("SLIDE_MATCH_MIN_MARGIN", "1.25")))
        self.max_terms = min(max(1, int(os.getenv("SLIDE_VOCABULARY_MAX_TERMS", "14"))), 14)
        self._cache: dict[str, dict[str, Any]] = {}
        self._offline_aligner = OfflineSlideAligner()

    def attach(self, meeting_id: str, presentation_id: str) -> SlideContextSnapshot:
        payload = self.storage.attach_presentation(
            meeting_id,
            presentation_id,
            active_slide_number=1,
            auto_match=True,
        )
        self._cache[meeting_id] = payload
        return self._snapshot(meeting_id, payload)

    def context_for(self, meeting_id: str) -> SlideContextSnapshot | None:
        payload = self._cache.get(meeting_id)
        if payload is None:
            payload = self.storage.get_meeting_presentation(meeting_id)
            if payload is None:
                return None
            self._cache[meeting_id] = payload
        return self._snapshot(meeting_id, payload)

    def activate_manual(self, meeting_id: str, slide_number: int) -> SlideContextSnapshot:
        payload = self.storage.set_active_slide(
            meeting_id,
            slide_number,
            auto_match=False,
            match_score=None,
            source="manual",
        )
        self._cache[meeting_id] = payload
        return self._snapshot(meeting_id, payload)

    def enable_auto(self, meeting_id: str) -> SlideContextSnapshot:
        payload = self.storage.set_slide_auto_match(meeting_id, True)
        self._cache[meeting_id] = payload
        return self._snapshot(meeting_id, payload)

    def observe(self, meeting_id: str, text: str) -> SlideContextSnapshot | None:
        if len(text.strip()) < 20:
            return None
        payload = self._cache.get(meeting_id) or self.storage.get_meeting_presentation(meeting_id)
        if payload is None or not payload.get("auto_match", True):
            return None

        slides = list(payload.get("slides") or [])
        if not slides:
            return None
        current_number = int(payload.get("active_slide_number") or 1)
        normalized = _normalise(text)
        speech_tokens = _tokens(text)
        if not speech_tokens:
            return None

        scored: list[tuple[float, int, dict[str, Any]]] = []
        for slide in slides:
            number = int(slide["slide_number"])
            title = str(slide.get("title") or "")
            body = str(slide.get("body_text") or "")
            notes = str(slide.get("notes_text") or "")
            keywords = [str(item) for item in slide.get("keywords") or []]

            title_tokens = _tokens(title)
            body_tokens = _tokens(f"{body} {notes}")
            score = 2.2 * len(speech_tokens & title_tokens)
            score += min(4.0, 0.45 * len(speech_tokens & body_tokens))
            for keyword in keywords:
                keyword_norm = _normalise(keyword)
                if _contains(normalized, keyword_norm):
                    score += 5.0 + min(2.0, 0.35 * len(keyword_norm.split()))
                else:
                    overlap = len(speech_tokens & _tokens(keyword))
                    score += 1.2 * overlap

            # Presentations usually advance sequentially. These small bonuses
            # stabilize matching without preventing an explicit jump.
            distance = number - current_number
            if distance == 0:
                score += 1.0
            elif distance == 1:
                score += 1.6
            elif distance == 2:
                score += 0.7
            elif distance < 0:
                score -= min(2.0, abs(distance) * 0.25)

            scored.append((score, number, slide))

        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best_number, _ = scored[0]
        current_score = next((score for score, number, _ in scored if number == current_number), 0.0)
        second_score = scored[1][0] if len(scored) > 1 else 0.0

        if best_number == current_number:
            return None
        if best_score < self.min_score:
            return None
        if best_score - max(current_score, second_score) < self.min_margin:
            return None

        updated = self.storage.set_active_slide(
            meeting_id,
            best_number,
            auto_match=True,
            match_score=round(best_score, 3),
            source="automatic",
        )
        self._cache[meeting_id] = updated
        return self._snapshot(meeting_id, updated)


    def align_offline(self, meeting_id: str) -> list[dict[str, Any]]:
        """Globally realign a completed recording to the entire slide deck.

        Live matching remains local and low-latency. Recorded meetings can use
        the completed transcript and slide order together, which is much more
        reliable for image-heavy scientific decks and appendix slides.
        """
        payload = self.storage.get_meeting_presentation(meeting_id)
        if payload is None:
            return []
        transcript = self.storage.load_final_transcript_text(meeting_id)
        if not transcript.strip():
            return []
        boundaries = self._offline_aligner.align(transcript, payload)
        if not boundaries:
            return []
        events = [
            {
                "slide_number": item.slide_number,
                "transcript_character_offset": item.offset,
                "source": "offline-global",
                "match_score": item.score,
            }
            for item in boundaries
        ]
        self.storage.replace_slide_events(meeting_id, events)
        refreshed = self.storage.get_meeting_presentation(meeting_id)
        if refreshed is not None:
            self._cache[meeting_id] = refreshed
        return events

    def forget(self, meeting_id: str) -> None:
        self._cache.pop(meeting_id, None)

    def _snapshot(self, meeting_id: str, payload: dict[str, Any]) -> SlideContextSnapshot:
        slide = payload.get("active_slide") or {}
        return SlideContextSnapshot(
            meeting_id=meeting_id,
            presentation_id=str(payload["presentation_id"]),
            presentation_title=str(payload.get("title") or payload.get("filename") or "Presentation"),
            slide_number=int(payload.get("active_slide_number") or slide.get("slide_number") or 1),
            slide_count=int(payload.get("slide_count") or len(payload.get("slides") or [])),
            slide_title=str(slide.get("title") or ""),
            slide_terms=tuple(str(item) for item in (slide.get("keywords") or [])[: self.max_terms]),
            auto_match=bool(payload.get("auto_match", True)),
            match_score=(
                float(payload["last_match_score"])
                if payload.get("last_match_score") is not None
                else None
            ),
            updated_at=str(payload.get("updated_at") or datetime.now(timezone.utc).isoformat()),
        )
