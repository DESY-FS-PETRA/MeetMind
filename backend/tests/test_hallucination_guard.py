from __future__ import annotations

import unittest

from app.transcription.hallucination_guard import TranscriptHallucinationGuard
from app.transcription.result import TranscriptionResult, WordResult


class HallucinationGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = TranscriptHallucinationGuard()

    @staticmethod
    def result(text: str) -> TranscriptionResult:
        return TranscriptionResult(
            text=text,
            words=tuple(WordResult(token, 0.9) for token in text.split()),
            average_confidence=0.9,
        )

    def test_removes_prompt_induced_repeated_hotword_run(self) -> None:
        phrase = "X-ray beam induced current"
        result = self.result("Introduction " + " ".join([phrase] * 7) + " conclusion")
        cleaned, report = self.guard.sanitize(
            result,
            active_terms=(phrase,),
        )
        self.assertEqual(cleaned.text, "Introduction conclusion")
        self.assertTrue(report.changed)
        self.assertGreater(report.removed_word_count, 0)

    def test_removes_long_single_character_run(self) -> None:
        result = self.result("Normal speech ZZZZZZZZZZZZZZZZZ more speech")
        cleaned, report = self.guard.sanitize(result)
        self.assertEqual(cleaned.text, "Normal speech more speech")
        self.assertTrue(report.removed_character_runs)

    def test_keeps_single_genuine_technical_phrase(self) -> None:
        phrase = "X-ray beam induced current"
        result = self.result(f"We measured {phrase} at the beamline")
        cleaned, report = self.guard.sanitize(
            result,
            active_terms=(phrase,),
        )
        self.assertEqual(cleaned.text, result.text)
        self.assertFalse(report.changed)

    def test_collapses_generic_repetition_to_one_copy(self) -> None:
        result = self.result("thank you thank you thank you next topic")
        cleaned, report = self.guard.sanitize(result)
        self.assertEqual(cleaned.text, "thank you next topic")
        self.assertGreater(report.collapsed_word_count, 0)


if __name__ == "__main__":
    unittest.main()
