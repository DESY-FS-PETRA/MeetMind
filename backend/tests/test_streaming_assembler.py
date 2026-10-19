from __future__ import annotations

import unittest

from app.transcription.streaming_assembler import StreamingTranscriptAssembler


class StreamingTranscriptAssemblerTests(unittest.TestCase):
    def test_replaces_incorrect_provisional_tail(self) -> None:
        assembler = StreamingTranscriptAssembler()
        meeting_id = "meeting-1"

        chunks = [
            "The stale smell of old beer lingers.",
            "It takes heat to bring out the odor. A cold dip restores health and zest.",
            (
                "restores health at zest. A salt pickle tastes fine with ham. "
                "Tacos al pastor are my favorite. A zest fulfills..."
            ),
            "favorite. A zestful food is the hot cross bun.",
        ]

        snapshot = None
        for chunk in chunks:
            snapshot = assembler.add(meeting_id, chunk)

        self.assertIsNotNone(snapshot)
        self.assertEqual(
            snapshot.text,
            (
                "The stale smell of old beer lingers. It takes heat to bring out "
                "the odor. A cold dip restores health and zest. A salt pickle "
                "tastes fine with ham. Tacos al pastor are my favorite. A "
                "zestful food is the hot cross bun."
            ),
        )

    def test_merges_real_overlapping_whisper_chunks(self) -> None:
        assembler = StreamingTranscriptAssembler()
        meeting_id = "meeting-2"

        chunks = [
            (
                "The stale smell of old beer lingers. It takes heat to bring out "
                "the odor. A cold dip."
            ),
            (
                "a cold dip restores health and zest a salt pickle tastes fine "
                "with ham tacos al pastor are my"
            ),
            (
                "Tacos al pastor are my favorite. A zestful food is the hot "
                "cross bun."
            ),
        ]

        for chunk in chunks:
            assembler.add(meeting_id, chunk)
        final = assembler.finalize(meeting_id)

        self.assertIsNotNone(final)
        self.assertEqual(
            final.text,
            (
                "The stale smell of old beer lingers. It takes heat to bring out "
                "the odor. A cold dip restores health and zest a salt pickle "
                "tastes fine with ham tacos al pastor are my favorite. A "
                "zestful food is the hot cross bun."
            ),
        )
        self.assertTrue(final.is_final)

    def test_revision_and_segment_id_are_stable(self) -> None:
        assembler = StreamingTranscriptAssembler()
        first = assembler.add("m3", "Hello everyone and welcome to the meeting.")
        second = assembler.add("m3", "the meeting. Today we discuss deployment.")

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.segment_id, second.segment_id)
        self.assertGreater(second.revision, first.revision)


if __name__ == "__main__":
    unittest.main()
