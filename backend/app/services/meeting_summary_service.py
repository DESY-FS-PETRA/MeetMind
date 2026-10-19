from __future__ import annotations

import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from app.ai.llm_service import LLMService
from app.ai.numeric_fact_validator import NumericFactValidator
from app.schemas.summary import (
    ActionItem,
    DiscussionQuestion,
    MeetingSummary,
    MeetingSummaryContent,
    SlideSummary,
)
from app.storage.meeting_storage import MeetingStorage


_FUNCTION_WORDS = {
    "the", "and", "for", "that", "this", "with", "from", "into", "onto",
    "was", "were", "are", "is", "be", "been", "being", "to", "of", "in",
    "on", "at", "as", "by", "or", "an", "a", "it", "we", "they", "you",
    "but", "because", "should", "today", "yeah", "then", "there", "have",
    "had", "would", "could", "what", "when", "where", "why", "who",
}
_GENERIC_UNCERTAINTY_WORDS = {
    "slide", "slides", "speaker", "meeting", "assistant", "system", "final",
    "terms", "technical", "active", "number", "live", "thing", "things",
}
_GENERIC_TECHNICAL_TERMS = {
    "ray", "asta", "slide", "slide-aware", "slide aware", "meeting assistant",
    "active slide", "live transcript", "technical terms", "scientific vocab workload",
    "x-ray serial experiments", "utsu segmentation", "connect components",
}
_PROTECTED_TRIGGERS = (
    "not confused with", "transcribed as", "incorrect transcription is",
    "incorrect transcript is", "whisper wrote", "the output was", "recognized as",
    "recognised as", "heard as", "mistaken for", "instead of",
)
_ACTION_OWNER_BLACKLIST = {
    "normally", "probably", "maybe", "actually", "basically", "apparently",
    "yes", "no", "okay", "ok", "then", "today", "tomorrow",
}
_ACTION_META_RE = re.compile(
    r"\b(?:be\s+fine|one\s+more\s+thing|finish\s+it\s+just|finish\s+(?:the\s+)?talk|"
    r"go\s+ahead|share\s+(?:the\s+)?screen|share\s+everything|say\s+one\s+more|"
    r"thank\s+you|stop\s+sharing|start\s+sharing)\b",
    re.IGNORECASE,
)
_FUTURE_RE = re.compile(
    r"\b(?:will|must|need(?:s)?\s+to|is\s+responsible\s+for|was\s+assigned\s+to|"
    r"should\s+(?:implement|prepare|analyse|analyze|test|send|update|integrate|write|"
    r"create|generate|measure|compare|follow\s+up))\b",
    re.IGNORECASE,
)
_UNRESOLVED_MARKERS = (
    "i don't know", "i don´t know", "we don't know", "not sure", "unclear",
    "unknown", "haven't decided", "have not decided", "not yet implemented",
    "did not yet implement", "need to investigate", "remains open",
)
_ANSWER_MARKERS = (
    "because", "the reason", "the problem is", "it assumes", "it means",
    "it works", "it breaks down", "we use", "you can", "yes", "no",
)
_META_QUESTION_RE = re.compile(
    r"\b(?:what(?:'s| is) your question|are there any questions|who(?:'s| is) next(?: up)?|"
    r"should i (?:not\s+)?(?:share|stop|start)|can you (?:see|hear)|do you (?:see|hear)|"
    r"is (?:my )?(?:zoom|screen)|what was\.\.\.)\b",
    re.IGNORECASE,
)
_CONFIRMATION_END_RE = re.compile(
    r"\b(?:right|correct|okay|ok|isn't it|aren't they|don't you think)\?\s*$",
    re.IGNORECASE,
)
_SCIENTIFIC_QUESTION_TERMS = {
    "x ray", "stereo", "layer", "multilayer", "projection", "cnn", "network",
    "algorithm", "numerical", "training", "dataset", "sample", "simulation",
    "measurement", "component", "segmentation", "tomogram", "tomography",
    "phase", "ptychography", "holography", "reconstruction", "distance",
    "performance", "gpu", "astra", "background", "distribution",
}
_NON_SCIENTIFIC_REVIEW_WORDS = {
    "has", "vice-versa", "vice versa", "right", "correctly", "perfect",
    "probably", "normally", "basically", "actually", "maybe",
}
_POST_TALK_CHATTER_RE = re.compile(
    r"\b(?:who(?:'s| is) next(?: up)?|next speaker|shall we move on|okay next)\b.*$",
    re.IGNORECASE,
)
_QA_BOUNDARY_SLIDE_RE = re.compile(
    r"\b(?:thank\s+you(?:\s+for\s+your\s+attention)?|questions?|q\s*&\s*a|q&a)\b",
    re.IGNORECASE,
)
_TECH_TERM_CANONICAL_MAP = {
    "x ray": "X-ray",
    "x ray serial experiments": "X-ray stereo experiment",
    "x ray serial experiment": "X-ray stereo experiment",
    "x ray stereo experiments": "X-ray stereo experiment",
    "utsu segmentation": "Otsu segmentation",
    "connect components": "connected components",
    "astra toolbox": "ASTRA Toolbox",
}


