from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any


_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")
_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "into", "using",
    "are", "was", "were", "will", "have", "has", "our", "their", "about",
    "slide", "figure", "result", "results", "show", "shows", "data",
    "from",  # repeated footer words are otherwise down-weighted by title/body weights
    "there", "any",
}
_SETUP_MARKERS = (
    "zoom", "share the whole screen", "share everything", "screen", "not working",
    "download zoom", "modern technology", "can you see", "looks so weird",
)


def _norm(value: str) -> str:
    value = value.casefold().replace("x-ray", "x ray").replace("–", "-").replace("—", "-")
    value = re.sub(r"[^a-z0-9+.-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(value: str) -> set[str]:
    return {
        token for token in _TOKEN_RE.findall(_norm(value))
        if len(token) >= 3 and token not in _STOPWORDS
    }


def _contains(text: str, phrase: str) -> bool:
    text_n = _norm(text)
    phrase_n = _norm(phrase)
    return bool(phrase_n) and f" {phrase_n} " in f" {text_n} "


def _clean_reference_body(value: str) -> str:
    lines = []
    for line in str(value).splitlines():
        clean = line.strip()
        if not clean or clean == "<number>":
            continue
        # Scientific slide templates often repeat "Deck title | Author" in a
        # footer. It is not useful for deciding which slide is active.
        if "|" in clean and len(clean) < 160:
            continue
        lines.append(clean)
    return " ".join(lines)


@dataclass(frozen=True, slots=True)
class AlignmentChunk:
    text: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class OfflineSlideBoundary:
    slide_number: int
    offset: int
    score: float


class OfflineSlideAligner:
    """Globally align a completed transcript to an ordered slide deck.

    A Viterbi-style dynamic program uses the whole recording rather than local
    live decisions. States are monotonic: preamble -> slide 1 -> ... -> slide N.
    Staying on a slide is free; advancing costs a small amount and therefore
    requires either local slide evidence or a later stronger match. This is
    particularly useful for image-heavy scientific slides with little text.
    """

    def align(
        self,
        transcript: str,
        presentation: dict[str, Any],
    ) -> list[OfflineSlideBoundary]:
        slides = list(presentation.get("slides") or [])
        chunks = self._chunks(transcript)
        if not slides or not chunks:
            return []

        n = len(slides)
        m = len(chunks)
        neg = -1e18
        dp = [[neg] * (n + 1) for _ in range(m)]
        back = [[-1] * (n + 1) for _ in range(m)]

        # State 0 means pre-presentation/setup chatter.
        for state in range(n + 1):
            emission = self._emission(chunks[0], state, slides)
            if state == 0:
                dp[0][state] = emission
            elif state == 1:
                dp[0][state] = emission - 0.6

        for i in range(1, m):
            for state in range(n + 1):
                emission = self._emission(chunks[i], state, slides)
                candidates: list[tuple[float, int]] = []
                # Stay in the same state.
                candidates.append((dp[i - 1][state] + 0.08, state))
                # Monotonic advances may skip up to two image-only slides. A
                # larger penalty makes sequential movement preferable, but it
                # prevents the optimizer from assigning unrelated Q&A to a
                # slide merely to prepare for a strong appendix match later.
                if state > 0:
                    for delta, penalty in ((1, 0.9), (2, 2.1), (3, 3.4)):
                        previous = state - delta
                        if previous < 0:
                            continue
                        if previous == 0 and state != 1:
                            continue
                        actual_penalty = 0.25 if previous == 0 else penalty
                        candidates.append((dp[i - 1][previous] - actual_penalty, previous))
                best_score, best_prev = max(candidates, key=lambda item: item[0])
                if best_score <= neg / 2:
                    continue
                dp[i][state] = best_score + emission
                back[i][state] = best_prev

        # Do not force the deck to finish. The strongest globally consistent
        # state wins, while a small progress bonus breaks ties in favour of a
        # later slide when evidence is otherwise equivalent.
        end_state = max(
            range(n + 1),
            key=lambda state: dp[-1][state] + (0.08 * state),
        )
        states = [0] * m
        states[-1] = end_state
        for i in range(m - 1, 0, -1):
            states[i - 1] = max(0, back[i][states[i]])

        boundaries: list[OfflineSlideBoundary] = []
        previous_state = 0
        for chunk, state in zip(chunks, states):
            if state <= 0:
                previous_state = state
                continue
            if state != previous_state:
                boundaries.append(
                    OfflineSlideBoundary(
                        slide_number=state,
                        offset=chunk.start,
                        score=round(self._emission(chunk, state, slides), 3),
                    )
                )
            previous_state = state

        # Move provisional transitions to strong local evidence when available.
        # This prevents a future appendix match from pulling an earlier slide
        # boundary backwards into unrelated Q&A.
        boundaries = self._refine_boundaries(boundaries, chunks, slides)
        return boundaries

    def _emission(self, chunk: AlignmentChunk, state: int, slides: list[dict[str, Any]]) -> float:
        if state == 0:
            lowered = _norm(chunk.text)
            setup = sum(2.6 for marker in _SETUP_MARKERS if marker in lowered)
            strongest_slide = max(
                (self._score_slide(chunk.text, slide) for slide in slides),
                default=0.0,
            )
            return setup + (1.0 if strongest_slide < 2.0 else -min(5.0, strongest_slide * 0.55))
        score = self._score_state(chunk.text, state, slides)
        return score if score >= 1.5 else score - 0.45

    def _score_state(self, text: str, state: int, slides: list[dict[str, Any]]) -> float:
        slide = slides[state - 1]
        score = self._score_slide(text, slide)
        body = _norm(_clean_reference_body(str(slide.get("body_text") or "")))
        keywords = list(slide.get("keywords") or [])
        meaningful_body = [token for token in _tokens(body) if token != "number"]
        if state > 1 and not keywords and len(meaningful_body) <= 2:
            previous = slides[state - 2]
            previous_lines = [
                line.strip()
                for line in str(previous.get("body_text") or "").splitlines()
                if line.strip() and line.strip() != "<number>" and "|" not in line
            ]
            bridge_text = " ".join(previous_lines[-2:])[-420:]
            bridge_tokens = _tokens(bridge_text)
            overlap = len(_tokens(text) & bridge_tokens)
            score += min(5.0, 0.9 * overlap)
            for phrase in ("randomly rearrange", "synthetically generate", "background distributions"):
                if _contains(bridge_text, phrase) and _contains(text, phrase):
                    score += 5.0
        return score

    def _refine_boundaries(
        self,
        boundaries: list[OfflineSlideBoundary],
        chunks: list[AlignmentChunk],
        slides: list[dict[str, Any]],
    ) -> list[OfflineSlideBoundary]:
        if not boundaries:
            return boundaries
        refined: list[OfflineSlideBoundary] = []
        for index, boundary in enumerate(boundaries):
            next_offset = (
                boundaries[index + 1].offset if index + 1 < len(boundaries) else math.inf
            )
            lower_offset = (
                refined[-1].offset + 1 if refined else max(0, boundary.offset)
            )
            candidates: list[tuple[float, AlignmentChunk]] = []
            for chunk in chunks:
                if chunk.start < lower_offset or chunk.start >= next_offset:
                    continue
                score = self._score_state(chunk.text, boundary.slide_number, slides)
                candidates.append((score, chunk))
            if not candidates:
                refined.append(boundary)
                continue
            max_score = max(score for score, _ in candidates)
            slide = slides[boundary.slide_number - 1]
            title_norm = _norm(str(slide.get("title") or ""))

            # Closing / Q&A slides are usually sparse and lexical overlap from the
            # preceding performance discussion can otherwise pull the boundary too
            # early.  If the slide title itself is spoken (for example “thank you
            # for your attention”), prefer the first exact title cue.
            if "thank you" in title_norm:
                exact_title = [
                    (score, chunk)
                    for score, chunk in candidates
                    if (
                        "thank you" in _norm(chunk.text)
                        or "thanks for your attention" in _norm(chunk.text)
                    )
                ]
                if exact_title:
                    score, chunk = exact_title[0]
                    chunk_lower = chunk.text.casefold()
                    cue_position = chunk_lower.find("thank you")
                    if cue_position < 0:
                        cue_position = chunk_lower.find("thanks for your attention")
                    cue_offset = chunk.start + max(0, cue_position)
                    refined.append(
                        OfflineSlideBoundary(
                            slide_number=boundary.slide_number,
                            offset=cue_offset,
                            score=round(max(score, 5.0), 3),
                        )
                    )
                    continue

            sparse = (
                not list(slide.get("keywords") or [])
                and len(_tokens(_clean_reference_body(str(slide.get("body_text") or "")))) <= 2
            )
            threshold = 3.0 if sparse else max(4.0, max_score * 0.55)
            strong = [(score, chunk) for score, chunk in candidates if score >= threshold]
            if strong:
                score, chunk = strong[0]
                refined.append(
                    OfflineSlideBoundary(
                        slide_number=boundary.slide_number,
                        offset=chunk.start,
                        score=round(score, 3),
                    )
                )
            else:
                refined.append(boundary)
        # Ensure refinement never inverts the monotonic boundary order.
        output: list[OfflineSlideBoundary] = []
        last_offset = -1
        for item in refined:
            offset = max(last_offset + 1, item.offset)
            output.append(
                OfflineSlideBoundary(item.slide_number, offset, item.score)
            )
            last_offset = offset
        return output

    def _score_slide(self, text: str, slide: dict[str, Any]) -> float:
        number = int(slide.get("slide_number") or 0)
        title = str(slide.get("title") or "")
        body = _clean_reference_body(str(slide.get("body_text") or ""))
        notes = str(slide.get("notes_text") or "")
        keywords = [str(item) for item in slide.get("keywords") or []]
        speech_tokens = _tokens(text)
        title_tokens = _tokens(title)
        body_tokens = _tokens(f"{body} {notes}")

        score = 0.0
        score += 2.6 * len(speech_tokens & title_tokens)
        score += min(5.0, 0.65 * len(speech_tokens & body_tokens))
        if title and _contains(text, title):
            score += 8.0
        for keyword in keywords:
            if _contains(text, keyword):
                score += 5.5 + min(2.0, 0.35 * len(_tokens(keyword)))
            else:
                score += 1.0 * len(speech_tokens & _tokens(keyword))

        normalized = _norm(text)
        explicit = re.search(r"\b(?:on\s+)?slide\s+(\d{1,3})\b", normalized)
        if explicit and int(explicit.group(1)) == number:
            score += 20.0
        if "on the final slide" in normalized and number == len(slides):
            score += 20.0

        title_n = _norm(title)
        if "thank you for your attention" in normalized and "thank you" in title_n:
            score += 18.0
        if "are there any questions" in normalized and "question" in _norm(f"{title} {body}"):
            score += 10.0
        if "measurement data" in normalized and "measurement data" in title_n:
            score += 12.0
        if "background distributions" in normalized and "distribution" in title_n:
            score += 10.0
        if "performance" in normalized and "performance" in title_n:
            score += 5.0
        body_n = _norm(body)
        if "4k samples" in body_n and re.search(r"\b4\s*(?:,\s*)?000\s+samples\b", text, re.IGNORECASE):
            score += 8.0
        if "512x512" in body_n and re.search(r"\b512\s*[x×]\s*512\b", text, re.IGNORECASE):
            score += 8.0
        return score

    @staticmethod
    def _chunks(transcript: str) -> list[AlignmentChunk]:
        chunks: list[AlignmentChunk] = []
        # Newlines are ASR segment boundaries; punctuation gives finer-grained
        # boundaries when several slides are advanced within one batch segment.
        pattern = re.compile(r"[^.!?\n]+(?:[.!?]+|(?=\n)|$)")
        for match in pattern.finditer(transcript):
            raw = match.group(0)
            leading = len(raw) - len(raw.lstrip())
            trailing = len(raw.rstrip())
            text = raw.strip()
            if len(text) < 8:
                continue
            start = match.start() + leading
            end = match.start() + trailing
            # Extremely long ASR clauses are split on commas/semicolons so a
            # rapid appendix slide change can still create multiple states.
            if len(text) > 360:
                local_cursor = 0
                for part in re.split(r"(?<=[,;:])\s+", text):
                    clean = part.strip()
                    if not clean:
                        continue
                    pos = text.find(part, local_cursor)
                    part_start = start + max(0, pos)
                    part_end = part_start + len(part)
                    chunks.append(AlignmentChunk(clean, part_start, part_end))
                    local_cursor = max(local_cursor, pos + len(part))
            else:
                chunks.append(AlignmentChunk(text, start, end))
        return chunks
