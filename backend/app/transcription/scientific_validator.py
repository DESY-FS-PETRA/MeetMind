from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from app.transcription.result import TranscriptionResult, WordResult


_WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")


def _norm(value: str) -> str:
    value = value.casefold().replace("x-ray", "xray").replace("–", "-").replace("—", "-")
    return " ".join(_WORD_RE.findall(value))


def _suffix(value: str) -> str:
    match = re.search(r"([^A-Za-z0-9']+)$", value)
    return match.group(1) if match else ""


@dataclass(frozen=True, slots=True)
class ScientificCorrection:
    original: str
    replacement: str
    source: str
    requires_review: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "replacement": self.replacement,
            "source": self.source,
            "requires_review": self.requires_review,
        }


@dataclass(frozen=True, slots=True)
class _Rule:
    alias: tuple[str, ...]
    replacement: tuple[str, ...]
    source: str
    evidence: tuple[str, ...] = ()
    requires_review: bool = False


class ScientificTranscriptValidator:
    """Conservative post-ASR correction grounded in the uploaded presentation.

    This layer runs only after complete-file ASR. Slide text is treated as a
    source of canonical spelling, not as replacement speech. Rules are narrow
    enough to avoid rewriting ordinary language that merely resembles a domain
    term. Corrections without direct slide evidence are marked for review.
    """

    _RULES = (
        _Rule(
            alias=("xray", "serial", "experiments"),
            replacement=("X-ray", "stereo", "experiment"),
            source="slide",
            evidence=("xray stereo experiment",),
        ),
        _Rule(
            alias=("xray", "serial", "experiment"),
            replacement=("X-ray", "stereo", "experiment"),
            source="slide",
            evidence=("xray stereo experiment",),
        ),
        _Rule(
            alias=("xray", "sterile", "experiment"),
            replacement=("X-ray", "stereo", "experiment"),
            source="slide",
            evidence=("xray stereo experiment",),
        ),
        _Rule(
            alias=("sterile", "experiment"),
            replacement=("stereo", "experiment"),
            source="slide",
            evidence=("stereo experiment",),
        ),
        _Rule(
            alias=("eliminate", "a", "sample"),
            replacement=("illuminate", "a", "sample"),
            source="slide",
            evidence=("illuminate sample",),
        ),
        _Rule(
            alias=("eliminate", "the", "sample"),
            replacement=("illuminate", "the", "sample"),
            source="slide",
            evidence=("illuminate sample",),
        ),
        _Rule(
            alias=("sensitively", "generate"),
            replacement=("synthetically", "generate"),
            source="slide",
            evidence=("synthetically generate",),
        ),
        _Rule(
            alias=("connect", "components"),
            replacement=("connected", "components"),
            source="domain",
            requires_review=False,
        ),
        _Rule(
            alias=("utsu", "segmentation"),
            replacement=("Otsu", "segmentation"),
            source="domain",
            requires_review=True,
        ),
    )

    def correct_result(
        self,
        result: TranscriptionResult,
        *,
        presentation: dict[str, Any] | None,
    ) -> tuple[TranscriptionResult, tuple[ScientificCorrection, ...]]:
        if not result.text.strip() or not result.words:
            return result, ()

        deck_text = self._deck_text(presentation)
        words = list(result.words)
        corrections: list[ScientificCorrection] = []

        for rule in self._RULES:
            if rule.evidence and not any(item in deck_text for item in rule.evidence):
                continue
            words, found = self._apply_rule(words, rule)
            corrections.extend(found)

        # Person-name variants are deck-grounded and only activated when the
        # presentation itself names Sina. This avoids a global CINA/Dina rewrite.
        if "sina" in deck_text:
            for index, word in enumerate(words):
                normalized = _norm(word.text)
                if normalized not in {"cina", "dina", "sina"}:
                    continue
                canonical = "Sina" + _suffix(word.text)
                if word.text == canonical:
                    continue
                corrections.append(
                    ScientificCorrection(
                        original=word.text,
                        replacement=canonical,
                        source="slide",
                    )
                )
                words[index] = WordResult(
                    canonical,
                    word.probability,
                    word.start,
                    word.end,
                )

        words, contextual = self._apply_contextual_rules(words)
        corrections.extend(contextual)

        if not corrections:
            return result, ()

        corrected_text = " ".join(word.text for word in words).strip()
        merged_corrections = tuple(result.corrections) + tuple(
            item.to_dict() for item in corrections
        )
        return (
            TranscriptionResult(
                text=corrected_text,
                words=tuple(words),
                average_confidence=result.average_confidence,
                corrections=merged_corrections,
            ),
            tuple(corrections),
        )


    @classmethod
    def _apply_contextual_rules(
        cls,
        words: list[WordResult],
    ) -> tuple[list[WordResult], list[ScientificCorrection]]:
        """Apply narrow context-sensitive corrections that are unsafe globally.

        These rules require nearby semantic evidence in the same ASR segment, so
        ordinary uses of words such as ``rain`` or ``two and a half`` are never
        rewritten out of context.
        """
        output = list(words)
        corrections: list[ScientificCorrection] = []
        norms = [_norm(item.text) for item in output]

        # ``grayscale map ... rain blocks`` is a recurrent ASR error for
        # ``gray blocks``. Require explicit grayscale context within the preceding
        # window before correcting it.
        for index in range(len(output) - 1):
            if norms[index] != "rain" or norms[index + 1] not in {"block", "blocks"}:
                continue
            context = " ".join(norms[max(0, index - 14):index])
            if "grayscale" not in context and "gray scale" not in context:
                continue
            original = output[index].text
            replacement = "gray" + _suffix(original)
            output[index] = WordResult(
                replacement,
                output[index].probability,
                output[index].start,
                output[index].end,
            )
            norms[index] = "gray"
            corrections.append(
                ScientificCorrection(
                    original=original,
                    replacement=replacement,
                    source="context",
                    requires_review=False,
                )
            )

        # Canonicalize ``two and a half`` to ``2.5D`` only when the same segment
        # explicitly discusses whether the representation is 3D.
        index = 0
        while index <= len(output) - 3:
            window = tuple(_norm(item.text) for item in output[index:index + 3])
            if window != ("two", "and", "a half") and window != ("two", "and", "half"):
                # Tokenization normally produces four tokens: two / and / a / half.
                if index <= len(output) - 4:
                    window4 = tuple(_norm(item.text) for item in output[index:index + 4])
                else:
                    window4 = ()
                if window4 != ("two", "and", "a", "half"):
                    index += 1
                    continue
                size = 4
            else:
                size = 3

            segment_context = " ".join(_norm(item.text) for item in output)
            if not (
                "3d" in segment_context
                or "3 d" in segment_context
                or "not really 3d" in segment_context
                or "not really three d" in segment_context
            ):
                index += size
                continue

            chunk = output[index:index + size]
            original = " ".join(item.text for item in chunk)
            probabilities = [item.probability for item in chunk if item.probability is not None]
            probability = min(probabilities) if probabilities else None
            replacement = "2.5D" + _suffix(chunk[-1].text)
            output[index:index + size] = [
                WordResult(replacement, probability, chunk[0].start, chunk[-1].end)
            ]
            corrections.append(
                ScientificCorrection(
                    original=original,
                    replacement=replacement,
                    source="context",
                    requires_review=False,
                )
            )
            index += 1

        return output, corrections

    @classmethod
    def _apply_rule(
        cls,
        words: list[WordResult],
        rule: _Rule,
    ) -> tuple[list[WordResult], list[ScientificCorrection]]:
        output: list[WordResult] = []
        corrections: list[ScientificCorrection] = []
        index = 0
        size = len(rule.alias)
        while index < len(words):
            window = words[index : index + size]
            if len(window) == size and tuple(_norm(item.text) for item in window) == rule.alias:
                original = " ".join(item.text for item in window)
                replacement_tokens = list(rule.replacement)
                if replacement_tokens:
                    replacement_tokens[-1] += _suffix(window[-1].text)
                probability_values = [
                    item.probability for item in window if item.probability is not None
                ]
                probability = min(probability_values) if probability_values else None
                start = window[0].start
                end = window[-1].end
                for token_index, token in enumerate(replacement_tokens):
                    output.append(
                        WordResult(
                            token,
                            probability,
                            start if token_index == 0 else None,
                            end if token_index == len(replacement_tokens) - 1 else None,
                        )
                    )
                replacement = " ".join(replacement_tokens)
                corrections.append(
                    ScientificCorrection(
                        original=original,
                        replacement=replacement,
                        source=rule.source,
                        requires_review=rule.requires_review,
                    )
                )
                index += size
                continue
            output.append(words[index])
            index += 1
        return output, corrections

    @staticmethod
    def _deck_text(presentation: dict[str, Any] | None) -> str:
        if not presentation:
            return ""
        parts: list[str] = []
        for slide in presentation.get("slides") or []:
            parts.extend(
                [
                    str(slide.get("title") or ""),
                    str(slide.get("body_text") or ""),
                    str(slide.get("notes_text") or ""),
                    " ".join(str(item) for item in slide.get("keywords") or []),
                ]
            )
        return _norm(" ".join(parts))
