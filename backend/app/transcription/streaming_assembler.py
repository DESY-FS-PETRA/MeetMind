from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from statistics import mean

from app.transcription.result import TranscriptionResult, WordResult
from app.transcription.transcript_cleaner import TranscriptCleaner


_EDGE_PUNCTUATION = re.compile(r"(^[^\w']+|[^\w']+$)")


def _normalise_token(token: str) -> str:
    return _EDGE_PUNCTUATION.sub("", token).casefold()


@dataclass(slots=True)
class _MeetingState:
    committed: list[WordResult] = field(default_factory=list)
    pending: list[WordResult] = field(default_factory=list)
    update_number: int = 0


@dataclass(frozen=True, slots=True)
class TranscriptSnapshot:
    meeting_id: str
    segment_id: str
    text: str
    revision: int
    words: tuple[dict, ...] = ()
    average_confidence: float | None = None
    low_confidence_count: int = 0
    is_final: bool = False


class StreamingTranscriptAssembler:
    """Build one corrected transcript from overlapping Whisper hypotheses.

    The audio chunker intentionally repeats two seconds of audio. Whisper may
    transcribe that overlap with a small variation, so simply appending every
    chunk creates duplicated or contradictory text. This assembler keeps a
    mutable tail and lets a newer chunk replace that tail while preserving the
    older, more contextual wording inside the aligned overlap.
    """

    def __init__(
        self,
        *,
        holdback_words: int = 18,
        max_alignment_words: int = 40,
        low_confidence_threshold: float = 0.65,
    ) -> None:
        if holdback_words < 4:
            raise ValueError("holdback_words must be at least 4")
        if max_alignment_words < holdback_words:
            raise ValueError("max_alignment_words must be >= holdback_words")
        if not 0.0 <= low_confidence_threshold <= 1.0:
            raise ValueError("low_confidence_threshold must be between 0 and 1")

        self.holdback_words = holdback_words
        self.max_alignment_words = max_alignment_words
        self.low_confidence_threshold = low_confidence_threshold
        self.cleaner = TranscriptCleaner()
        self._states: dict[str, _MeetingState] = {}

    def add(
        self,
        meeting_id: str,
        raw: str | TranscriptionResult,
    ) -> TranscriptSnapshot | None:
        current = self._coerce_words(raw)
        if not current:
            return None

        current = self.cleaner.clean_words(current, final=False)
        state = self._states.setdefault(meeting_id, _MeetingState())

        if not state.pending:
            state.pending = current
        else:
            state.pending = self._merge_pending(state.pending, current)

        self._commit_stable_prefix(state)
        state.update_number += 1
        return self._snapshot(meeting_id, state, is_final=False)

    def finalize(self, meeting_id: str) -> TranscriptSnapshot | None:
        state = self._states.get(meeting_id)
        if state is None:
            return None

        state.committed.extend(state.pending)
        state.pending.clear()
        state.committed = self.cleaner.clean_words(state.committed, final=True)
        state.update_number += 1
        return self._snapshot(meeting_id, state, is_final=True)

    def forget(self, meeting_id: str) -> None:
        self._states.pop(meeting_id, None)

    def get_text(self, meeting_id: str) -> str:
        state = self._states.get(meeting_id)
        if state is None:
            return ""
        words = self.cleaner.clean_words(
            [*state.committed, *state.pending],
            final=False,
        )
        return self.cleaner.text(words)

    def _snapshot(
        self,
        meeting_id: str,
        state: _MeetingState,
        *,
        is_final: bool,
    ) -> TranscriptSnapshot | None:
        words = self.cleaner.clean_words(
            [*state.committed, *state.pending],
            final=is_final,
        )
        text = self.cleaner.text(words)
        if not text:
            return None

        probabilities = [
            word.probability
            for word in words
            if word.probability is not None
        ]
        average_confidence = mean(probabilities) if probabilities else None
        serialized = tuple(
            word.to_dict(
                low_confidence_threshold=self.low_confidence_threshold,
            )
            for word in words
        )
        low_confidence_count = sum(
            1 for word in serialized if word["needs_review"]
        )

        return TranscriptSnapshot(
            meeting_id=meeting_id,
            segment_id=f"{meeting_id}:rolling-transcript",
            text=text,
            revision=state.update_number,
            words=serialized,
            average_confidence=(
                round(average_confidence, 4)
                if average_confidence is not None
                else None
            ),
            low_confidence_count=low_confidence_count,
            is_final=is_final,
        )

    @staticmethod
    def _coerce_words(raw: str | TranscriptionResult) -> list[WordResult]:
        if isinstance(raw, TranscriptionResult):
            if raw.words:
                return list(raw.words)
            text = raw.text
        else:
            text = raw

        return [WordResult(token) for token in text.split() if token]

    def _commit_stable_prefix(self, state: _MeetingState) -> None:
        excess = len(state.pending) - self.holdback_words
        if excess <= 0:
            return

        cut = excess
        for index in range(excess - 1, -1, -1):
            if state.pending[index].text.rstrip().endswith((".", "?", "!")):
                cut = index + 1
                break

        state.committed.extend(state.pending[:cut])
        del state.pending[:cut]

    def _merge_pending(
        self,
        previous: list[WordResult],
        current: list[WordResult],
    ) -> list[WordResult]:
        alignment = self._find_alignment(previous, current)
        if alignment is None:
            return [*previous, *current]

        previous_start, overlap_size = alignment
        previous_overlap = previous[previous_start : previous_start + overlap_size]
        current_overlap = current[:overlap_size]

        reconciled: list[WordResult] = []
        for old_word, new_word in zip(previous_overlap, current_overlap):
            old_token = _normalise_token(old_word.text)
            new_token = _normalise_token(new_word.text)

            if old_token == new_token:
                text = (
                    new_word.text
                    if len(new_word.text) > len(old_word.text)
                    else old_word.text
                )
                old_probability = old_word.probability or 0.0
                new_probability = new_word.probability or 0.0
                source = new_word if new_probability > old_probability else old_word
                reconciled.append(
                    WordResult(
                        text=text,
                        probability=max(old_probability, new_probability)
                        if old_word.probability is not None
                        or new_word.probability is not None
                        else None,
                        start=source.start,
                        end=source.end,
                    )
                )
            else:
                # Keep the older overlap hypothesis because it was decoded away
                # from the leading boundary and usually has more context. Its
                # original probability is retained for review highlighting.
                reconciled.append(old_word)

        return [
            *previous[:previous_start],
            *reconciled,
            *current[overlap_size:],
        ]

    def _find_alignment(
        self,
        previous: list[WordResult],
        current: list[WordResult],
    ) -> tuple[int, int] | None:
        if len(current) < 2 or len(previous) < 2:
            return None

        previous_normalised = [
            _normalise_token(word.text) for word in previous
        ]
        current_normalised = [
            _normalise_token(word.text) for word in current
        ]

        search_start = max(0, len(previous) - self.max_alignment_words)
        current_limit = min(len(current), self.max_alignment_words)
        best: tuple[tuple[float, ...], int, int] | None = None

        for previous_start in range(search_start, len(previous)):
            max_size = min(
                len(previous) - previous_start,
                current_limit,
            )
            for size in range(2, max_size + 1):
                old = previous_normalised[previous_start : previous_start + size]
                new = current_normalised[:size]
                if not all(old) or not all(new):
                    continue

                positional_matches = sum(
                    left == right for left, right in zip(old, new)
                )
                exact = positional_matches == size
                ratio = SequenceMatcher(
                    None,
                    old,
                    new,
                    autojunk=False,
                ).ratio()
                boundary_anchor = old[0] == new[0] or old[-1] == new[-1]

                accepted = exact or (
                    size >= 4
                    and ratio >= 0.70
                    and boundary_anchor
                )
                if not accepted:
                    continue

                trailing_old_words = len(previous) - (previous_start + size)
                score = (
                    float(size),
                    ratio,
                    1.0 if exact else 0.0,
                    float(-trailing_old_words),
                    float(previous_start),
                )
                if best is None or score > best[0]:
                    best = (score, previous_start, size)

        if best is None:
            return None
        return best[1], best[2]
