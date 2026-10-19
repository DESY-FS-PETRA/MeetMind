from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.schemas.summary import ActionItem, MeetingSummaryContent


class StructuredMeetingEnricher:
    """Recover explicit decisions and assignments missed by a small LLM.

    The enricher is intentionally conservative. It only adds information that is
    directly expressed by recognisable decision or assignment phrases in the
    transcript. It never invents owners, deadlines, or tasks.
    """

    _DECISION_PATTERNS = (
        re.compile(
            r"^(?:the\s+team|the\s+group|the\s+participants|participants|we|they)\s+"
            r"(?:have\s+|had\s+)?"
            r"(?:agreed|decided|selected|chose|approved|adopted|confirmed|committed)\s+"
            r"(?:that\s+|to\s+|on\s+)?(?P<body>.+)$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^(?:it\s+was\s+)?(?:agreed|decided|confirmed)\s+"
            r"(?:that\s+|to\s+)?(?P<body>.+)$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^(?:the\s+team|the\s+group|we|they)\s+will\s+"
            r"(?P<body>(?:use|adopt|select|choose|standardize|proceed\s+with|move\s+to|"
            r"deploy|implement)\b.+)$",
            re.IGNORECASE,
        ),
    )

    _ACTION_PATTERN = re.compile(
        r"^(?P<owner>.+?)\s+"
        r"(?:will|must|should|needs?\s+to|is\s+responsible\s+for|was\s+assigned\s+to)\s+"
        r"(?P<task>.+)$",
        re.IGNORECASE,
    )

    _DEADLINE_PATTERN = re.compile(
        r"\s+(?:by|before|no\s+later\s+than|due(?:\s+on)?|on)\s+"
        r"(?P<deadline>"
        r"today|tomorrow|tonight|"
        r"(?:this|next)\s+(?:week|month|quarter|year|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)|"
        r"Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|"
        r"(?:the\s+)?\d{1,2}(?:st|nd|rd|th)?(?:\s+of)?\s+[A-Za-z]+(?:\s+\d{4})?|"
        r"[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?|"
        r"\d{4}-\d{2}-\d{2}"
        r")\s*[.!?]*$",
        re.IGNORECASE,
    )

    _DECISION_ACTION_VERBS = {
        "use",
        "adopt",
        "select",
        "choose",
        "standardize",
        "proceed",
        "move",
        "deploy",
    }

    _OWNER_BLACKLIST = {
        "normally", "probably", "maybe", "actually", "basically",
        "apparently", "yes", "no", "okay", "ok", "then", "today",
    }

    _META_TASK_RE = re.compile(
        r"\b(?:be\s+fine|one\s+more\s+thing|finish\s+it\s+just|"
        r"finish\s+(?:the\s+)?talk|share\s+(?:the\s+)?screen|"
        r"share\s+everything|go\s+ahead|thank\s+you)\b",
        re.IGNORECASE,
    )

    def enrich(
        self,
        content: MeetingSummaryContent,
        transcript: str,
    ) -> MeetingSummaryContent:
        result = content.model_copy(deep=True)
        sentences = self._split_sentences(transcript)

        for decision in self._extract_decisions(sentences):
            if not any(self._similar(decision, current) for current in result.decisions):
                result.decisions.append(decision)

        for extracted in self._extract_action_items(sentences):
            existing = self._find_matching_action(result.action_items, extracted)
            if existing is None:
                result.action_items.append(extracted)
                continue

            # Preserve the model's wording but fill missing fields from explicit
            # transcript evidence.
            if not existing.owner and extracted.owner:
                existing.owner = extracted.owner
            if not existing.deadline and extracted.deadline:
                existing.deadline = extracted.deadline

        result.decisions = self._deduplicate(result.decisions)
        result.action_items = self._deduplicate_actions(result.action_items)
        return result

    @classmethod
    def _split_sentences(cls, transcript: str) -> list[str]:
        normalised = " ".join(transcript.split()).strip()
        if not normalised:
            return []
        return [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", normalised)
            if sentence.strip()
        ]

    @classmethod
    def _extract_decisions(cls, sentences: list[str]) -> list[str]:
        decisions: list[str] = []
        for sentence in sentences:
            bare = sentence.strip().rstrip(".!?")
            for pattern in cls._DECISION_PATTERNS:
                match = pattern.match(bare)
                if not match:
                    continue
                body = cls._clean_statement(match.group("body"))
                if body:
                    decisions.append(body)
                break
        return cls._deduplicate(decisions)

    @classmethod
    def _extract_action_items(cls, sentences: list[str]) -> list[ActionItem]:
        items: list[ActionItem] = []
        for sentence in sentences:
            bare = sentence.strip().rstrip(".!?")
            match = cls._ACTION_PATTERN.match(bare)
            if not match:
                continue

            raw_owner = " ".join(match.group("owner").split()).strip()
            if not cls._is_valid_owner(raw_owner):
                continue
            owner = cls._normalise_owner(raw_owner)
            task = match.group("task").strip()
            if cls._META_TASK_RE.search(task):
                continue

            first_verb = task.casefold().split(maxsplit=1)[0] if task else ""
            if raw_owner.casefold() == "we" and first_verb in cls._DECISION_ACTION_VERBS:
                # "We will use X" is normally a decision, not an assigned task.
                continue

            deadline: str | None = None
            deadline_match = cls._DEADLINE_PATTERN.search(task)
            if deadline_match:
                deadline = cls._clean_deadline(deadline_match.group("deadline"))
                task = task[: deadline_match.start()].strip()

            task = cls._clean_task(task)
            if not task:
                continue

            items.append(ActionItem(task=task, owner=owner, deadline=deadline))

        return cls._deduplicate_actions(items)

    @staticmethod
    def _is_valid_owner(owner: str) -> bool:
        lowered = owner.casefold()
        if lowered in StructuredMeetingEnricher._OWNER_BLACKLIST:
            return False
        if lowered in {"we", "the team", "the group"}:
            return True
        if re.fullmatch(r"the\s+[A-Za-z0-9'’\-]+\s+team", owner, re.IGNORECASE):
            return True

        tokens = owner.replace("&", " and ").split()
        if not 1 <= len(tokens) <= 6:
            return False
        connectors = {"and", "dr.", "prof.", "mr.", "ms."}
        meaningful = [token for token in tokens if token.casefold() not in connectors]
        if not meaningful:
            return False
        return all(token[:1].isupper() for token in meaningful)

    @staticmethod
    def _normalise_owner(owner: str) -> str:
        owner = " ".join(owner.split()).strip()
        lowered = owner.casefold()
        if lowered == "we":
            return "Team"
        if lowered == "the team":
            return "Team"
        if lowered == "the group":
            return "Group"
        return " ".join(part.capitalize() for part in owner.split())

    @staticmethod
    def _clean_statement(text: str) -> str:
        text = " ".join(text.split()).strip(" ,;:-")
        if not text:
            return ""
        return text[0].upper() + text[1:].rstrip(".!?") + "."

    @staticmethod
    def _clean_task(text: str) -> str:
        text = " ".join(text.split()).strip(" ,;:-")
        if not text:
            return ""
        # Keep an infinitive/action phrase rather than repeating the owner.
        return text[0].upper() + text[1:].rstrip(".!?") + "."

    @staticmethod
    def _clean_deadline(text: str) -> str:
        cleaned = " ".join(text.split()).strip(" ,;:.!?-")
        if not cleaned:
            return ""
        # Retain familiar lowercase relative dates, capitalize weekdays/months.
        if cleaned.casefold() in {"today", "tomorrow", "tonight"}:
            return cleaned.casefold()
        return cleaned[0].upper() + cleaned[1:]

    @classmethod
    def _find_matching_action(
        cls,
        existing: list[ActionItem],
        candidate: ActionItem,
    ) -> ActionItem | None:
        for item in existing:
            if cls._similar(item.task, candidate.task):
                return item
        return None

    @classmethod
    def _deduplicate(cls, values: list[str]) -> list[str]:
        unique: list[str] = []
        for value in values:
            cleaned = " ".join(value.split()).strip()
            if cleaned and not any(cls._similar(cleaned, prior) for prior in unique):
                unique.append(cleaned)
        return unique

    @classmethod
    def _deduplicate_actions(cls, items: list[ActionItem]) -> list[ActionItem]:
        unique: list[ActionItem] = []
        for item in items:
            existing = cls._find_matching_action(unique, item)
            if existing is None:
                unique.append(item)
                continue
            if not existing.owner and item.owner:
                existing.owner = item.owner
            if not existing.deadline and item.deadline:
                existing.deadline = item.deadline
        return unique

    @staticmethod
    def _normalise_for_compare(text: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))

    @classmethod
    def _similar(cls, left: str, right: str) -> bool:
        a = cls._normalise_for_compare(left)
        b = cls._normalise_for_compare(right)
        if not a or not b:
            return False
        if a == b:
            return True
        if a in b or b in a:
            shorter = min(len(a.split()), len(b.split()))
            return shorter >= 3
        return SequenceMatcher(None, a, b).ratio() >= 0.72
