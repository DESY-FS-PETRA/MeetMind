from __future__ import annotations

import re
from dataclasses import replace
from statistics import mean

from app.transcription.result import WordResult


_MULTI_SPACE = re.compile(r"\s+")
_EDGE_PUNCTUATION = re.compile(r"(^[^\w+']+|[^\w+']+$)")
_SENTENCE_END = (".", "?", "!")
_PROTECTED_DUPLICATE_TRIGGERS = (
    "not confused with",
    "transcribed as",
    "incorrect transcription is",
    "whisper wrote",
    "recognized as",
    "recognised as",
    "heard as",
    "mistaken for",
    "instead of",
)
_QUALIFIER_RE = re.compile(r"^(?:\d+|[ivxlcdm]+)$", re.IGNORECASE)


def _comparison_token(value: str) -> str:
    token = _EDGE_PUNCTUATION.sub("", value).casefold().replace("-", "")
    # A singular/plural variation at a chunk boundary should not prevent a
    # repeated technical phrase from being recognized (beamline/beamlines).
    if (
        len(token) > 5
        and token.endswith("s")
        and not token.endswith(("ss", "ics", "sis"))
    ):
        token = token[:-1]
    return token


class TranscriptCleaner:
    """Conservative word-preserving cleanup for the rolling transcript.

    Phase 5.7.1 additionally joins Whisper's split hyphen tokens and removes
    only *immediately repeated* words or multiword phrases. It does not rewrite
    arbitrary recognized vocabulary; scientific correction remains in the
    confidence-aware vocabulary service.
    """

    def clean_words(
        self,
        words: list[WordResult] | tuple[WordResult, ...],
        *,
        final: bool,
    ) -> list[WordResult]:
        cleaned = [
            replace(word, text=_MULTI_SPACE.sub(" ", word.text).strip())
            for word in words
            if _MULTI_SPACE.sub(" ", word.text).strip()
        ]
        if not cleaned:
            return []

        cleaned = self._merge_hyphenated_tokens(cleaned)
        cleaned = self._remove_immediate_repetitions(cleaned)
        cleaned = self._remove_nearby_technical_duplicates(cleaned)
        cleaned = self._remove_immediate_repetitions(cleaned)

        # Whisper can emit a provisional sentence boundary at an overlapping
        # chunk edge, for example "A cold dip. restores". Remove only that
        # narrow pattern; do not rewrite lexical content.
        for index in range(len(cleaned) - 1):
            current = cleaned[index]
            next_word = cleaned[index + 1]
            following = next_word.text
            first_alpha = next((char for char in following if char.isalpha()), "")
            mixed_case_brand = bool(re.match(r"^[a-z][A-Z]", following.lstrip("\"'([{“‘")))
            gap = (
                next_word.start - current.end
                if next_word.start is not None and current.end is not None
                else None
            )
            short_or_unknown_pause = gap is None or gap < 0.35
            if (
                current.text.endswith(".")
                and first_alpha.islower()
                and not mixed_case_brand
                and short_or_unknown_pause
            ):
                cleaned[index] = replace(current, text=current.text[:-1])

        if final:
            sentence_start = True
            for index, word in enumerate(cleaned):
                text = word.text
                if sentence_start:
                    text = self._capitalize_first_alpha(text)
                    cleaned[index] = replace(word, text=text)
                sentence_start = text.endswith(_SENTENCE_END)

            if not cleaned[-1].text.endswith(_SENTENCE_END):
                cleaned[-1] = replace(cleaned[-1], text=f"{cleaned[-1].text}.")

        return cleaned

    @staticmethod
    def text(words: list[WordResult] | tuple[WordResult, ...]) -> str:
        return " ".join(word.text for word in words if word.text).strip()

    @staticmethod
    def _capitalize_first_alpha(text: str) -> str:
        chars = list(text)
        for index, char in enumerate(chars):
            if char.isalpha():
                chars[index] = char.upper()
                break
        return "".join(chars)

    @staticmethod
    def _merge_hyphenated_tokens(words: list[WordResult]) -> list[WordResult]:
        output: list[WordResult] = []
        index = 0
        while index < len(words):
            current = words[index]
            if index + 1 >= len(words):
                output.append(current)
                break

            following = words[index + 1]
            left = current.text
            right = following.text
            should_merge = (
                (right.startswith("-") and len(right) > 1 and any(char.isalnum() for char in left))
                or (left.endswith("-") and len(left) > 1 and any(char.isalnum() for char in right))
                or left == "-"
                or right == "-"
            )
            if not should_merge:
                output.append(current)
                index += 1
                continue

            if right == "-" and index + 2 < len(words):
                third = words[index + 2]
                merged_text = f"{left.rstrip('-')}-{third.text.lstrip('-')}"
                merged = TranscriptCleaner._merge_word_metadata(
                    merged_text,
                    [current, following, third],
                )
                output.append(merged)
                index += 3
                continue

            if left == "-" and output:
                previous = output.pop()
                merged_text = f"{previous.text.rstrip('-')}-{right.lstrip('-')}"
                output.append(
                    TranscriptCleaner._merge_word_metadata(
                        merged_text,
                        [previous, current, following],
                    )
                )
                index += 2
                continue

            merged_text = (
                f"{left.rstrip('-')}-{right.lstrip('-')}"
                if not left.endswith("-")
                else f"{left}{right.lstrip('-')}"
            )
            output.append(
                TranscriptCleaner._merge_word_metadata(
                    merged_text,
                    [current, following],
                )
            )
            index += 2
        return output

    @staticmethod
    def _merge_word_metadata(text: str, words: list[WordResult]) -> WordResult:
        probabilities = [item.probability for item in words if item.probability is not None]
        return WordResult(
            text=text,
            probability=mean(probabilities) if probabilities else None,
            start=next((item.start for item in words if item.start is not None), None),
            end=next((item.end for item in reversed(words) if item.end is not None), None),
        )


    @staticmethod
    def _remove_nearby_technical_duplicates(words: list[WordResult]) -> list[WordResult]:
        """Remove repeated technical list items within one short sentence span.

        Streaming overlap may produce sequences such as ``PtyPy, PyNX, pyFAI,
        cSAXS code, PtyPy, and cSAXS code``. These are not adjacent exact
        repetitions, but the repeated mixed-case/acronym terms occur within a
        compact comma/conjunction list. Keep the first occurrence and remove
        only later copies inside a 14-token sentence window.
        """
        output: list[WordResult] = []
        index = 0
        connector_tokens = {"and", "or", "plus", "with", "the", "a", "an"}
        while index < len(words):
            removed = False
            sentence_start = 0
            for position in range(len(output) - 1, -1, -1):
                if output[position].text.rstrip().endswith(_SENTENCE_END):
                    sentence_start = position + 1
                    break
            prefix = " ".join(
                _comparison_token(item.text)
                for item in output[max(sentence_start, len(output) - 14) :]
                if _comparison_token(item.text)
            )
            protected_context = any(
                trigger in prefix for trigger in _PROTECTED_DUPLICATE_TRIGGERS
            )

            for size in range(min(3, len(words) - index), 0, -1):
                current_words = words[index : index + size]
                current_tokens = [_comparison_token(item.text) for item in current_words]
                if not all(current_tokens) or current_tokens[0] in connector_tokens:
                    continue
                if protected_context:
                    continue
                raw_phrase = " ".join(item.text for item in current_words)
                technical = bool(
                    re.search(r"[a-z][A-Z]|[A-Z]{2,}|\d|[-+]", raw_phrase)
                    or (size >= 2 and sum(len(token) for token in current_tokens) >= 10)
                )
                if not technical:
                    continue

                search_start = max(sentence_start, len(output) - 14)
                for previous_start in range(len(output) - size, search_start - 1, -1):
                    previous_tokens = [
                        _comparison_token(item.text)
                        for item in output[previous_start : previous_start + size]
                    ]
                    if previous_tokens != current_tokens:
                        continue

                    # Preserve shared names with distinct numeric/Roman
                    # qualifiers, e.g. ``PETRA III and PETRA IV``.
                    if size == 1:
                        previous_follow = (
                            _comparison_token(output[previous_start + 1].text)
                            if previous_start + 1 < len(output)
                            else ""
                        )
                        current_follow = (
                            _comparison_token(words[index + 1].text)
                            if index + 1 < len(words)
                            else ""
                        )
                        if (
                            previous_follow
                            and current_follow
                            and _QUALIFIER_RE.fullmatch(previous_follow)
                            and _QUALIFIER_RE.fullmatch(current_follow)
                            and previous_follow != current_follow
                        ):
                            continue

                    bridge = output[previous_start + size :]
                    bridge_text = " ".join(item.text.casefold() for item in bridge)
                    if not (
                        any("," in item.text or ";" in item.text for item in bridge)
                        or re.search(r"\b(?:and|or|plus|with)\b", bridge_text)
                    ):
                        continue
                    # Remove a dangling connector/article immediately before
                    # the duplicated list item (", and the cSAXS code").
                    while output and _comparison_token(output[-1].text) in connector_tokens:
                        output.pop()
                    index += size
                    removed = True
                    break
                if removed:
                    break
            if removed:
                continue
            output.append(words[index])
            index += 1
        return output

    @staticmethod
    def _remove_immediate_repetitions(words: list[WordResult]) -> list[WordResult]:
        output: list[WordResult] = []
        index = 0
        while index < len(words):
            current_token = _comparison_token(words[index].text)
            if output and current_token and current_token == _comparison_token(output[-1].text):
                # Keep the higher-confidence copy of an immediately duplicated word.
                old = output[-1]
                old_score = old.probability if old.probability is not None else -1.0
                new_score = words[index].probability if words[index].probability is not None else -1.0
                if new_score > old_score:
                    output[-1] = words[index]
                index += 1
                continue

            repeated_size = 0
            max_size = min(8, len(output), len(words) - index)
            for size in range(max_size, 1, -1):
                previous = [_comparison_token(item.text) for item in output[-size:]]
                current = [_comparison_token(item.text) for item in words[index : index + size]]
                if not all(previous) or previous != current:
                    continue
                # Avoid removing generic two-word constructions such as
                # "this is ... this is ...". Longer immediate repeats are safe;
                # two-word repeats require a scientific-looking/content token.
                if size == 2 and not any(
                    len(token) >= 6 or any(char.isdigit() for char in token)
                    for token in current
                ):
                    continue
                repeated_size = size
                break

            if repeated_size:
                index += repeated_size
                continue

            output.append(words[index])
            index += 1
        return output
