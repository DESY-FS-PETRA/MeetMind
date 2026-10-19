from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.presentation.extractor import PresentationExtractionError, extract_presentation
from app.storage.meeting_storage import MeetingStorage
from app.vocabulary.service import AdaptiveVocabularyService


_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_SCIENTIFIC_TOKEN_RE = re.compile(
    r"\b(?:[A-Z][A-Z0-9+.-]{1,}|[A-Za-z]+(?:Py|NX|XFEL|XRF|XBIC|XEOL|XRD)|"
    r"[A-Za-z]+(?:-[A-Za-z0-9]+){1,3}|[A-Za-z]+\d{1,3})\b"
)
_STOP_TOKENS = {
    "THE", "AND", "FOR", "WITH", "FROM", "THIS", "THAT", "FIG", "FIGURE",
    "SLIDE", "RESULT", "RESULTS", "SUMMARY", "INTRODUCTION", "CONCLUSION",
    "RAY", "AWARE",
}
_CURATED_PRESENTATION_PHRASES = (
    "scientific vocabulary",
    "transcript alignment",
    "active slide vocabulary",
    "slide-aware vocabulary",
    "live transcript",
    "Meeting History",
)
_NEGATIVE_EXAMPLE_RE = re.compile(
    r"\b(?:avoid|not\s+confused\s+with|incorrect(?:\s+transcription)?|"
    r"transcribed\s+as|mistaken\s+for|heard\s+as|instead\s+of|asr\s+error)\b",
    re.IGNORECASE,
)


def _normalise_keyword(value: str) -> str:
    value = value.casefold().replace("x-ray", "x ray").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+.-]+", " ", value)).strip()


def _phrase_count(text: str, phrase: str) -> int:
    if not phrase:
        return 0
    return len(re.findall(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text))


def _remove_redundant_visible_terms(terms: list[str], text: str) -> list[str]:
    normalized_text = _normalise_keyword(text)
    output: list[str] = []
    for term in terms:
        normalized = _normalise_keyword(term)
        if normalized in {"ray", "slide-aware", "slide aware", "x-"}:
            continue
        longer = [
            item
            for item in terms
            if len(_normalise_keyword(item).split()) > len(normalized.split())
            and f" {normalized} " in f" {_normalise_keyword(item)} "
        ]
        if longer:
            short_count = _phrase_count(normalized_text, normalized)
            covered_count = sum(
                _phrase_count(normalized_text, _normalise_keyword(item))
                for item in longer
            )
            if short_count and short_count <= covered_count:
                continue
        output.append(term)
    return output


