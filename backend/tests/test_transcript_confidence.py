from __future__ import annotations

import unittest

from app.transcription.result import TranscriptionResult, WordResult
from app.transcription.streaming_assembler import StreamingTranscriptAssembler
from app.transcription.transcript_cleaner import TranscriptCleaner


class TranscriptConfidenceTests(unittest.TestCase):
    def test_low_confidence_words_are_exposed(self) -> None:
        assembler = StreamingTranscriptAssembler(low_confidence_threshold=0.65)
        result = TranscriptionResult(
            text="The stale smell of old weird lingers.",
            words=(
                WordResult("The", 0.99),
                WordResult("stale", 0.95),
                WordResult("smell", 0.93),
                WordResult("of", 0.98),
                WordResult("old", 0.92),
                WordResult("weird", 0.41),
                WordResult("lingers.", 0.96),
            ),
            average_confidence=0.877,
        )

        snapshot = assembler.add("meeting-confidence", result)

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.low_confidence_count, 1)
        flagged = [word["text"] for word in snapshot.words if word["needs_review"]]
        self.assertEqual(flagged, ["weird"])

    def test_confidence_survives_exact_overlap(self) -> None:
        assembler = StreamingTranscriptAssembler(low_confidence_threshold=0.65)
        first = TranscriptionResult(
            text="Tacos al pastor are my",
            words=tuple(
                WordResult(text, probability)
                for text, probability in [
                    ("Tacos", 0.91),
                    ("al", 0.90),
                    ("pastor", 0.88),
                    ("are", 0.95),
                    ("my", 0.93),
                ]
            ),
        )
        second = TranscriptionResult(
            text="Tacos al pastor are my favorite.",
            words=tuple(
                WordResult(text, probability)
                for text, probability in [
                    ("Tacos", 0.96),
                    ("al", 0.94),
                    ("pastor", 0.92),
                    ("are", 0.97),
                    ("my", 0.96),
                    ("favorite.", 0.89),
                ]
            ),
        )

        assembler.add("meeting-overlap", first)
        snapshot = assembler.add("meeting-overlap", second)

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.text, "Tacos al pastor are my favorite.")
        self.assertAlmostEqual(snapshot.words[0]["probability"], 0.96)


class TranscriptCleanerTests(unittest.TestCase):
    def test_final_cleanup_does_not_replace_words(self) -> None:
        cleaner = TranscriptCleaner()
        words = [
            WordResult("the", 0.9),
            WordResult("cold", 0.9),
            WordResult("dip.", 0.9),
            WordResult("restores", 0.9),
            WordResult("health", 0.9),
        ]

        cleaned = cleaner.clean_words(words, final=True)

        self.assertEqual(
            cleaner.text(cleaned),
            "The cold dip restores health.",
        )
        self.assertEqual(
            [word.text.rstrip(".").casefold() for word in cleaned],
            ["the", "cold", "dip", "restores", "health"],
        )

    def test_joins_split_hyphens_and_removes_immediate_repetition(self) -> None:
        cleaner = TranscriptCleaner()
        words = [
            WordResult("Slide", 0.9),
            WordResult("-Aware", 0.9),
            WordResult("X", 0.9),
            WordResult("-ray", 0.9),
            WordResult("cluster", 0.8),
            WordResult("cluster", 0.9),
            WordResult("PETRA", 0.9),
            WordResult("IV", 0.9),
            WordResult("beamlines.", 0.9),
            WordResult("PETRA", 0.8),
            WordResult("IV", 0.8),
            WordResult("beamline", 0.8),
        ]

        cleaned = cleaner.clean_words(words, final=True)

        self.assertEqual(
            cleaner.text(cleaned),
            "Slide-Aware X-ray cluster PETRA IV beamlines.",
        )


if __name__ == "__main__":
    unittest.main()
