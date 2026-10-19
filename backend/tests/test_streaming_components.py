from __future__ import annotations

import unittest

from app.audio.pcm_chunker import PCMChunker
from app.transcription.text_stitcher import TranscriptStitcher


class PCMChunkerTests(unittest.TestCase):
    def test_chunks_keep_overlap(self) -> None:
        # Simplified 10 bytes/sec audio makes the boundaries easy to verify.
        chunker = PCMChunker(
            sample_rate=5,
            channels=1,
            sample_width=2,
            chunk_seconds=4,
            overlap_seconds=1,
            min_flush_seconds=0.5,
        )
        data = bytes(range(70))
        chunks = chunker.add(data)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0], bytes(range(40)))
        self.assertEqual(chunks[1], bytes(range(30, 70)))
        self.assertIsNone(chunker.flush())

    def test_flush_keeps_new_tail(self) -> None:
        chunker = PCMChunker(
            sample_rate=5,
            channels=1,
            sample_width=2,
            chunk_seconds=4,
            overlap_seconds=1,
            min_flush_seconds=0.5,
        )
        chunks = chunker.add(bytes(range(55)))
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunker.flush(), bytes(range(30, 55)))


class TranscriptStitcherTests(unittest.TestCase):
    def test_exact_overlap(self) -> None:
        stitcher = TranscriptStitcher()
        first = stitcher.stitch("m1", "I am jumping in for Philip today because he cannot")
        second = stitcher.stitch(
            "m1",
            "because he cannot attend the meeting. I am going to talk about summer school.",
        )
        self.assertEqual(first, "I am jumping in for Philip today because he cannot")
        self.assertEqual(
            second,
            "attend the meeting. I am going to talk about summer school.",
        )

    def test_fuzzy_overlap(self) -> None:
        stitcher = TranscriptStitcher()
        stitcher.stitch("m2", "We discussed the project and the next important milestone")
        second = stitcher.stitch(
            "m2",
            "the project and our next important milestone is deployment next week",
        )
        self.assertEqual(second, "is deployment next week")


if __name__ == "__main__":
    unittest.main()
