from __future__ import annotations

import re
from dataclasses import dataclass


_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}

_NUM_TOKEN = (
    r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?[kK]?|"
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[-\s]+(?:one|two|three|"
    r"four|five|six|seven|eight|nine))?(?:\s+thousand|\s+hundred)?)"
)


@dataclass(frozen=True)
class NumericFact:
    value: float
    unit: str
    role: str
    raw_number: str
    evidence: str

    @property
    def display(self) -> str:
        if self.value.is_integer():
            integer = int(self.value)
            return f"{integer:,}"
        return f"{self.value:g}"


class NumericFactValidator:
    """Conservatively validate numeric claims against transcript/slide evidence.

    The validator does not try to solve scientific equations. It protects the
    semantic role of quantities that are easy for a small summarization model to
    confuse, e.g. "5,000 generated samples" vs "4,000 training samples".
    """

    _SAMPLE_PATTERNS = (
        ("generated", re.compile(
            rf"\b(?:generated|generate|created|create|produced|produce)\b[^.!?]{{0,55}}?"
            rf"(?P<num>{_NUM_TOKEN})\s+(?:synthetic\s+)?samples?\b",
            re.IGNORECASE,
        )),
        ("generated", re.compile(
            rf"\b(?P<num>{_NUM_TOKEN})\s+(?:synthetic\s+)?samples?\b[^.!?]{{0,35}}?"
            r"\b(?:generated|created|produced)\b",
            re.IGNORECASE,
        )),
        ("generated", re.compile(
            rf"\b(?:generated|created|produced)\b[^.!?]{{0,70}}?"
            rf"(?P<num>{_NUM_TOKEN})\s+(?:of\s+those|projections?)\b",
            re.IGNORECASE,
        )),
        ("training", re.compile(
            rf"\bfor\s+training\s+(?:i|we)\s+used\b[^.!?]{{0,35}}?"
            rf"(?P<num>{_NUM_TOKEN})\s+samples?\b",
            re.IGNORECASE,
        )),
        ("training", re.compile(
            rf"\bused\b[^.!?]{{0,25}}?(?P<num>{_NUM_TOKEN})\s+samples?\b"
            r"[^.!?]{0,22}?\bfor\s+training\b",
            re.IGNORECASE,
        )),
        ("training", re.compile(
            rf"\b(?P<num>{_NUM_TOKEN})\s+samples?\b[^.!?]{{0,30}}?\b(?:used\s+)?for\s+training\b",
            re.IGNORECASE,
        )),
        ("validation_testing", re.compile(
            rf"\b(?P<num>{_NUM_TOKEN})\s+samples?\b[^.!?]{{0,25}}?"
            r"\bfor\s+(?:validation\s+and\s+(?:testing|test)|validation/testing)\b",
            re.IGNORECASE,
        )),
        ("validation", re.compile(
            rf"\b(?P<num>{_NUM_TOKEN})\s+samples?\b[^.!?]{{0,20}}?\bfor\s+validation\b",
            re.IGNORECASE,
        )),
        ("testing", re.compile(
            rf"\b(?P<num>{_NUM_TOKEN})\s+samples?\b[^.!?]{{0,20}}?\bfor\s+(?:testing|test)\b",
            re.IGNORECASE,
        )),
    )

    _SUMMARY_SAMPLE_CLAIM = re.compile(
        rf"(?P<num>{_NUM_TOKEN})\s+(?P<label>(?:synthetic\s+)?(?:training\s+|validation\s+|testing\s+|test\s+)?samples?)",
        re.IGNORECASE,
    )

    @classmethod
    def extract_facts(cls, text: str) -> list[NumericFact]:
        clean = re.sub(r"\s+", " ", text or "").strip()
        clean = re.sub(r"(?<=\d)\s*,\s*(?=\d{3}\b)", ",", clean)
        if not clean:
            return []
        facts: list[NumericFact] = []
        seen: set[tuple[str, float, str]] = set()
        for role, pattern in cls._SAMPLE_PATTERNS:
            for match in pattern.finditer(clean):
                raw = match.group("num")
                value = cls._parse_number(raw)
                if value is None:
                    continue
                evidence = cls._sentence_around(clean, match.start(), match.end())
                if role == "generated" and "of those" in match.group(0).casefold():
                    if not re.search(r"\b(?:projection|projections|sample|samples)\b", evidence, re.I):
                        continue
                key = (role, value, "samples")
                if key in seen:
                    continue
                seen.add(key)
                facts.append(
                    NumericFact(
                        value=float(value),
                        unit="samples",
                        role=role,
                        raw_number=raw,
                        evidence=evidence,
                    )
                )
        return facts

    @classmethod
    def repair_summary(cls, text: str, evidence_text: str) -> str:
        """Repair contradicted sample-count claims; leave ambiguous facts alone."""
        clean = re.sub(r"\s+", " ", text or "").strip()
        clean = re.sub(r"(?<=\d)\s*,\s*(?=\d{3}\b)", ",", clean)
        if not clean:
            return clean
        facts = cls.extract_facts(evidence_text)
        by_role: dict[str, set[float]] = {}
        for fact in facts:
            by_role.setdefault(fact.role, set()).add(fact.value)

        unique = {
            role: next(iter(values))
            for role, values in by_role.items()
            if len(values) == 1
        }

        def replace_claim(match: re.Match[str]) -> str:
            raw_number = match.group("num")
            label = match.group("label")
            role = cls._role_from_label(label)
            if role is None or role not in unique:
                return match.group(0)
            current = cls._parse_number(raw_number)
            if current is None or float(current) == float(unique[role]):
                return match.group(0)
            return f"{cls._format_number(unique[role])} {label}"

        repaired = cls._SUMMARY_SAMPLE_CLAIM.sub(replace_claim, clean)
        repaired = cls._repair_generated_training_sentence(repaired, unique)
        return repaired

    @classmethod
    def _repair_generated_training_sentence(
        cls,
        text: str,
        unique: dict[str, float],
    ) -> str:
        generated = unique.get("generated")
        training = unique.get("training")
        if generated is None or training is None or generated == training:
            return text

        # A common local-LLM error observed in scientific meeting reports is to
        # attach the total generated count to the word "training". If a sentence
        # discusses data generation/projection and a training-sample count, retain
        # both grounded quantities instead of silently losing the total count.
        sentences = re.split(r"(?<=[.!?])\s+", text)
        output: list[str] = []
        for sentence in sentences:
            lower = sentence.casefold()
            if (
                "training sample" in lower
                and any(token in lower for token in ("generated", "project", "synthetic"))
            ):
                count_match = cls._SUMMARY_SAMPLE_CLAIM.search(sentence)
                if count_match and cls._role_from_label(count_match.group("label")) == "training":
                    prefix = sentence[: count_match.start()].rstrip(" ,;:")
                    prefix = re.sub(
                        r"(?:,?\s*)\b(?:resulting\s+in|yielding|producing)\s*$",
                        "",
                        prefix,
                        flags=re.I,
                    ).rstrip(" ,;:")
                    suffix = sentence[count_match.end():].strip()
                    suffix = suffix.strip(" .,:;")
                    clause = (
                        f"{prefix}, producing {cls._format_number(generated)} synthetic samples; "
                        f"{cls._format_number(training)} were used for training"
                    ).strip(" ,")
                    val_test = unique.get("validation_testing")
                    if val_test is not None:
                        clause += (
                            f"; {cls._format_number(val_test)} samples were used for "
                            "validation and testing"
                        )
                    if suffix:
                        # Avoid duplicating generic tails such as "were generated".
                        if not re.match(r"^(?:were\s+)?(?:generated|created|produced)\b", suffix, re.I):
                            clause += f" {suffix}"
                    sentence = clause.rstrip(".") + "."
            output.append(sentence)
        return " ".join(item.strip() for item in output if item.strip())

    @staticmethod
    def _role_from_label(label: str) -> str | None:
        normalized = re.sub(r"\s+", " ", label.casefold()).strip()
        if normalized.startswith("training "):
            return "training"
        if normalized.startswith("validation "):
            return "validation"
        if normalized.startswith("testing ") or normalized.startswith("test "):
            return "testing"
        if normalized.startswith("synthetic "):
            return "generated"
        return None

    @classmethod
    def _parse_number(cls, raw: str) -> float | None:
        value = re.sub(r"\s+", " ", raw.strip().casefold())
        if not value:
            return None
        if re.fullmatch(r"\d+(?:\.\d+)?[k]", value):
            return float(value[:-1]) * 1000.0
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", value):
            return float(value.replace(",", ""))

        multiplier = 1
        if value.endswith(" thousand"):
            value = value[: -len(" thousand")]
            multiplier = 1000
        elif value.endswith(" hundred"):
            value = value[: -len(" hundred")]
            multiplier = 100

        parts = re.split(r"[-\s]+", value)
        total = 0
        for part in parts:
            number = _NUMBER_WORDS.get(part)
            if number is None:
                return None
            total += number
        return float(total * multiplier)

    @staticmethod
    def _format_number(value: float) -> str:
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{value:g}"

    @staticmethod
    def _sentence_around(text: str, start: int, end: int) -> str:
        left = max(text.rfind(".", 0, start), text.rfind("?", 0, start), text.rfind("!", 0, start))
        right_candidates = [pos for pos in (text.find(".", end), text.find("?", end), text.find("!", end)) if pos >= 0]
        right = min(right_candidates) + 1 if right_candidates else len(text)
        return text[left + 1 : right].strip()
