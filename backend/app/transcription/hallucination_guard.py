from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import mean
from typing import Iterable

from app.transcription.result import TranscriptionResult, WordResult


_EDGE_RE = re.compile(r"(^[^\w']+|[^\w']+$)")
_LONG_CHARACTER_RUN_RE = re.compile(r"^(.)\1{7,}$", re.IGNORECASE)


def _normalise_token(value: str) -> str:
    value = _EDGE_RE.sub("", value).casefold()
    value = value.replace("x-ray", "x ray")
    return re.sub(r"[^a-z0-9']+", "", value)


def _normalise_phrase(value: str) -> str:
    return " ".join(
        token
        for token in (_normalise_token(part) for part in value.split())
        if token
    )


@dataclass(frozen=True, slots=True)
class HallucinationGuardReport:
    removed_word_count: int = 0
    collapsed_word_count: int = 0
    removed_phrases: tuple[str, ...] = ()
    removed_character_runs: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(
            self.removed_word_count
            or self.collapsed_word_count
            or self.removed_phrases
            or self.removed_character_runs
        )


class TranscriptHallucinationGuard:
    """Removes obvious decoder loops before they reach the rolling transcript.

    The guard is intentionally conservative. It targets only pathological
    patterns that are not normal meeting speech: very long single-character
    runs and a multi-word phrase repeated consecutively three or more times.
    When the repeated phrase is one of the active hotwords, the whole run is
    removed because it is likely prompt-induced. Otherwise the run is collapsed
    to a single copy.
    """

    def __init__(
        self,
        *,
        minimum_phrase_words: int = 2,
        maximum_phrase_words: int = 8,
        minimum_repetitions: int = 3,
        minimum_single_token_repetitions: int = 6,
    ) -> None:
        self.minimum_phrase_words = minimum_phrase_words
        self.maximum_phrase_words = maximum_phrase_words
        self.minimum_repetitions = minimum_repetitions
        self.minimum_single_token_repetitions = minimum_single_token_repetitions

    def sanitize(
        self,
        result: TranscriptionResult,
        *,
        active_terms: Iterable[str] = (),
    ) -> tuple[TranscriptionResult, HallucinationGuardReport]:
        if not result.words:
            return result, HallucinationGuardReport()

        active = {_normalise_phrase(term) for term in active_terms if term.strip()}
        words = list(result.words)
        removed_character_runs: list[str] = []

        filtered: list[WordResult] = []
        for word in words:
            compact = _normalise_token(word.text)
            if compact and _LONG_CHARACTER_RUN_RE.fullmatch(compact):
                removed_character_runs.append(word.text)
                continue
            filtered.append(word)

        removed_word_count = len(words) - len(filtered)
        collapsed_word_count = 0
        removed_phrases: list[str] = []
        words = filtered

        changed = True
        while changed and words:
            changed = False
            normalized = [_normalise_token(word.text) for word in words]

            # Single-token loops such as "you you you ...".
            index = 0
            while index < len(words):
                token = normalized[index]
                end = index + 1
                while end < len(words) and normalized[end] == token:
                    end += 1
                count = end - index
                if token and count >= self.minimum_single_token_repetitions:
                    removed_phrases.append(" ".join(word.text for word in words[index:end]))
                    removed_word_count += count
                    del words[index:end]
                    changed = True
                    break
                index = end
            if changed:
                continue

            normalized = [_normalise_token(word.text) for word in words]
            max_size = min(self.maximum_phrase_words, len(words) // self.minimum_repetitions)
            for phrase_size in range(max_size, self.minimum_phrase_words - 1, -1):
                found = False
                for start in range(0, len(words) - phrase_size * self.minimum_repetitions + 1):
                    phrase = normalized[start : start + phrase_size]
                    if not all(phrase):
                        continue
                    repetitions = 1
                    while (
                        start + (repetitions + 1) * phrase_size <= len(words)
                        and normalized[
                            start + repetitions * phrase_size :
                            start + (repetitions + 1) * phrase_size
                        ]
                        == phrase
                    ):
                        repetitions += 1
                    if repetitions < self.minimum_repetitions:
                        continue

                    end = start + repetitions * phrase_size
                    phrase_text = " ".join(word.text for word in words[start : start + phrase_size])
                    normalized_phrase = " ".join(phrase)
                    if normalized_phrase in active:
                        # Prompt-induced loop: remove the entire run.
                        removed_word_count += end - start
                        removed_phrases.append(phrase_text)
                        del words[start:end]
                    else:
                        # Generic decoder loop: retain one copy only.
                        collapsed = (repetitions - 1) * phrase_size
                        collapsed_word_count += collapsed
                        removed_phrases.append(phrase_text)
                        del words[start + phrase_size : end]
                    changed = True
                    found = True
                    break
                if found:
                    break

        probabilities = [
            word.probability for word in words if word.probability is not None
        ]
        corrections = list(result.corrections)
        report = HallucinationGuardReport(
            removed_word_count=removed_word_count,
            collapsed_word_count=collapsed_word_count,
            removed_phrases=tuple(removed_phrases),
            removed_character_runs=tuple(removed_character_runs),
        )
        if report.changed:
            corrections.append(
                {
                    "type": "hallucination_guard",
                    "removed_word_count": removed_word_count,
                    "collapsed_word_count": collapsed_word_count,
                    "removed_phrases": list(report.removed_phrases),
                    "removed_character_runs": list(report.removed_character_runs),
                }
            )

        sanitized = TranscriptionResult(
            text=" ".join(word.text for word in words).strip(),
            words=tuple(words),
            average_confidence=(
                mean(probabilities) if probabilities else None
            ),
            corrections=tuple(corrections),
        )
        return sanitized, report
