from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from statistics import mean
from typing import Any

from app.transcription.result import TranscriptionResult, WordResult


_WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")
_EDGE_RE = re.compile(r"(^[^\w']+|[^\w']+$)")
_AMBIGUOUS_VISIBLE_TERMS = {"ray"}



_DYNAMIC_SLIDE_ALIASES: dict[str, tuple[str, ...]] = {
    "motivation": (
        "modi-for",
        "modi for",
        "motive for",
        "motive four",
    ),
    "scientific vocabulary": (
        "scientific vocab workload",
        "scientific vocab",
        "vocab workload",
    ),
    "transcript alignment": (
        "transcription alignment",
    ),
}
_DYNAMIC_SLIDE_REPLACEMENTS = {
    "motivation": "motivation for",
}
_TITLE_PREFIX_STOPWORDS = {
    "slide", "summary", "introduction", "conclusion", "overview", "agenda",
}

_DEFAULT_ALWAYS_ON_TERMS = (
    "DESY",
    "PETRA III",
    "PETRA IV",
    "European XFEL",
    "ASTRA Toolbox",
    "TomoPy",
    "PtyPy",
    "PyNX",
    "pyFAI",
    "MATLAB",
    "Maxwell cluster",
    "near-field holography",
    "far-field holography",
    "phase retrieval",
    "ptychography",
    "computed tomography",
    "synchrotron radiation",
    "X-ray optics",
)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _normalise_text(value: str) -> str:
    value = value.replace("–", "-").replace("—", "-").casefold()
    value = value.replace("x-ray", "x ray")
    value = re.sub(r"[^a-z0-9+'-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _normalise_token(value: str) -> str:
    return _normalise_text(_EDGE_RE.sub("", value))


def _token_set(value: str) -> set[str]:
    return set(_WORD_RE.findall(_normalise_text(value)))


def _contains_phrase(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    return f" {phrase} " in f" {text} "


@dataclass(frozen=True, slots=True)
class VocabularyTerm:
    canonical_term: str
    category: str
    aliases: tuple[str, ...]
    priority: str

    @property
    def search_forms(self) -> tuple[str, ...]:
        return (self.canonical_term, *self.aliases)


@dataclass(frozen=True, slots=True)
class VocabularyContext:
    hotwords: str | None
    initial_prompt: str | None
    active_terms: tuple[str, ...]
    categories: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VocabularySnapshot:
    meeting_id: str
    categories: tuple[str, ...]
    category_labels: tuple[str, ...]
    active_terms: tuple[str, ...]
    category_scores: dict[str, float]
    revision: int
    observed_characters: int
    correction_count: int
    is_final: bool
    updated_at: str
    current_slide_number: int | None = None
    current_slide_title: str | None = None
    slide_terms: tuple[str, ...] = ()
    slide_auto_match: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "meeting_id": self.meeting_id,
            "categories": list(self.categories),
            "category_labels": list(self.category_labels),
            "active_terms": list(self.active_terms),
            "active_term_count": len(self.active_terms),
            "category_scores": dict(self.category_scores),
            "revision": self.revision,
            "observed_characters": self.observed_characters,
            "correction_count": self.correction_count,
            "is_final": self.is_final,
            "updated_at": self.updated_at,
            "current_slide_number": self.current_slide_number,
            "current_slide_title": self.current_slide_title,
            "slide_terms": list(self.slide_terms),
            "slide_term_count": len(self.slide_terms),
            "slide_auto_match": self.slide_auto_match,
        }


@dataclass(slots=True)
class _MeetingVocabularyState:
    observed_text: str = ""
    categories: list[str] = field(default_factory=list)
    domain_terms: list[str] = field(default_factory=list)
    slide_terms: list[str] = field(default_factory=list)
    custom_terms: list[str] = field(default_factory=list)
    active_terms: list[str] = field(default_factory=list)
    current_slide_number: int | None = None
    current_slide_title: str | None = None
    slide_auto_match: bool | None = None
    category_scores: dict[str, float] = field(default_factory=dict)
    revision: int = 0
    correction_count: int = 0
    is_final: bool = False
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class AdaptiveVocabularyService:
    """Selects and applies a bounded scientific vocabulary automatically.

    A 1000-term master glossary stays local. Whisper only receives core terms
    plus terms from the most relevant detected categories, keeping prompts
    bounded while still biasing domain-specific names and methods.
    """

    def __init__(self, glossary_path: str | Path | None = None) -> None:
        default_path = Path(__file__).resolve().parent / "data" / "scientific_vocabulary_1000.json"
        configured = glossary_path or os.getenv("VOCABULARY_PATH") or default_path
        self.path = Path(configured)
        self.enabled = _env_bool("VOCABULARY_ENABLED", True)
        # Hotwords are a bias, not a dictionary. Large lists can overpower the
        # acoustic evidence and create prompt-driven hallucinations. Keep the
        # active list intentionally small and retrieve only the most relevant
        # terms from the 1000-term master glossary.
        # Hard safety caps also protect users upgrading from Phase 5.6 whose
        # existing .env may still contain the old aggressive values (120/240).
        self.max_hotwords = min(
            max(0, int(os.getenv("VOCABULARY_MAX_HOTWORDS", "24"))),
            24,
        )
        self.max_hotword_words = min(
            max(0, int(os.getenv("VOCABULARY_MAX_HOTWORD_WORDS", "48"))),
            48,
        )
        self.core_term_limit = min(
            max(0, int(os.getenv("VOCABULARY_CORE_TERM_LIMIT", "18"))),
            18,
        )
        self.max_categories = min(
            max(0, int(os.getenv("VOCABULARY_MAX_CATEGORIES", "2"))),
            2,
        )
        self.max_terms_per_category = min(
            max(0, int(os.getenv("VOCABULARY_MAX_TERMS_PER_CATEGORY", "8"))),
            8,
        )
        self.slide_term_limit = min(
            max(0, int(os.getenv("SLIDE_VOCABULARY_MAX_TERMS", "14"))),
            14,
        )
        self.min_topic_score = max(
            6.0,
            float(os.getenv("VOCABULARY_MIN_TOPIC_SCORE", "6.0")),
        )
        self.min_topic_evidence = max(
            2,
            int(os.getenv("VOCABULARY_MIN_TOPIC_EVIDENCE", "2")),
        )
        self.topic_warmup_characters = max(
            160,
            int(os.getenv("VOCABULARY_TOPIC_WARMUP_CHARACTERS", "160")),
        )
        self.max_observed_characters = int(
            os.getenv("VOCABULARY_MAX_OBSERVED_CHARACTERS", "4000")
        )
        self.correction_confidence = float(
            os.getenv("VOCABULARY_CORRECTION_CONFIDENCE", "0.72")
        )
        self.fuzzy_threshold = float(os.getenv("VOCABULARY_FUZZY_THRESHOLD", "0.92"))
        self.initial_prompt_prefix = os.getenv(
            "VOCABULARY_INITIAL_PROMPT",
            "English meeting transcript. Preserve scientific names exactly when they are clearly spoken.",
        ).strip()
        self.use_initial_prompt = _env_bool(
            "VOCABULARY_USE_INITIAL_PROMPT",
            False,
        )
        configured_always_on = os.getenv("VOCABULARY_ALWAYS_ON_TERMS", "").strip()
        self.always_on_terms = tuple(
            term.strip()
            for term in (
                configured_always_on.split("|")
                if configured_always_on
                else _DEFAULT_ALWAYS_ON_TERMS
            )
            if term.strip()
        )

        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.version = str(payload.get("version", "unknown"))
        self.categories: dict[str, dict[str, Any]] = dict(payload.get("categories") or {})
        self.terms = tuple(
            VocabularyTerm(
                canonical_term=str(item["canonical_term"]),
                category=str(item["category"]),
                aliases=tuple(str(alias) for alias in item.get("aliases") or []),
                priority=str(item.get("priority", "domain")),
            )
            for item in payload.get("terms") or []
        )
        self._terms_by_category: dict[str, list[VocabularyTerm]] = {
            key: [] for key in self.categories
        }
        for term in self.terms:
            self._terms_by_category.setdefault(term.category, []).append(term)

        self._core_terms = [term for term in self.terms if term.priority == "core"]
        by_name = {
            _normalise_text(term.canonical_term): term
            for term in self.terms
        }
        self._always_on_term_objects = [
            by_name[_normalise_text(name)]
            for name in self.always_on_terms
            if _normalise_text(name) in by_name
        ]
        self._states: dict[str, _MeetingVocabularyState] = {}

    def global_status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "version": self.version,
            "glossary_path": str(self.path),
            "term_count": len(self.terms),
            "alias_count": sum(len(term.aliases) for term in self.terms),
            "category_count": len(self.categories),
            "categories": [
                {
                    "id": key,
                    "label": value.get("label", key),
                    "description": value.get("description", ""),
                    "term_count": len(self._terms_by_category.get(key, [])),
                }
                for key, value in self.categories.items()
            ],
            "max_hotwords": self.max_hotwords,
            "max_hotword_words": self.max_hotword_words,
            "core_term_limit": self.core_term_limit,
            "always_on_terms": list(self.always_on_terms),
            "max_terms_per_category": self.max_terms_per_category,
            "slide_term_limit": self.slide_term_limit,
            "min_topic_score": self.min_topic_score,
            "min_topic_evidence": self.min_topic_evidence,
            "topic_warmup_characters": self.topic_warmup_characters,
            "use_initial_prompt": self.use_initial_prompt,
        }

    def start_meeting(self, meeting_id: str, custom_terms: list[str] | tuple[str, ...] | None = None) -> VocabularySnapshot:
        state = _MeetingVocabularyState()
        # Conference/talk context is a bounded bias supplied from trusted metadata
        # (title, abstract, program keywords). It is never used as transcript evidence.
        seen_custom: set[str] = set()
        for item in custom_terms or []:
            clean = re.sub(r"\s+", " ", str(item).strip())
            key = _normalise_text(clean)
            if clean and key and key not in seen_custom:
                seen_custom.add(key)
                state.custom_terms.append(clean)
            if len(state.custom_terms) >= self.max_hotwords:
                break
        state.domain_terms = self._select_active_terms("", [])
        state.active_terms = self._merge_context_terms(
            state.slide_terms,
            state.domain_terms,
            state.custom_terms,
        )
        state.revision = 1
        state.updated_at = datetime.now(timezone.utc).isoformat()
        self._states[meeting_id] = state
        return self._snapshot(meeting_id, state)

    def context_for(self, meeting_id: str) -> VocabularyContext:
        if not self.enabled:
            return VocabularyContext(None, None, (), ())
        state = self._states.get(meeting_id)
        if state is None:
            self.start_meeting(meeting_id)
            state = self._states[meeting_id]

        labels = [self.categories.get(key, {}).get("label", key) for key in state.categories]
        prompt = self.initial_prompt_prefix if self.use_initial_prompt else ""
        if prompt and labels:
            prompt += " Likely domains: " + ", ".join(labels) + "."
        hotwords = ", ".join(state.active_terms) if state.active_terms else None
        return VocabularyContext(
            hotwords=hotwords,
            initial_prompt=prompt or None,
            active_terms=tuple(state.active_terms),
            categories=tuple(state.categories),
        )

    def observe(self, meeting_id: str, text: str) -> VocabularySnapshot | None:
        if not self.enabled or not text.strip():
            return None
        state = self._states.setdefault(meeting_id, _MeetingVocabularyState())
        clean_text = re.sub(r"\s+", " ", text.strip())
        # Observe raw, sanitized chunk text only. Keep a bounded rolling topic
        # window and avoid duplicating an identical chunk suffix.
        if not state.observed_text.endswith(clean_text):
            state.observed_text = f"{state.observed_text} {clean_text}".strip()
        if len(state.observed_text) > self.max_observed_characters:
            state.observed_text = state.observed_text[-self.max_observed_characters :]

        scores, evidence = self._score_categories(state.observed_text)
        selected = [
            category
            for category, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
            if (
                len(state.observed_text) >= self.topic_warmup_characters
                and score >= self.min_topic_score
                and evidence.get(category, 0) >= self.min_topic_evidence
            )
        ][: self.max_categories]
        domain_terms = self._select_active_terms(state.observed_text, selected)
        active_terms = self._merge_context_terms(state.slide_terms, domain_terms, state.custom_terms)

        rounded_scores = {key: round(value, 3) for key, value in scores.items() if value > 0}
        changed = (
            selected != state.categories
            or active_terms != state.active_terms
            or rounded_scores != state.category_scores
        )
        state.category_scores = rounded_scores
        if not changed:
            return None

        state.categories = selected
        state.domain_terms = domain_terms
        state.active_terms = active_terms
        state.revision += 1
        state.updated_at = datetime.now(timezone.utc).isoformat()
        return self._snapshot(meeting_id, state)

    def visible_terms(self, text: str, *, limit: int = 12) -> tuple[str, ...]:
        """Return canonical glossary terms literally visible in slide text.

        Slide files contain clean written terminology, so aliases are not used
        here. This avoids expanding a visible acronym such as ``SIRT`` into an
        additional long hotword that was never present on the slide.
        """
        normalized = _normalise_text(text)
        matches: list[tuple[int, int, str]] = []
        seen: set[str] = set()
        for position, term in enumerate(self.terms):
            canonical_norm = _normalise_text(term.canonical_term)
            if (
                len(canonical_norm) < 2
                or canonical_norm in _AMBIGUOUS_VISIBLE_TERMS
                or not _contains_phrase(normalized, canonical_norm)
            ):
                continue
            if canonical_norm in seen:
                continue
            seen.add(canonical_norm)
            priority = 1 if term.priority == "core" else 0
            matches.append(
                (len(canonical_norm.split()) * 10 + priority, -position, term.canonical_term)
            )
        matches.sort(reverse=True)
        return tuple(item[2] for item in matches[: max(0, int(limit))])

    def set_slide_context(
        self,
        meeting_id: str,
        *,
        slide_number: int | None,
        slide_title: str | None,
        slide_terms: list[str] | tuple[str, ...],
        auto_match: bool | None,
    ) -> VocabularySnapshot | None:
        if not self.enabled:
            return None
        state = self._states.get(meeting_id)
        if state is None:
            self.start_meeting(meeting_id)
            state = self._states[meeting_id]

        clean_terms: list[str] = []
        seen: set[str] = set()
        clean_title = re.sub(r"\s+", " ", str(slide_title or "").strip()) or None

        # A concise slide title is direct written evidence and is often the
        # word Whisper needs most (for example "Motivation"). Keep long or
        # generic titles out of the hotword prompt. For titles with a colon,
        # also keep the short leading concept because ASR often hears that word
        # independently of the rest of the title.
        prefix_candidates: list[str] = []
        full_title_candidates: list[str] = []
        if clean_title:
            prefix = re.split(r"\s*[:|]\s*|\s+[–—]\s+", clean_title, maxsplit=1)[0].strip()
            prefix_words = prefix.split()
            if (
                prefix
                and prefix.casefold() not in _TITLE_PREFIX_STOPWORDS
                and 1 <= len(prefix_words) <= 3
                and len(prefix) <= 40
                and _normalise_text(prefix) != _normalise_text(clean_title)
            ):
                prefix_candidates.append(prefix)

            title_words = clean_title.split()
            title_norm = _normalise_text(clean_title)
            overlaps_existing = any(
                _normalise_text(term)
                and (
                    _contains_phrase(title_norm, _normalise_text(term))
                    or _contains_phrase(_normalise_text(term), title_norm)
                )
                for term in slide_terms
            )
            if (
                not overlaps_existing
                and 1 <= len(title_words) <= 6
                and len(clean_title) <= 80
                and not re.fullmatch(r"slide\s+\d+", clean_title, flags=re.IGNORECASE)
                and clean_title.casefold() not in _TITLE_PREFIX_STOPWORDS
            ):
                full_title_candidates.append(clean_title)

        # A short unique prefix such as "Motivation" is useful for correcting
        # speech and comes first. Canonical slide terms retain priority over a
        # generic full title such as "Tomographic reconstruction".
        for item in [*prefix_candidates, *slide_terms, *full_title_candidates]:
            term = re.sub(r"\s+", " ", str(item).strip())
            key = _normalise_text(term)
            if not term or not key or key in seen:
                continue
            seen.add(key)
            clean_terms.append(term)
            if len(clean_terms) >= self.slide_term_limit:
                break

        active_terms = self._merge_context_terms(clean_terms, state.domain_terms, state.custom_terms)
        changed = (
            state.current_slide_number != slide_number
            or state.current_slide_title != clean_title
            or state.slide_terms != clean_terms
            or state.slide_auto_match != auto_match
            or state.active_terms != active_terms
        )
        if not changed:
            return None

        state.current_slide_number = slide_number
        state.current_slide_title = clean_title
        state.slide_terms = clean_terms
        state.slide_auto_match = auto_match
        state.active_terms = active_terms
        state.revision += 1
        state.updated_at = datetime.now(timezone.utc).isoformat()
        return self._snapshot(meeting_id, state)

    def correct_result(
        self,
        meeting_id: str,
        result: TranscriptionResult,
    ) -> tuple[TranscriptionResult, VocabularySnapshot | None]:
        if not self.enabled or not result.words:
            return result, None
        state = self._states.get(meeting_id)
        if state is None:
            self.start_meeting(meeting_id)
            state = self._states[meeting_id]

        active = self._active_term_objects(state.active_terms)
        corrected_words, corrections = self._correct_words(list(result.words), active)
        if not corrections:
            return result, None

        probabilities = [
            word.probability for word in corrected_words if word.probability is not None
        ]
        corrected = TranscriptionResult(
            text=" ".join(word.text for word in corrected_words).strip(),
            words=tuple(corrected_words),
            average_confidence=mean(probabilities) if probabilities else result.average_confidence,
            corrections=tuple(corrections),
        )
        state.correction_count += len(corrections)
        state.revision += 1
        state.updated_at = datetime.now(timezone.utc).isoformat()
        return corrected, self._snapshot(meeting_id, state)

    def finalize(self, meeting_id: str) -> VocabularySnapshot | None:
        state = self._states.get(meeting_id)
        if state is None:
            return None
        state.is_final = True
        state.revision += 1
        state.updated_at = datetime.now(timezone.utc).isoformat()
        return self._snapshot(meeting_id, state)

    def snapshot(self, meeting_id: str) -> VocabularySnapshot | None:
        state = self._states.get(meeting_id)
        return self._snapshot(meeting_id, state) if state else None

    def forget(self, meeting_id: str) -> None:
        self._states.pop(meeting_id, None)

    def _score_categories(self, text: str) -> tuple[dict[str, float], dict[str, int]]:
        normalized = _normalise_text(text)
        text_tokens = _token_set(text)
        scores = {key: 0.0 for key in self.categories}
        evidence: dict[str, set[str]] = {key: set() for key in self.categories}

        for category, profile in self.categories.items():
            for keyword in profile.get("keywords") or []:
                keyword_norm = _normalise_text(str(keyword))
                if not keyword_norm:
                    continue
                if _contains_phrase(normalized, keyword_norm):
                    scores[category] += 3.0 + 0.25 * len(keyword_norm.split())
                    evidence[category].add(keyword_norm)
                else:
                    overlap = len(_token_set(keyword_norm) & text_tokens)
                    scores[category] += 0.2 * overlap

        # Exact glossary matches are strong topic evidence.
        for term in self.terms:
            for form in term.search_forms:
                form_norm = _normalise_text(form)
                if len(form_norm) >= 3 and _contains_phrase(normalized, form_norm):
                    scores[term.category] += 4.0 if " " in form_norm else 2.5
                    evidence[term.category].add(form_norm)
                    break
        return scores, {key: len(values) for key, values in evidence.items()}

    def _select_active_terms(self, text: str, categories: list[str]) -> list[str]:
        if not self.enabled:
            return []
        normalized = _normalise_text(text)
        text_tokens = _token_set(text)
        selected: list[str] = []
        seen: set[str] = set()
        selected_word_count = 0

        def append(term: VocabularyTerm) -> None:
            nonlocal selected_word_count
            key = _normalise_text(term.canonical_term)
            term_words = max(1, len(key.split()))
            if key in seen or len(selected) >= self.max_hotwords:
                return
            if selected and selected_word_count + term_words > self.max_hotword_words:
                return
            seen.add(key)
            selected.append(term.canonical_term)
            selected_word_count += term_words

        for term in self._always_on_term_objects[: self.core_term_limit]:
            append(term)

        candidates: list[tuple[float, VocabularyTerm]] = []
        for category in categories:
            category_candidates: list[tuple[float, VocabularyTerm]] = []
            for position, term in enumerate(self._terms_by_category.get(category, [])):
                term_tokens = _token_set(term.canonical_term)
                overlap = len(term_tokens & text_tokens)
                canonical_exact = _contains_phrase(
                    normalized,
                    _normalise_text(term.canonical_term),
                )
                alias_exact = any(
                    _contains_phrase(normalized, _normalise_text(alias))
                    for alias in term.aliases
                    if len(_normalise_text(alias)) >= 3
                )
                exact = canonical_exact or alias_exact
                score = (
                    (30.0 if canonical_exact else 20.0 if alias_exact else 0.0)
                    + overlap * 3.0
                    - position * 0.001
                )
                if term.priority == "core":
                    score += 5.0
                # Never fill the prompt with arbitrary category vocabulary.
                # A term must be a curated core item or have lexical evidence
                # in the observed transcript.
                if term.priority == "core" or exact or overlap > 0:
                    category_candidates.append((score, term))

            candidates.extend(
                sorted(category_candidates, key=lambda item: item[0], reverse=True)[
                    : self.max_terms_per_category
                ]
            )

        for _, term in sorted(candidates, key=lambda item: item[0], reverse=True):
            append(term)
        return selected

    def _merge_context_terms(
        self,
        slide_terms: list[str],
        domain_terms: list[str],
        custom_terms: list[str] | None = None,
    ) -> list[str]:
        selected: list[str] = []
        seen: set[str] = set()
        word_count = 0

        def append(name: str) -> None:
            nonlocal word_count
            clean = re.sub(r"\s+", " ", str(name).strip())
            key = _normalise_text(clean)
            words = max(1, len(key.split()))
            if not clean or not key or key in seen:
                return
            if len(selected) >= self.max_hotwords:
                return
            if selected and word_count + words > self.max_hotword_words:
                return
            seen.add(key)
            selected.append(clean)
            word_count += words

        # Talk/conference terms come from explicit program metadata and should
        # bias ASR early, before the transcript contains enough topic evidence.
        for name in (custom_terms or []):
            append(name)
        # Slide terms are direct evidence from the uploaded presentation.
        for name in slide_terms[: self.slide_term_limit]:
            append(name)
        for name in domain_terms:
            append(name)
        return selected

    def _active_term_objects(self, active_names: list[str]) -> list[VocabularyTerm]:
        wanted = {_normalise_text(name) for name in active_names}
        output = [
            term
            for term in self.terms
            if _normalise_text(term.canonical_term) in wanted
        ]
        existing = {_normalise_text(term.canonical_term) for term in output}
        for name in active_names:
            normalized = _normalise_text(name)
            aliases = _DYNAMIC_SLIDE_ALIASES.get(normalized)
            if not aliases or normalized in existing:
                continue
            output.append(
                VocabularyTerm(
                    canonical_term=_DYNAMIC_SLIDE_REPLACEMENTS.get(normalized, name),
                    category="presentation_context",
                    aliases=aliases,
                    priority="slide",
                )
            )
            existing.add(normalized)
        return output

    def _correct_words(
        self,
        words: list[WordResult],
        active_terms: list[VocabularyTerm],
    ) -> tuple[list[WordResult], list[dict[str, Any]]]:
        candidates: list[tuple[list[str], VocabularyTerm, str]] = []
        for term in active_terms:
            for alias in term.aliases:
                tokens = _normalise_text(alias).split()
                if tokens:
                    candidates.append((tokens, term, alias))
        candidates.sort(key=lambda item: len(item[0]), reverse=True)

        output: list[WordResult] = []
        corrections: list[dict[str, Any]] = []
        index = 0
        normalized_words = [_normalise_token(word.text) for word in words]
        while index < len(words):
            if self._is_protected_correction_context(words, index):
                output.append(words[index])
                index += 1
                continue

            match: tuple[int, VocabularyTerm, str] | None = None
            for alias_tokens, term, alias in candidates:
                size = len(alias_tokens)
                if normalized_words[index : index + size] == alias_tokens:
                    match = (size, term, alias)
                    break

            if match is None:
                fuzzy = self._find_fuzzy_match(words, normalized_words, index, active_terms)
                if fuzzy is not None:
                    match = fuzzy

            if match is None:
                output.append(words[index])
                index += 1
                continue

            size, term, source_phrase = match
            matched = words[index : index + size]
            if (
                term.canonical_term == "Ollama"
                and output
                and _normalise_token(output[-1].text) == "a"
            ):
                output[-1] = WordResult(
                    text="an",
                    probability=output[-1].probability,
                    start=output[-1].start,
                    end=output[-1].end,
                )
            replacement = self._replacement_words(term.canonical_term, matched)
            output.extend(replacement)
            corrections.append({
                "source": " ".join(word.text for word in matched),
                "matched_form": source_phrase,
                "replacement": term.canonical_term,
                "category": term.category,
            })
            index += size

        return output, corrections

    @staticmethod
    def _is_protected_correction_context(
        words: list[WordResult],
        index: int,
    ) -> bool:
        # Preserve examples of *incorrect* recognition. In a sentence such as
        # "ASTRA Toolbox is not confused with ASTA football", the phrase
        # after "not confused with" is evidence for evaluation and must not
        # be silently rewritten.
        start = max(0, index - 12)
        for position in range(index - 1, start - 1, -1):
            if words[position].text.rstrip().endswith((".", "?", "!")):
                start = position + 1
                break
        prefix = " ".join(
            _normalise_token(word.text)
            for word in words[start:index]
            if _normalise_token(word.text)
        )
        protected_triggers = (
            "not confused with",
            "transcribed as",
            "incorrect transcription is",
            "incorrect transcript is",
            "whisper wrote",
            "the output was",
            "recognized as",
            "recognised as",
            "heard as",
            "mistaken for",
            "instead of",
        )
        return any(prefix.endswith(trigger) or f" {trigger} " in f" {prefix} " for trigger in protected_triggers)

    def _find_fuzzy_match(
        self,
        words: list[WordResult],
        normalized_words: list[str],
        index: int,
        active_terms: list[VocabularyTerm],
    ) -> tuple[int, VocabularyTerm, str] | None:
        best: tuple[float, int, VocabularyTerm, str] | None = None
        for size in range(1, min(4, len(words) - index) + 1):
            chunk = words[index : index + size]
            probabilities = [word.probability for word in chunk if word.probability is not None]
            if not probabilities or mean(probabilities) >= self.correction_confidence:
                continue
            source = " ".join(normalized_words[index : index + size])
            if len(source) < 5:
                continue
            for term in active_terms:
                # Do not count an already canonical recognition as a
                # correction merely because it has low confidence.
                if source == _normalise_text(term.canonical_term):
                    continue
                for form in term.search_forms:
                    target = _normalise_text(form)
                    if abs(len(target.split()) - size) > 1:
                        continue
                    ratio = SequenceMatcher(None, source, target).ratio()
                    if ratio < self.fuzzy_threshold:
                        continue
                    if best is None or ratio > best[0]:
                        best = (ratio, size, term, form)
        if best is None:
            return None
        _, size, term, form = best
        return size, term, form

    @staticmethod
    def _replacement_words(
        canonical: str,
        matched: list[WordResult],
    ) -> list[WordResult]:
        tokens = canonical.split()
        leading_match = re.match(r"^([^\w+']+)", matched[0].text)
        trailing_match = re.search(r"([^\w+']+)$", matched[-1].text)
        leading = leading_match.group(1) if leading_match else ""
        trailing = trailing_match.group(1) if trailing_match else ""
        if tokens and leading:
            tokens[0] = f"{leading}{tokens[0]}"
        if tokens and trailing:
            tokens[-1] = f"{tokens[-1]}{trailing}"
        probabilities = [word.probability for word in matched if word.probability is not None]
        probability = mean(probabilities) if probabilities else None
        start = matched[0].start
        end = matched[-1].end
        duration = (
            max(0.0, end - start)
            if start is not None and end is not None
            else None
        )
        output: list[WordResult] = []
        for index, token in enumerate(tokens):
            token_start = None
            token_end = None
            if duration is not None and start is not None:
                token_start = start + duration * index / len(tokens)
                token_end = start + duration * (index + 1) / len(tokens)
            output.append(
                WordResult(
                    text=token,
                    probability=probability,
                    start=token_start,
                    end=token_end,
                )
            )
        return output

    def _snapshot(
        self,
        meeting_id: str,
        state: _MeetingVocabularyState,
    ) -> VocabularySnapshot:
        labels = tuple(
            str(self.categories.get(key, {}).get("label", key))
            for key in state.categories
        )
        return VocabularySnapshot(
            meeting_id=meeting_id,
            categories=tuple(state.categories),
            category_labels=labels,
            active_terms=tuple(state.active_terms),
            category_scores=dict(state.category_scores),
            revision=state.revision,
            observed_characters=len(state.observed_text),
            correction_count=state.correction_count,
            is_final=state.is_final,
            updated_at=state.updated_at,
            current_slide_number=state.current_slide_number,
            current_slide_title=state.current_slide_title,
            slide_terms=tuple(state.slide_terms),
            slide_auto_match=state.slide_auto_match,
        )
