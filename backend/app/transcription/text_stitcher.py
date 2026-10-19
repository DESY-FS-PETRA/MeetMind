from __future__ import annotations

import re
from difflib import SequenceMatcher


_EDGE_PUNCTUATION = re.compile(r"(^[^\w']+|[^\w']+$)")


def _tokens(text: str) -> list[str]:
    return text.split()


def _normalise_token(token: str) -> str:
    return _EDGE_PUNCTUATION.sub("", token).casefold()


class TranscriptStitcher:
    """Remove words repeated because consecutive audio chunks overlap."""

    def __init__(self, max_overlap_words: int = 40) -> None:
        self.max_overlap_words = max_overlap_words
        self._previous_raw_by_meeting: dict[str, str] = {}

    def stitch(self, meeting_id: str, current_raw: str) -> str:
        current_raw = " ".join(current_raw.split()).strip()
        if not current_raw:
            return ""

        previous_raw = self._previous_raw_by_meeting.get(meeting_id, "")
        self._previous_raw_by_meeting[meeting_id] = current_raw
        if not previous_raw:
            return current_raw

        previous_tokens = _tokens(previous_raw)
        current_tokens = _tokens(current_raw)
        overlap = self._find_overlap(previous_tokens, current_tokens)

        new_tokens = current_tokens[overlap:]
        return " ".join(new_tokens).strip()

    def forget(self, meeting_id: str) -> None:
        self._previous_raw_by_meeting.pop(meeting_id, None)

    def _find_overlap(
        self,
        previous_tokens: list[str],
        current_tokens: list[str],
    ) -> int:
        limit = min(
            self.max_overlap_words,
            len(previous_tokens),
            len(current_tokens),
        )

        previous_normalised = [_normalise_token(token) for token in previous_tokens]
        current_normalised = [_normalise_token(token) for token in current_tokens]

        # Prefer an exact overlap before considering fuzzy matching.  This is
        # important when the new chunk completes an unfinished phrase from the
        # previous chunk.  For example:
        #
        #   previous: "... tacos al pastor are my"
        #   current:  "tacos al pastor are my favorite ..."
        #
        # A fuzzy six-word window is superficially similar, but the true exact
        # overlap is five words.  Returning six would incorrectly delete the
        # newly completed word "favorite".
        for size in range(limit, 0, -1):
            left = previous_normalised[-size:]
            right = current_normalised[:size]
            if all(left) and all(right) and left == right:
                return size

        # Only use fuzzy matching when no exact suffix/prefix overlap exists.
        # Require aligned boundary tokens so SequenceMatcher cannot accept a
        # one-word shifted window and over-trim new speech.
        for size in range(limit, 0, -1):
            left = previous_normalised[-size:]
            right = current_normalised[:size]
            if not all(left) or not all(right):
                continue

            if size == 1:
                if left[0] == right[0] and len(left[0]) >= 5:
                    return 1
                continue

            if left[0] != right[0] or left[-1] != right[-1]:
                continue

            # Whisper may alter punctuation or one short word in the overlap.
            # Fuzzy matching is intentionally conservative for short overlaps.
            ratio = SequenceMatcher(None, left, right, autojunk=False).ratio()
            if size >= 5 and ratio >= 0.78:
                return size
            if size >= 3 and ratio >= 0.86:
                return size
            if size == 2 and ratio >= 0.99:
                return size

        return 0