class PresentationService:
    def __init__(
        self,
        *,
        storage: MeetingStorage,
        vocabulary: AdaptiveVocabularyService,
        root: str | Path | None = None,
    ) -> None:
        self.storage = storage
        self.vocabulary = vocabulary
        self.root = Path(root or os.getenv("PRESENTATION_STORAGE_DIR", "data/presentations"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = int(float(os.getenv("PRESENTATION_MAX_MB", "50")) * 1024 * 1024)
        self.max_slides = max(1, int(os.getenv("PRESENTATION_MAX_SLIDES", "300")))
        self.max_text_characters = max(10_000, int(
            os.getenv("PRESENTATION_MAX_TEXT_CHARACTERS", "500000")
        ))
        self.max_slide_terms = min(
            max(1, int(os.getenv("SLIDE_VOCABULARY_MAX_TERMS", "14"))),
            14,
        )
        self._noncanonical_aliases = {
            _normalise_keyword(alias)
            for term in self.vocabulary.terms
            for alias in term.aliases
            if _normalise_keyword(alias)
            and _normalise_keyword(alias) != _normalise_keyword(term.canonical_term)
        }
        self._noncanonical_alias_tokens = {
            token
            for alias in self._noncanonical_aliases
            for token in alias.split()
            if len(token) >= 3
        }

    async def upload(self, upload: UploadFile) -> dict:
        original_name = Path(upload.filename or "presentation").name
        extension = Path(original_name).suffix.casefold()
        if extension not in {".pptx", ".pdf"}:
            raise PresentationExtractionError("Only .pptx and .pdf files are supported")

        presentation_id = str(uuid4())
        target_dir = self.root / presentation_id
        target_dir.mkdir(parents=True, exist_ok=False)
        safe_stem = _SAFE_FILENAME_RE.sub("_", Path(original_name).stem).strip("._") or "presentation"
        target_path = target_dir / f"{safe_stem}{extension}"

        written = 0
        try:
            with target_path.open("wb") as output:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > self.max_bytes:
                        raise PresentationExtractionError(
                            f"Presentation exceeds the {self.max_bytes // (1024 * 1024)} MB limit"
                        )
                    output.write(chunk)

            extracted = extract_presentation(target_path, extension)
            if len(extracted) > self.max_slides:
                raise PresentationExtractionError(
                    f"Presentation has more than {self.max_slides} slides/pages"
                )
            extracted_characters = sum(len(item.combined_text) for item in extracted)
            if extracted_characters > self.max_text_characters:
                raise PresentationExtractionError(
                    "Extracted presentation text exceeds the configured safety limit"
                )
            slides = []
            for item in extracted:
                combined = item.combined_text
                keywords = self._extract_keywords(combined)
                slides.append(
                    {
                        "slide_number": item.slide_number,
                        "title": item.title,
                        "body_text": item.body_text,
                        "notes_text": item.notes_text,
                        "keywords": keywords,
                    }
                )

            title = next(
                (slide["title"] for slide in slides if slide["title"].strip()),
                Path(original_name).stem,
            )
            return self.storage.create_presentation(
                presentation_id=presentation_id,
                filename=original_name,
                source_type=extension.lstrip("."),
                title=title,
                storage_path=str(target_path.resolve()),
                slides=slides,
            )
        except Exception:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise
        finally:
            await upload.close()

    def _extract_keywords(self, text: str) -> list[str]:
        # Do not turn deliberately displayed ASR mistakes (for example
        # "Avoid ASTA football errors") into Whisper hotwords or summary terms.
        safe_lines = [
            line
            for line in str(text).splitlines()
            if line.strip() and not _NEGATIVE_EXAMPLE_RE.search(line)
        ]
        safe_text = "\n".join(safe_lines)

        selected = _remove_redundant_visible_terms(
            list(
                self.vocabulary.visible_terms(
                    safe_text,
                    limit=self.max_slide_terms + 8,
                )
            ),
            safe_text,
        )[: self.max_slide_terms]
        seen = {_normalise_keyword(item) for item in selected}

        normalized_safe_text = _normalise_keyword(safe_text)
        for phrase in _CURATED_PRESENTATION_PHRASES:
            normalized = _normalise_keyword(phrase)
            if (
                f" {normalized} " in f" {normalized_safe_text} "
                and normalized not in seen
                and len(selected) < self.max_slide_terms
            ):
                selected.append(phrase)
                seen.add(normalized)

        for match in _SCIENTIFIC_TOKEN_RE.finditer(safe_text):
            token = match.group(0).strip(".,;:()[]{}")
            normalized = _normalise_keyword(token)
            if (
                len(token) < 2
                or token.startswith("-")
                or token.endswith("-")
                or token.upper() in _STOP_TOKENS
                or normalized in {"ray", "slide-aware", "slide aware", "x-"}
            ):
                continue
            if normalized in self._noncanonical_aliases:
                continue
            if normalized in self._noncanonical_alias_tokens:
                continue
            if normalized in seen:
                continue
            # Do not add an acronym/token already contained in a longer
            # canonical term such as ``ASTRA Toolbox`` or ``X-ray imaging``.
            if any(
                normalized in re.findall(r"[a-z0-9+.-]+", _normalise_keyword(item))
                for item in selected
            ):
                continue
            seen.add(normalized)
            selected.append(token)
            if len(selected) >= self.max_slide_terms:
                break
        return selected[: self.max_slide_terms]
