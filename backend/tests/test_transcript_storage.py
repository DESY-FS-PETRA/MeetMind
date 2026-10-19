from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.storage.meeting_storage import MeetingStorage


class TranscriptStorageTests(unittest.TestCase):
    def test_final_clean_transcript_and_confidence_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "storage.db"
            storage = MeetingStorage(
                database_url=f"sqlite:///{database_path.as_posix()}"
            )
            try:
                storage.create_meeting(
                    "meeting-storage",
                    "Test",
                    "2026-07-21T00:00:00Z",
                )
                storage.upsert_transcript(
                    "meeting-storage",
                    "The stale smell of old weird lingers.",
                    segment_id="rolling",
                    revision=3,
                    is_final=True,
                    words=[
                        {
                            "text": "weird",
                            "probability": 0.41,
                            "needs_review": True,
                        }
                    ],
                    average_confidence=0.88,
                    low_confidence_count=1,
                )

                items = storage.load_transcript("meeting-storage")
                self.assertEqual(items[0]["low_confidence_count"], 1)
                self.assertTrue(items[0]["words"][0]["needs_review"])
                self.assertEqual(
                    storage.load_final_transcript_text("meeting-storage"),
                    "The stale smell of old weird lingers.",
                )
            finally:
                storage.database.dispose()


if __name__ == "__main__":
    unittest.main()
