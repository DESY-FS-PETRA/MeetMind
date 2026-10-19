from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.storage.meeting_storage import MeetingStorage


class DatabaseMeetingStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "history.db"
        self.storage = MeetingStorage(database_url=f"sqlite:///{database_path.as_posix()}")
        self.meeting_id = "meeting-1"
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.storage.create_meeting(
            self.meeting_id,
            "Database design review",
            self.started_at,
        )

    def tearDown(self) -> None:
        self.storage.database.dispose()
        self.temp_dir.cleanup()

    def test_meeting_transcript_summary_and_details(self) -> None:
        self.storage.upsert_transcript(
            self.meeting_id,
            "We selected SQLite for local development.",
            segment_id="rolling",
            event_id="event-1",
            created_at=self.started_at,
            revision=1,
            is_final=True,
            words=[
                {
                    "text": "SQLite",
                    "probability": 0.91,
                    "needs_review": False,
                }
            ],
            average_confidence=0.91,
            low_confidence_count=0,
        )
        self.storage.complete_meeting(self.meeting_id, self.started_at)
        self.storage.save_summary(
            self.meeting_id,
            {
                "meeting_id": self.meeting_id,
                "summary": "The team selected SQLite for local development.",
                "key_points": ["Database persistence was reviewed."],
                "decisions": ["Use SQLite first."],
                "action_items": [
                    {
                        "task": "Add PostgreSQL configuration",
                        "owner": "Vahid",
                        "deadline": None,
                    }
                ],
                "open_questions": [],
                "generated_at": self.started_at,
                "provider": "local",
                "model": None,
                "transcript_segments": 1,
                "transcript_characters": 41,
            },
        )

        details = self.storage.get_meeting_details(self.meeting_id)
        self.assertIsNotNone(details)
        assert details is not None
        self.assertEqual(details["status"], "completed")
        self.assertEqual(details["transcript_count"], 1)
        self.assertAlmostEqual(details["average_confidence"], 0.91)
        self.assertEqual(details["summary"]["decisions"], ["Use SQLite first."])
        self.assertEqual(
            details["summary"]["action_items"][0]["owner"],
            "Vahid",
        )

    def test_transcript_upsert_keeps_latest_revision(self) -> None:
        self.storage.upsert_transcript(
            self.meeting_id,
            "Partial text",
            segment_id="rolling",
            revision=1,
        )
        self.storage.upsert_transcript(
            self.meeting_id,
            "Final corrected text",
            segment_id="rolling",
            revision=2,
            is_final=True,
        )
        self.storage.upsert_transcript(
            self.meeting_id,
            "Stale text",
            segment_id="rolling",
            revision=1,
        )

        transcript = self.storage.load_transcript(self.meeting_id)
        self.assertEqual(len(transcript), 1)
        self.assertEqual(transcript[0]["text"], "Final corrected text")
        self.assertTrue(transcript[0]["is_final"])

    def test_list_search_update_and_delete(self) -> None:
        self.storage.upsert_transcript(
            self.meeting_id,
            "A discussion about vector databases and RAG.",
            segment_id="rolling",
            revision=1,
            is_final=True,
        )
        self.storage.complete_meeting(self.meeting_id, self.started_at)

        result = self.storage.list_meetings(search="vector")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["meeting_id"], self.meeting_id)

        updated = self.storage.update_meeting(
            self.meeting_id,
            title="RAG architecture review",
        )
        self.assertEqual(updated["title"], "RAG architecture review")

        self.assertTrue(self.storage.delete_meeting(self.meeting_id))
        self.assertIsNone(self.storage.get_meeting(self.meeting_id))
        self.assertEqual(self.storage.load_transcript(self.meeting_id), [])


if __name__ == "__main__":
    unittest.main()


class LegacyJsonMigrationTests(unittest.TestCase):
    def test_legacy_json_folder_can_be_imported(self) -> None:
        import json
        from app.database.migrate_json import migrate_directory

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "legacy"
            meeting_folder = legacy / "old-meeting"
            meeting_folder.mkdir(parents=True)
            self_iso = datetime.now(timezone.utc).isoformat()
            (meeting_folder / "meeting.json").write_text(
                json.dumps(
                    {
                        "meeting_id": "old-meeting",
                        "title": "Imported meeting",
                        "status": "completed",
                        "start_time": self_iso,
                        "end_time": self_iso,
                    }
                ),
                encoding="utf-8",
            )
            (meeting_folder / "transcript.json").write_text(
                json.dumps(
                    [
                        {
                            "segment_id": "rolling",
                            "revision": 2,
                            "is_final": True,
                            "time": self_iso,
                            "text": "Legacy transcript imported successfully.",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            database_path = root / "migration.db"
            database_url = f"sqlite:///{database_path.as_posix()}"
            result = migrate_directory(legacy, database_url=database_url)
            self.assertEqual(result["imported"], 1)

            storage = MeetingStorage(database_url=database_url)
            try:
                details = storage.get_meeting_details("old-meeting")
                self.assertIsNotNone(details)
                assert details is not None
                self.assertEqual(details["status"], "completed")
                self.assertIn("Legacy transcript", details["final_transcript"])
            finally:
                storage.database.dispose()