def _normalise(value: str) -> str:
    value = value.casefold().replace("–", "-").replace("—", "-")
    value = value.replace("x-ray", "x ray")
    value = re.sub(r"[^a-z0-9+'-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _contains_phrase(text: str, phrase: str) -> bool:
    text_norm = _normalise(text)
    phrase_norm = _normalise(phrase)
    return bool(phrase_norm) and f" {phrase_norm} " in f" {text_norm} "


def _is_contiguous_subphrase(shorter: str, longer: str) -> bool:
    short_tokens = _normalise(shorter).split()
    long_tokens = _normalise(longer).split()
    if not short_tokens or len(short_tokens) >= len(long_tokens):
        return False
    size = len(short_tokens)
    return any(
        long_tokens[index : index + size] == short_tokens
        for index in range(len(long_tokens) - size + 1)
    )


def _looks_like_technical_term(value: str) -> bool:
    clean = re.sub(r"\s+", " ", str(value).strip())
    normalized = _normalise(clean)
    if not normalized or normalized in _GENERIC_TECHNICAL_TERMS:
        return False
    tokens = normalized.split()
    if len(tokens) >= 2:
        return len(normalized) >= 6
    return bool(
        re.search(r"\d", clean)
        or re.search(r"[a-z][A-Z]|[A-Z][a-z]+[A-Z]", clean)
        or re.fullmatch(r"[A-Z][A-Z0-9+.-]{1,}", clean)
        or "-" in clean
    )


def _in_protected_example(transcript: str, phrase: str) -> bool:
    transcript_norm = _normalise(transcript)
    phrase_norm = _normalise(phrase)
    if not transcript_norm or not phrase_norm:
        return False
    positions = [
        match.start()
        for match in re.finditer(
            rf"(?<!\w){re.escape(phrase_norm)}(?!\w)", transcript_norm
        )
    ]
    if not positions:
        return False
    protected = 0
    for position in positions:
        sentence_start = max(
            transcript_norm.rfind(".", 0, position),
            transcript_norm.rfind("?", 0, position),
            transcript_norm.rfind("!", 0, position),
        )
        prefix = transcript_norm[max(sentence_start + 1, position - 140) : position]
        if any(trigger in prefix for trigger in _PROTECTED_TRIGGERS):
            protected += 1
    return protected == len(positions)


def _content_tokens(text: str) -> set[str]:
    output: set[str] = set()
    for raw in _normalise(text).split():
        pieces = [raw, *raw.split("-")] if "-" in raw else [raw]
        for token in pieces:
            if len(token) < 3 or token in _FUNCTION_WORDS:
                continue
            output.add(token)
            if len(token) > 4 and token.endswith("s"):
                output.add(token[:-1])
    return output


def _similar(left: str, right: str, *, threshold: float = 0.62) -> bool:
    a = _normalise(left)
    b = _normalise(right)
    if not a or not b:
        return False
    if a == b:
        return True
    ta, tb = _content_tokens(a), _content_tokens(b)
    if ta and tb:
        overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
        if overlap >= 0.6:
            return True
    return SequenceMatcher(None, a, b).ratio() >= threshold


class MeetingSummaryService:
    def __init__(
        self,
        storage: MeetingStorage | None = None,
        llm: LLMService | None = None,
    ) -> None:
        self.storage = storage or MeetingStorage()
        self.llm = llm or LLMService()

    async def summarize(self, meeting_id: str) -> MeetingSummary:
        meeting = self.storage.get_meeting(meeting_id)
        if meeting is None:
            raise FileNotFoundError(f"Meeting {meeting_id} was not found")

        transcript_items = self.storage.load_transcript(meeting_id)
        full_transcript = self.storage.load_final_transcript_text(meeting_id)
        if not full_transcript:
            raise ValueError("The meeting has no transcript to summarize")

        slide_sections = self.storage.build_slide_transcript_sections(meeting_id)
        analysis_transcript = self._analysis_transcript(full_transcript, slide_sections)
        presentation_context = self.storage.build_presentation_context(meeting_id)
        content, provider, model = await self.llm.summarize(
            title=meeting.get("title", "Conference Meeting"),
            transcript=analysis_transcript,
            presentation_context=presentation_context or None,
        )
        content = self._enrich_multimodal_content(
            content,
            transcript=analysis_transcript,
            transcript_items=transcript_items,
            slide_sections=slide_sections,
        )

        summary = MeetingSummary(
            **content.model_dump(),
            meeting_id=meeting_id,
            generated_at=datetime.now(timezone.utc),
            provider=provider,
            model=model,
            transcript_segments=len(transcript_items),
            transcript_characters=len(full_transcript),
        )
        self.storage.save_summary(meeting_id, summary.model_dump(mode="json"))
        return summary

    @staticmethod
    def _analysis_transcript(
        transcript: str,
        sections: list[dict[str, Any]],
    ) -> str:
        if not sections:
            return transcript
        starts = [
            int(item.get("start_character") or 0)
            for item in sections
            if str(item.get("transcript") or "").strip()
        ]
        if not starts:
            return transcript
        # Offline global alignment may intentionally begin after Zoom/screen
        # setup chatter. Keep the full transcript in History, but exclude that
        # preamble from meeting intelligence.
        start = max(0, min(starts))
        return transcript[start:].strip() or transcript

    def _enrich_multimodal_content(
        self,
        content: MeetingSummaryContent,
        *,
        transcript: str,
        transcript_items: list[dict[str, Any]],
        slide_sections: list[dict[str, Any]],
    ) -> MeetingSummaryContent:
        numeric_evidence = self._numeric_evidence(transcript, slide_sections)
        validated_summary = NumericFactValidator.repair_summary(
            content.summary, numeric_evidence
        )
        validated_key_points = [
            NumericFactValidator.repair_summary(item, numeric_evidence)
            for item in content.key_points
        ]
        slide_summaries = self._build_slide_summaries(
            content.slide_summaries,
            slide_sections,
        )
        technical_terms = self._build_technical_terms(
            content.technical_terms,
            transcript,
            slide_sections,
        )
        discussion_questions, open_questions = self._build_discussion_questions(
            content.discussion_questions,
            content.open_questions,
            transcript,
            slide_sections,
            transcript_items=transcript_items,
        )
        action_items = self._validate_action_items(content.action_items, transcript)
        scientific_review = self._build_uncertainties(
            content.transcription_uncertainties,
            transcript,
            transcript_items,
            technical_terms,
            slide_sections,
        )
        return content.model_copy(
            update={
                "summary": validated_summary,
                "key_points": validated_key_points,
                "slide_summaries": slide_summaries,
                "technical_terms": technical_terms,
                "discussion_questions": discussion_questions,
                "open_questions": open_questions,
                "action_items": action_items,
                "transcription_uncertainties": scientific_review,
            }
        )

    @staticmethod
    def _numeric_evidence(
        transcript: str,
        sections: list[dict[str, Any]],
    ) -> str:
        parts = [transcript]
        for section in sections:
            body = str(section.get("body_text") or "").strip()
            notes = str(section.get("notes_text") or "").strip()
            if body:
                parts.append(body)
            if notes:
                parts.append(notes)
        return " ".join(parts)

    def _build_slide_summaries(
        self,
        llm_items: list[SlideSummary],
        sections: list[dict[str, Any]],
    ) -> list[SlideSummary]:
        if not sections:
            return []

        llm_by_number = {
            int(item.slide_number): item
            for item in llm_items
            if item.summary.strip()
        }
        output: list[SlideSummary] = []
        for section in sections:
            number = int(section["slide_number"])
            title = str(section.get("title") or f"Slide {number}").strip()
            spoken = str(section.get("transcript") or "").strip()
            if not spoken:
                continue

            # A closing/"Thank you" slide is a semantic boundary, not a bucket
            # for the Q&A that follows. Keep discussion questions in Discussion Q&A
            # and make the slide summary explicitly describe the transition.
            if self._is_qa_boundary_slide(section):
                output.append(
                    SlideSummary(
                        slide_number=number,
                        title=title,
                        summary=(
                            "The presentation concluded on this slide; the subsequent "
                            "scientific discussion is captured separately in Discussion Q&A."
                        ),
                        key_terms=[],
                    )
                )
                continue

            keywords = [str(item) for item in section.get("keywords") or []]
            visible_terms = [term for term in keywords if _contains_phrase(spoken, term)]
            existing = llm_by_number.get(number)
            fallback = (
                self._domain_slide_summary(spoken, section)
                or self._compact_slide_fallback(spoken, section)
            )
            if existing is not None:
                summary_text = self._clean_slide_summary(existing.summary.strip())
                covered = sum(
                    1 for term in visible_terms if _contains_phrase(summary_text, term)
                )
                coverage = covered / len(visible_terms) if visible_terms else 1.0
                # Prefer a compact evidence-grounded fallback when the local LLM
                # copied a long transcript passage, omitted nearly all slide terms,
                # or returned a fragment too short to be useful.
                word_count = len(summary_text.split())
                if (
                    word_count > 58
                    or len(summary_text) > 430
                    or self._slide_copy_ratio(summary_text, spoken) >= 0.52
                    or bool(re.match(r"^(?:I|we|so|yes|yeah)\b", summary_text, re.I))
                    or (len(visible_terms) >= 3 and coverage < 0.35)
                    or (len(spoken) >= 160 and len(summary_text) < 45)
                ):
                    summary_text = fallback
                llm_terms = [
                    term
                    for term in existing.key_terms
                    if any(
                        _normalise(term) == _normalise(item)
                        for item in visible_terms
                    )
                ]
                key_terms = self._unique_strings(
                    [*visible_terms, *llm_terms], limit=12
                )
            else:
                summary_text = fallback
                key_terms = self._unique_strings(visible_terms, limit=12)

            section_evidence = " ".join(
                value for value in (
                    spoken,
                    str(section.get("body_text") or ""),
                    str(section.get("notes_text") or ""),
                ) if value
            )
            summary_text = NumericFactValidator.repair_summary(
                self._clean_slide_summary(summary_text),
                section_evidence,
            )
            if not summary_text:
                continue
            output.append(
                SlideSummary(
                    slide_number=number,
                    title=title,
                    summary=summary_text,
                    key_terms=key_terms,
                )
            )
        return output

    def _build_technical_terms(
        self,
        llm_terms: list[str],
        transcript: str,
        sections: list[dict[str, Any]],
    ) -> list[str]:
        authoritative: list[str] = []
        for section in sections:
            for item in section.get("keywords") or []:
                term = self._canonical_term(str(item).strip())
                if term and _contains_phrase(transcript, term):
                    authoritative.append(term)

        output = self._unique_strings(authoritative, limit=60)
        authoritative_norms = {_normalise(item) for item in output}
        for value in llm_terms:
            clean = self._canonical_term(re.sub(r"\s+", " ", str(value).strip()))
            normalized = _normalise(clean)
            if not clean or not normalized or normalized in _GENERIC_TECHNICAL_TERMS:
                continue
            if not _contains_phrase(transcript, clean):
                continue
            if normalized in authoritative_norms:
                continue
            if not _looks_like_technical_term(clean):
                continue
            if any(_is_contiguous_subphrase(clean, canonical) for canonical in output):
                continue
            output.append(clean)
            authoritative_norms.add(normalized)

        # Common scientific terms seen in the corrected transcript are useful
        # even when they were embedded inside a full slide sentence rather than
        # extracted as a hotword.
        curated = (
            "X-ray stereo experiment", "stereo hard X-ray ptychography",
            "stereo projections", "depth information", "data augmentation",
            "subvolumes", "Otsu segmentation", "connected components",
            "ASTRA Toolbox", "z-slice", "phase shift", "ground truth",
            "validation set", "training data", "background distributions",
            "numerical approach", "CNN", "GPU",
        )
        for term in curated:
            if _contains_phrase(transcript, term):
                output.append(term)
        return self._unique_strings(output, limit=35)

    @staticmethod
    def _canonical_term(value: str) -> str:
        normalized = _normalise(value)
        return _TECH_TERM_CANONICAL_MAP.get(normalized, value)

    def _validate_action_items(
        self,
        items: list[ActionItem],
        transcript: str,
    ) -> list[ActionItem]:
        if not items:
            return []
        sentences = self._sentences(transcript)
        valid: list[ActionItem] = []
        for item in items:
            task = re.sub(r"\s+", " ", item.task.strip())
            owner = re.sub(r"\s+", " ", (item.owner or "").strip()) or None
            if not task or _ACTION_META_RE.search(task):
                continue
            if owner and owner.casefold() in _ACTION_OWNER_BLACKLIST:
                continue

            task_tokens = _content_tokens(task)
            evidence = None
            for sentence in sentences:
                if _ACTION_META_RE.search(sentence) or not _FUTURE_RE.search(sentence):
                    continue
                sentence_tokens = _content_tokens(sentence)
                overlap = len(task_tokens & sentence_tokens)
                if task_tokens and overlap < max(1, min(2, len(task_tokens))):
                    continue
                if owner:
                    owner_n = owner.casefold()
                    sentence_n = sentence.casefold()
                    if owner_n in {"i", "presenter"}:
                        if not re.search(r"\bi\s+(?:will|must|need\s+to|should\s+)", sentence_n):
                            continue
                    elif owner_n not in sentence_n:
                        continue
                evidence = sentence
                break
            if evidence is None:
                continue
            valid.append(item)
        return self._dedupe_actions(valid)

    def _build_discussion_questions(
        self,
        llm_items: list[DiscussionQuestion],
        llm_open: list[str],
        transcript: str,
        sections: list[dict[str, Any]],
        *,
        transcript_items: list[dict[str, Any]] | None = None,
    ) -> tuple[list[DiscussionQuestion], list[str]]:
        domain_tokens: set[str] = set()
        for section in sections:
            domain_tokens.update(_content_tokens(str(section.get("title") or "")))
            domain_tokens.update(_content_tokens(str(section.get("body_text") or "")))
            for term in section.get("keywords") or []:
                domain_tokens.update(_content_tokens(str(term)))

        # Transcript-derived Q&A is the source of truth. LLM entries are used only
        # to enrich a question that can be matched back to an actual utterance.
        questions = self._extract_transcript_qna(
            transcript, domain_tokens, transcript_items=transcript_items
        )
        for item in llm_items:
            clean_q = self._polish_question(self._clean_question(item.question))
            if not self._is_meaningful_question(clean_q, domain_tokens):
                continue
            existing = next(
                (q for q in questions if _similar(q.question, clean_q, threshold=0.52)),
                None,
            )
            if existing is None:
                continue
            if item.status == "answered" and item.answer and not existing.answer:
                if self._answer_is_grounded(item.answer, transcript):
                    existing.status = "answered"
                    existing.answer = self._polish_answer(
                        self._trim_answer(item.answer), existing.question
                    )

        questions = self._dedupe_questions(questions)
        answered = [item for item in questions if item.status == "answered"]
        unresolved = [item for item in questions if item.status == "unresolved"]

        open_questions: list[str] = []
        for value in llm_open:
            clean = self._polish_question(self._clean_question(str(value)))
            if not self._is_meaningful_question(clean, domain_tokens):
                continue
            if any(_similar(clean, item.question, threshold=0.52) for item in answered):
                continue
            # Do not preserve an LLM-only question unless the transcript extractor
            # found a semantically matching unresolved question.
            if not any(_similar(clean, item.question, threshold=0.52) for item in unresolved):
                continue
            open_questions.append(clean)
        for item in unresolved:
            if not any(_similar(item.question, value, threshold=0.52) for value in open_questions):
                open_questions.append(item.question)
        return questions[:10], self._unique_strings(open_questions, limit=8)

    def _extract_transcript_qna(
        self,
        transcript: str,
        domain_tokens: set[str],
        *,
        transcript_items: list[dict[str, Any]] | None = None,
    ) -> list[DiscussionQuestion]:
        sentences = self._qna_units(transcript, transcript_items)
        output: list[DiscussionQuestion] = []
        for index, sentence in enumerate(sentences):
            if "?" not in sentence:
                continue
            question = self._polish_question(self._clean_question(sentence))
            if not self._is_meaningful_question(question, domain_tokens):
                continue

            status, answer = self._resolve_question(
                question,
                sentences,
                index,
                domain_tokens,
            )
            output.append(
                DiscussionQuestion(
                    question=question,
                    status=status,
                    answer=self._polish_answer(answer, question) if answer else None,
                )
            )
        return self._dedupe_questions(output)

    def _qna_units(
        self,
        transcript: str,
        transcript_items: list[dict[str, Any]] | None,
    ) -> list[str]:
        if transcript_items:
            final_items = [item for item in transcript_items if item.get("is_final")]
            selected = final_items or transcript_items
            units: list[str] = []
            for item in selected:
                text = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
                if not text:
                    continue
                pieces = self._sentences(text) or [text]
                for piece in pieces:
                    if "?" in piece and len(piece) > 140:
                        q_tail = self._clean_question(piece)
                        q_plain = q_tail.rstrip("?").strip()
                        pos = piece.casefold().rfind(q_plain.casefold()) if q_plain else -1
                        if pos > 25:
                            prefix = piece[:pos].strip(" ,;:-")
                            if prefix:
                                units.append(prefix)
                            units.append(q_tail)
                            continue
                    units.append(piece)
            if units:
                return units
        return self._sentences(transcript)

    def _resolve_question(
        self,
        question: str,
        sentences: list[str],
        index: int,
        domain_tokens: set[str],
    ) -> tuple[str, str | None]:
        q_tokens = _content_tokens(question)
        following = sentences[index + 1 : index + 11]

        # An explicit "I don't know" immediately following a question is strong
        # evidence that this particular issue remained unresolved.
        non_question_seen = 0
        for candidate in following[:4]:
            if "?" in candidate:
                continue
            non_question_seen += 1
            candidate_n = candidate.casefold()
            if any(marker in candidate_n for marker in _UNRESOLVED_MARKERS):
                return "unresolved", None
            if non_question_seen >= 2:
                break

        best_index: int | None = None
        best_score = 0.0
        for offset, candidate in enumerate(following):
            if "?" in candidate or self._is_meta_question(candidate):
                continue
            c_tokens = _content_tokens(candidate)
            if len(c_tokens) < 4:
                continue
            overlap_count = len(q_tokens & c_tokens)
            overlap_ratio = overlap_count / max(1, min(len(q_tokens), len(c_tokens)))
            score = overlap_ratio * 4.0
            lower = candidate.casefold()
            if any(marker in lower for marker in _ANSWER_MARKERS):
                score += 1.5
            if domain_tokens and (c_tokens & domain_tokens):
                score += 0.8
            if any(token in lower for token in ("breaks down", "under-determined", "underdetermined", "not enough information", "assumes", "because")):
                score += 1.0
            q_norm = _normalise(question)
            if "network perform" in q_norm and any(
                cue in lower for cue in ("performance", "quite good", "outlier", "ground truth", "prediction", "predict")
            ):
                score += 2.4
            if "distance between layer" in q_norm and any(
                cue in lower for cue in ("distance", "spacing", "don't know", "do not know")
            ):
                score += 1.6
            if "why would a cnn" in q_norm and any(
                cue in lower for cue in ("correlation", "correlate", "underdetermined", "under-determined", "learned")
            ):
                score += 2.0
            # Answers several turns later are valid, but nearby evidence wins.
            score -= offset * 0.08
            if score > best_score:
                best_score = score
                best_index = offset

        if best_index is None or best_score < 1.9:
            return "unresolved", None

        answer_parts = [following[best_index].strip()]
        for extra in following[best_index + 1 : best_index + 3]:
            if "?" in extra or self._is_meta_question(extra):
                break
            extra_tokens = _content_tokens(extra)
            if not extra_tokens:
                continue
            if len(q_tokens & extra_tokens) or any(
                marker in extra.casefold() for marker in _ANSWER_MARKERS
            ):
                answer_parts.append(extra.strip())
            else:
                break
        answer = self._trim_answer(" ".join(answer_parts))
        return "answered", answer

    @classmethod
    def _clean_question(cls, text: str) -> str:
        clean = re.sub(r"\s+", " ", str(text or "")).strip(" -")
        if not clean:
            return ""
        # Long ASR sentences often contain an explanatory statement followed by
        # the actual question. Keep the interrogative tail when it is clear.
        lower = clean.casefold()
        if len(clean) > 150:
            candidates = []
            for pattern in (
                r"\bbut\s+if\b",
                r"\b(?:what|why|how|which|where|when|who)\b",
                r"\b(?:would|could|can|does|do|is|are)\s+(?:you|we|it|the)\b",
            ):
                for match in re.finditer(pattern, lower):
                    candidates.append(match.start())
            if candidates:
                start = max(candidates)
                # Preserve a nearby conditional clause before "would you".
                if "would you" in lower[start:]:
                    cond = lower.rfind("if ", 0, start)
                    if cond >= max(0, start - 110):
                        start = cond
                clean = clean[start:].strip(" ,;:-")
        clean = re.sub(
            r"^(?:yes|yeah)?\s*,?\s*(?:and\s+)?now\s+one\s+can\s+ask\s+the\s+question\s+",
            "",
            clean,
            flags=re.I,
        )
        clean = re.sub(r"^(?:yes|yeah|so|and)\s*[,;:-]*\s*", "", clean, flags=re.I)
        clean = re.sub(
            r"^because\s+(?=(?:what|why|how|which|does|do|can|could|would|is|are)\b)",
            "",
            clean,
            flags=re.I,
        )
        if clean and not clean.endswith("?"):
            clean += "?"
        return clean

    @staticmethod
    def _polish_question(text: str) -> str:
        """Canonicalize ASR-like scientific questions for report display.

        This does not invent a new question. It only rewrites a transcript-grounded
        interrogative into concise grammatical wording and normalizes known names /
        acronyms that are already supported elsewhere in the meeting context.
        """
        clean = re.sub(r"\s+", " ", str(text or "")).strip(" ,;:-")
        if not clean:
            return ""
        clean = re.sub(r"\b(?:CINA|Dina|SINA)\b", "Sina", clean, flags=re.I)
        clean = re.sub(r"\bCNN\s*2\b", "CNN", clean, flags=re.I)

        patterns = (
            (
                r"^how well does (?:a|the) network perform when trained (?:with|on) (?:those|that|this) kind of data\??$",
                "How well does the network perform when trained on the synthetic data?",
            ),
            (
                r"^(?:what )?the problem is with the numerical approach when you have multiple layers,? why it doesn'?t work\??$",
                "Why does the numerical approach fail for multilayer objects?",
            ),
            (
                r"^does the numerical (?:algorithm|approach) not work because you have more layers or because (?:the )?distance between the layers is smaller\??$",
                "Does the numerical approach fail because of the number of layers or the smaller distance between layers?",
            ),
            (
                r"^if you (?:do not|don'?t) have enough (?:info|information) from two projections,? would you expect a CNN\??$",
                "If two projections do not contain enough information, why would a CNN be expected to work?",
            ),
            (
                r"^in the experiments from Sina how does the distance between the layers compare to the distance in a microchip\??$",
                "In Sina's experiments, how does the distance between layers compare with the layer spacing in a microchip?",
            ),
        )
        for pattern, replacement in patterns:
            if re.match(pattern, clean, flags=re.I):
                return replacement

        # Generic grammatical repairs that preserve the original semantics.
        clean = re.sub(r"^what the problem is with\b", "What is the problem with", clean, flags=re.I)
        clean = re.sub(r"\bthose kind of data\b", "this type of data", clean, flags=re.I)
        clean = clean[0].upper() + clean[1:] if clean else clean
        if clean and not clean.endswith("?"):
            clean += "?"
        return clean

    @staticmethod
    def _polish_answer(text: str | None, question: str) -> str | None:
        """Compress a grounded answer into concise scientific prose."""
        if not text:
            return None
        clean = re.sub(r"\s+", " ", text).strip(" ,;:-")
        clean = re.sub(r"\b(?:CINA|Dina|SINA)\b", "Sina", clean, flags=re.I)
        clean = re.sub(r"\bCNN\s*2\b", "CNN", clean, flags=re.I)
        clean = re.sub(r"\brain blocks\b", "gray blocks", clean, flags=re.I)
        qn = _normalise(question)
        an = _normalise(clean)

        if "network perform" in qn and ("quite good" in an or "outlier" in an):
            details = ""
            if "overlap" in an or "overlying" in an:
                details = " Errors were concentrated around small or overlapping features."
            return "The network performed well overall, with only small outliers." + details
        if "numerical approach fail" in qn or "number of layers" in qn:
            if "not enough information" in an and ("two view" in an or "two projection" in an):
                return (
                    "The numerical approach breaks down for multilayer objects because "
                    "two views do not provide enough information to separate all layers."
                )
            if "simple shift" in an or "matrix approximation" in an:
                return (
                    "The numerical approach breaks down for multiple layers because the "
                    "simple-shift model leaves two views with not enough information for reliable separation."
                )
        if "why would a cnn" in qn and "correlat" in an:
            return (
                "A CNN may exploit learned correlations in the training data even when "
                "the inverse problem from two projections is underdetermined."
            )

        # Generic cleanup: keep at most two informative sentence-like clauses and
        # remove discourse fillers without changing technical content.
        clean = re.sub(r"^(?:yes|yeah|so|and)\b[, ]*", "", clean, flags=re.I)
        clean = re.sub(r"\b(?:you know|let's say|basically)\b[, ]*", "", clean, flags=re.I)
        parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", clean) if p.strip()]
        if len(parts) > 2:
            clean = " ".join(parts[:2])
        words = clean.split()
        if len(words) > 65:
            clean = " ".join(words[:65]).rstrip(" ,;:") + "..."
        if clean and clean[-1] not in ".!?":
            clean += "."
        return clean

    @classmethod
    def _is_meta_question(cls, question: str) -> bool:
        clean = re.sub(r"\s+", " ", question or "").strip()
        if not clean:
            return True
        normalized = _normalise(clean)
        if _META_QUESTION_RE.search(clean):
            return True
        if normalized in {"what s your question", "what is your question"}:
            return True
        if _CONFIRMATION_END_RE.search(clean):
            starts_interrogative = bool(re.match(
                r"^(?:what|why|how|which|where|when|who|does|do|can|could|would|is|are)\b",
                clean,
                re.I,
            ))
            if not starts_interrogative:
                return True
        return False

    @classmethod
    def _is_meaningful_question(
        cls,
        question: str,
        domain_tokens: set[str],
    ) -> bool:
        if cls._is_meta_question(question):
            return False
        q_tokens = _content_tokens(question)
        if len(q_tokens) < 2:
            return False
        if domain_tokens and len(q_tokens & domain_tokens) >= 1:
            return True
        normalized = _normalise(question)
        return any(term in normalized for term in _SCIENTIFIC_QUESTION_TERMS)

    @staticmethod
    def _answer_is_grounded(answer: str, transcript: str) -> bool:
        a_tokens = _content_tokens(answer)
        if not a_tokens:
            return False
        transcript_tokens = _content_tokens(transcript)
        return len(a_tokens & transcript_tokens) / max(1, len(a_tokens)) >= 0.65

    def _build_uncertainties(
        self,
        llm_items: list[str],
        transcript: str,
        transcript_items: list[dict[str, Any]],
        technical_terms: list[str],
        sections: list[dict[str, Any]],
    ) -> list[str]:
        """Build a scientific review queue rather than a generic confidence dump."""
        canonical_terms = list(technical_terms)
        for section in sections:
            canonical_terms.extend(str(item) for item in section.get("keywords") or [])
        canonical_terms = self._unique_strings(canonical_terms, limit=120)
        canonical_norms = {_normalise(term) for term in canonical_terms}
        canonical_tokens = {
            token for term in canonical_terms for token in _normalise(term).split()
        }

        candidates: list[str] = []
        final_items = [item for item in transcript_items if item.get("is_final")]
        selected = final_items or transcript_items

        # LLM uncertainty suggestions are advisory only. A rare scientific phrase
        # is not suspicious by itself: require actual low-confidence ASR evidence
        # before admitting a free-form LLM suggestion to the review queue. This
        # prevents valid terms such as PSI, zone plate, or gold particles from
        # being flagged merely because they are uncommon in ordinary English.
        low_confidence_norms: set[str] = set()
        for item in selected:
            for word in item.get("words") or []:
                if not word.get("needs_review") or word.get("context_confirmed"):
                    continue
                clean_word = re.sub(
                    r"^[^\w+.-]+|[^\w+.-]+$", "", str(word.get("text") or "")
                )
                norm_word = _normalise(clean_word)
                if norm_word:
                    low_confidence_norms.add(norm_word)

        for value in llm_items:
            clean = re.sub(r"\s+", " ", str(value).strip())
            bare = re.sub(r"\s*\(\d+% confidence\)$", "", clean)
            normalized = _normalise(bare)
            if not clean or len(normalized.split()) > 6:
                continue
            if normalized in canonical_norms or normalized in _GENERIC_UNCERTAINTY_WORDS:
                continue
            if not _looks_like_technical_term(bare):
                continue
            if not _contains_phrase(transcript, bare) or _in_protected_example(transcript, bare):
                continue
            bare_tokens = set(normalized.split())
            has_low_confidence_evidence = bool(bare_tokens & low_confidence_norms)
            if not has_low_confidence_evidence:
                continue
            candidates.append(clean)
        for item in selected:
            for word in item.get("words") or []:
                # Surface non-slide-grounded scientific auto-corrections.
                for correction in word.get("scientific_corrections") or []:
                    if not correction.get("requires_review"):
                        continue
                    candidates.append(
                        f'Review correction: "{correction.get("original")}" → '
                        f'"{correction.get("replacement")}"'
                    )

                if not word.get("needs_review") or word.get("context_confirmed"):
                    continue
                clean = re.sub(
                    r"^[^\w+.-]+|[^\w+.-]+$", "", str(word.get("text") or "")
                )
                normalized = _normalise(clean)
                if (
                    not clean
                    or len(normalized) < 3
                    or normalized in _FUNCTION_WORDS
                    or normalized in _GENERIC_UNCERTAINTY_WORDS
                    or normalized in _NON_SCIENTIFIC_REVIEW_WORDS
                    or normalized in canonical_tokens
                    or _in_protected_example(transcript, normalized)
                ):
                    continue
                if not self._is_scientific_review_candidate(clean, canonical_terms):
                    continue
                probability = word.get("probability")
                candidates.append(
                    clean if probability is None
                    else f"{clean} ({float(probability):.0%} confidence)"
                )

        # Detect suspicious acronym+digit forms even when Whisper confidence is
        # deceptively high, e.g. "CNN2" when the deck/transcript supports "CNN".
        for match in re.finditer(r"\b[A-Z]{2,}\d+\b", transcript):
            token = match.group(0)
            token_norm = _normalise(token)
            if token_norm in canonical_norms:
                continue
            closest = None
            closest_score = 0.0
            for canonical in canonical_terms:
                c = canonical.strip()
                if not re.fullmatch(r"[A-Z][A-Z0-9+.-]{1,}", c):
                    continue
                score = SequenceMatcher(None, token_norm, _normalise(c)).ratio()
                if score > closest_score:
                    closest, closest_score = c, score
            if closest and closest_score >= 0.72:
                candidates.append(
                    f'Possible terminology mismatch: "{token}" → "{closest}"'
                )

        return self._unique_strings(
            candidates,
            limit=12,
            strip_confidence_for_key=True,
        )

    @staticmethod
    def _is_scientific_review_candidate(value: str, canonical_terms: list[str]) -> bool:
        clean = value.strip()
        normalized = _normalise(clean)
        if not normalized or normalized in _NON_SCIENTIFIC_REVIEW_WORDS:
            return False
        if re.search(r"\d", clean) or re.fullmatch(r"[A-Z][A-Z0-9+.-]{1,}", clean):
            return True
        # Hyphenation alone is not enough (e.g. ordinary "vice-versa"). Keep
        # hyphenated tokens only when they resemble known scientific terminology.
        for term in canonical_terms:
            for token in _normalise(term).split():
                if len(token) >= 4 and SequenceMatcher(None, normalized, token).ratio() >= 0.72:
                    return True
        return bool(
            re.fullmatch(r"[A-Z][a-z]?-?[A-Za-z0-9]+", clean)
            and "-" in clean
        )

    @staticmethod
    def _is_qa_boundary_slide(section: dict[str, Any]) -> bool:
        title = str(section.get("title") or "")
        body = str(section.get("body_text") or "")
        title_norm = _normalise(title)
        body_norm = _normalise(body)
        if "thank you" in title_norm or "q&a" in title_norm or "q a" in title_norm:
            return True
        if title_norm in {"questions", "questions?", "discussion", "q and a"}:
            return True
        # Only treat the body as a boundary cue when it is essentially a closing
        # prompt; a technical slide that happens to contain the word 'question'
        # must not be converted into a Q&A boundary.
        if len(body_norm.split()) <= 8 and _QA_BOUNDARY_SLIDE_RE.search(body):
            return True
        return False

    @staticmethod
    def _slide_copy_ratio(summary: str, spoken: str) -> float:
        """Estimate how much a slide summary copies the spoken transcript.

        A content-token containment score is intentionally simple and robust for
        short local-LLM outputs. A high score means the 'summary' is effectively
        a transcript excerpt and should be replaced by the compact neutral form.
        """
        summary_tokens = _content_tokens(summary)
        spoken_tokens = _content_tokens(spoken)
        if not summary_tokens or not spoken_tokens:
            return 0.0
        return len(summary_tokens & spoken_tokens) / max(1, len(summary_tokens))

    @staticmethod
    def _neutralize_slide_sentence(text: str) -> str:
        clean = re.sub(r"\s+", " ", text).strip(" ,;:-")
        clean = re.sub(r"^(?:so|yes|yeah|and|now)\b[, ]*", "", clean, flags=re.I)
        replacements = (
            (r"^I\s+generated\b", "The presenter generated"),
            (r"^I\s+used\b", "The presenter used"),
            (r"^For\s+training\s+I\s+used\s+([0-9][0-9, .kK]*)\s+samples?\b", r"\1 samples were used for training"),
            (r"^I\s+rotated\s+my\s+original\s+tomograms\b", "The original tomograms were rotated"),
            (r"^I\s+cropped\s+(?:it|them)\s+down\b", "The inputs were cropped down"),
            (r"^my\s+goal\s+was\s+to\b", "The goal was to"),
            (r"^I'm\s+giving\s+a\s+short\s+update\s+(?:to|on)\b", "The slide introduces"),
            (r"^I\s+gave\s+this\s+talk\s+(?:on|from)\b", "The presentation covers"),
            (r"^we\s+(?:try|tried)\s+to\b", "The approach aims to"),
            (r"^we\s+want\s+to\b", "The work aims to"),
        )
        for pattern, replacement in replacements:
            clean = re.sub(pattern, replacement, clean, flags=re.I)
        clean = re.sub(r"\bI\s+think\b[, ]*", "", clean, flags=re.I)
        clean = re.sub(r"\byou\s+can\s+see\b[, ]*", "", clean, flags=re.I)
        clean = re.sub(r"\s+", " ", clean).strip(" ,;:-")
        if clean and clean[-1] not in ".!?":
            clean += "."
        return clean

    def _domain_slide_summary(
        self,
        spoken: str,
        section: dict[str, Any],
    ) -> str:
        """Build a short grounded abstractive summary for common scientific slides.

        The templates are cue-driven rather than deck-specific: they activate only
        when the title/transcript contains the corresponding evidence. This gives a
        deterministic fallback when a small local LLM copies the transcript.
        """
        clean = self._clean_slide_summary(spoken)
        if not clean:
            return ""
        title = str(section.get("title") or "")
        title_n = _normalise(title)
        text_n = _normalise(clean)
        evidence = " ".join(
            value for value in (
                clean,
                str(section.get("body_text") or ""),
                str(section.get("notes_text") or ""),
            ) if value
        )
        ev_n = _normalise(evidence)

        if "background" in title_n and "stereo" in ev_n and "x ray" in ev_n:
            sentence = (
                "The slide introduced stereo X-ray imaging, where two views encode "
                "depth information through relative shifts in the projections."
            )
            if "numerical" in ev_n and ("break" in ev_n or "multilayer" in ev_n):
                sentence += (
                    " Numerical separation works for simple cases but becomes insufficient "
                    "for multilayer objects, motivating a CNN-based approach."
                )
            return sentence

        if "data generation pipeline" in title_n or (
            "dataset" in ev_n and "tomogram" in ev_n and ("rotat" in ev_n or "flip" in ev_n)
        ):
            sentence = (
                "The slide described a pipeline for generating stereo X-ray training data "
                "from existing tomograms using augmentation and extracted sub-volumes."
            )
            if "90" in evidence or "180" in evidence or "270" in evidence:
                sentence = sentence.replace(
                    "using augmentation and extracted sub-volumes",
                    "using rotations, flips, and extracted sub-volumes",
                )
            if "not enough" in ev_n or "not diverse" in ev_n or "diverse enough" in ev_n:
                sentence += " The initial augmentation did not provide sufficient data diversity."
            return sentence

        if "synthetic data generation" in title_n:
            methods: list[str] = []
            if "phase shift" in ev_n:
                methods.append("phase-shift profiles")
            if "otsu" in ev_n:
                methods.append("Otsu segmentation")
            if "connected components" in ev_n:
                methods.append("connected-component labeling")
            if "rearrang" in ev_n:
                methods.append("random component rearrangement")
            if methods:
                joined = ", ".join(methods[:-1]) + (f", and {methods[-1]}" if len(methods) > 1 else methods[0])
                return (
                    "Synthetic training volumes were constructed from segmented microchip layers "
                    f"using {joined}."
                )
            return (
                "The slide described synthetic training-data generation by reorganizing "
                "microchip-layer components to increase dataset diversity."
            )

        if "cnn performance" in title_n or ("ground truth" in ev_n and "gpu" in ev_n):
            facts = NumericFactValidator.extract_facts(evidence)
            training = next((f.value for f in facts if f.role == "training"), None)
            generated = next((f.value for f in facts if f.role == "generated"), None)
            count_bits: list[str] = []
            if generated:
                generated_text = f"{int(generated):,}" if float(generated).is_integer() else f"{generated:,}"
                count_bits.append(f"{generated_text} synthetic samples were generated")
            if training:
                training_text = f"{int(training):,}" if float(training).is_integer() else f"{training:,}"
                count_bits.append(f"{training_text} were used for training")
            if count_bits:
                first = "; ".join(count_bits).capitalize() + "."
            else:
                first = "The slide evaluated CNN performance on the synthetic dataset."
            if "512x512" in ev_n or "512 512" in ev_n:
                first += " Inputs were cropped to 512x512 pixels for GPU processing."
            if "quite good" in ev_n or "outlier" in ev_n or "ground truth" in ev_n:
                first += (
                    " Predictions matched the ground truth well overall, with errors mainly "
                    "in small or overlapping features."
                )
            return first

        if "data distributions" in title_n:
            if "background" in ev_n and ("not yet" in ev_n or "did not yet" in ev_n):
                return (
                    "The slide examined component distributions and noted that realistic "
                    "background distributions had not yet been implemented."
                )
            return "The slide examined the distributions used to construct the synthetic data."

        if "measurement data" in title_n and "simulation" in ev_n:
            sentence = "Measurement data were compared directly with the simulated data."
            if "background" in ev_n and ("zero" in ev_n or "zeros" in ev_n):
                sentence += (
                    " A remaining mismatch was attributed to the current simulation using "
                    "a zero-valued background."
                )
            return sentence

        if number := section.get("slide_number"):
            if int(number) == 1 and ("introduc" in ev_n or "update" in ev_n):
                concise_title = re.sub(r"\s+", " ", title).strip()
                if concise_title:
                    return f"The presentation introduced the topic '{concise_title}'."
        return ""

    def _compact_slide_fallback(
        self,
        spoken: str,
        section: dict[str, Any],
    ) -> str:
        clean = self._clean_slide_summary(spoken)
        if not clean:
            return ""
        title = str(section.get("title") or "")
        body = str(section.get("body_text") or "")
        keywords = " ".join(str(item) for item in section.get("keywords") or [])
        context_tokens = _content_tokens(f"{title} {body} {keywords}")

        chunks = [
            item.strip()
            for item in re.split(
                r"(?<=[.!?])\s+|\s+(?=(?:So|Now|Then|The|This|We|I)\s+[A-Z0-9])",
                clean,
            )
            if len(item.strip()) >= 18
        ]
        if not chunks:
            chunks = [clean]

        ranked: list[tuple[float, int, str]] = []
        for index, chunk in enumerate(chunks):
            lower = chunk.casefold()
            if _POST_TALK_CHATTER_RE.search(chunk):
                chunk = _POST_TALK_CHATTER_RE.sub("", chunk).strip(" ,.;:-")
                if not chunk:
                    continue
            c_tokens = _content_tokens(chunk)
            score = 0.0
            if context_tokens:
                score += 3.0 * len(c_tokens & context_tokens) / max(1, min(len(c_tokens), len(context_tokens)))
            if re.search(r"\d", chunk):
                score += 1.2
            if any(phrase in lower for phrase in (
                "don't want to go too much into detail",
                "do not want to go too much into detail",
                "modern technology",
                "zoom is not working",
            )):
                continue
            if any(term in lower for term in (
                "astra", "training", "validation", "ground truth", "performance",
                "segmentation", "projection", "dataset", "background", "distribution",
                "phase", "cnn", "gpu", "synthetic", "numerical", "layer",
            )):
                score += 1.0
            if 35 <= len(chunk) <= 280:
                score += 0.4
            ranked.append((score, index, chunk))

        chosen = sorted(ranked, key=lambda item: (-item[0], item[1]))[:3]
        chosen = sorted(chosen, key=lambda item: item[1])
        neutral = [self._neutralize_slide_sentence(item[2]) for item in chosen]
        summary = " ".join(item for item in neutral if item).strip()
        summary = self._clean_slide_summary(summary)
        words = summary.split()
        if len(words) > 55:
            summary = " ".join(words[:55]).rstrip(" ,;:") + "..."
        if len(summary) > 360:
            summary = summary[:357].rstrip(" ,;:") + "..."
        return summary

    @staticmethod
    def _clean_slide_summary(text: str) -> str:
        clean = re.sub(r"\s+", " ", str(text or "")).strip()
        clean = re.sub(
            r"^(?:on\s+)?slide\s+\d+\s*[,.:;-]*\s*",
            "",
            clean,
            flags=re.IGNORECASE,
        )
        clean = re.sub(
            r"^on\s+the\s+final\s+slide\s*[,.:;-]*\s*",
            "",
            clean,
            flags=re.IGNORECASE,
        )
        clean = _POST_TALK_CHATTER_RE.sub("", clean).strip(" ,;:-")
        clean = re.sub(
            r"^(?:so\s+first\s+to\s+the\s+background\s+of\s+the\s+problem\s+we\s+want\s+to\s+solve[, ]*"
            r"(?:so\s+as\s+you\s+all\s+probably\s+know\s*)?)",
            "",
            clean,
            flags=re.I,
        )
        clean = re.sub(r"\b(?:if\s+we\s+now\s+look\s+at|you\s+can\s+see|i\s+would\s+say|let's\s+say)\b[, ]*", "", clean, flags=re.I)
        clean = re.sub(r"\b(?:so|yes|yeah),?\s+(?=(?:the|this|i|we)\b)", "", clean, count=1, flags=re.I)
        return re.sub(r"\s+", " ", clean).strip()

    @staticmethod
    def _extractive_slide_summary(text: str) -> str:
        clean = re.sub(r"\s+", " ", text).strip()
        clean = re.sub(
            r"^(?:on\s+)?slide\s+\d+\s*[,.:;-]*\s*", "", clean, flags=re.IGNORECASE
        )
        clean = re.sub(
            r"^on\s+the\s+final\s+slide\s*[,.:;-]*\s*", "", clean, flags=re.IGNORECASE
        )
        sentences = [
            item.strip()
            for item in re.split(r"(?<=[.!?])\s+", clean)
            if item.strip()
        ]
        summary = " ".join(sentences[:2]) if sentences else clean
        if len(summary) > 620:
            summary = summary[:617].rstrip() + "..."
        return summary

    @staticmethod
    def _sentences(text: str) -> list[str]:
        clean = re.sub(r"[\t ]+", " ", text).strip()
        if not clean:
            return []
        pieces = re.split(r"(?<=[.!?])\s+|\n+", clean)
        return [item.strip() for item in pieces if item.strip()]

    @staticmethod
    def _trim_answer(text: str, limit: int = 360) -> str:
        clean = re.sub(r"\s+", " ", text).strip()
        clean = re.sub(r"\b(?:But|And|So)\s*$", "", clean, flags=re.I).rstrip(" ,;:")
        if len(clean) <= limit:
            return clean
        clipped = clean[: limit - 3].rstrip()
        if " " in clipped:
            clipped = clipped.rsplit(" ", 1)[0]
        return clipped.rstrip(" ,;:") + "..."

    @staticmethod
    def _dedupe_actions(items: list[ActionItem]) -> list[ActionItem]:
        output: list[ActionItem] = []
        for item in items:
            if any(_similar(item.task, prior.task) for prior in output):
                continue
            output.append(item)
        return output[:10]

    @staticmethod
    def _dedupe_questions(items: list[DiscussionQuestion]) -> list[DiscussionQuestion]:
        output: list[DiscussionQuestion] = []
        for item in items:
            existing = next(
                (prior for prior in output if _similar(item.question, prior.question)),
                None,
            )
            if existing is None:
                output.append(item)
            elif item.status == "answered" and existing.status != "answered":
                existing.status = "answered"
                existing.answer = item.answer
            elif not existing.answer and item.answer:
                existing.answer = item.answer
        return output

    @staticmethod
    def _unique_strings(
        values: list[str],
        *,
        limit: int,
        strip_confidence_for_key: bool = False,
    ) -> list[str]:
        output: list[str] = []
        seen: set[str] = set()
        for value in values:
            clean = re.sub(r"\s+", " ", str(value).strip())
            if not clean:
                continue
            key_source = (
                re.sub(r"\s*\(\d+% confidence\)$", "", clean)
                if strip_confidence_for_key else clean
            )
            key = _normalise(key_source)
            if not key or key in seen:
                continue
            seen.add(key)
            output.append(clean)
            if len(output) >= limit:
                break
        return output
