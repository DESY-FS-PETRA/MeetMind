from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.schemas.summary import MeetingSummaryContent
from app.services.meeting_summary_service import MeetingSummaryService
from app.storage.meeting_storage import MeetingStorage


class _StubLLM:
    async def summarize(self, **_kwargs):
        return (
            MeetingSummaryContent(
                summary="The presentation covered holography and tomography reconstruction.",
                key_points=["Two imaging workflows were discussed."],
            ),
            "ollama",
            "test-model",
        )


class SlideTranscriptAlignmentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.storage = MeetingStorage(
            database_url=f"sqlite:///{(root / 'slide-summary.db').as_posix()}"
        )
        self.storage.create_presentation(
            presentation_id="deck-summary",
            filename="deck.pptx",
            source_type="pptx",
            title="Scientific imaging",
            storage_path=str(root / "deck.pptx"),
            slides=[
                {
                    "slide_number": 1,
                    "title": "Near-field holography",
                    "body_text": "Fresnel propagation and phase retrieval",
                    "notes_text": "",
                    "keywords": ["near-field holography", "Fresnel propagation", "phase retrieval"],
                },
                {
                    "slide_number": 2,
                    "title": "Tomographic reconstruction",
                    "body_text": "ASTRA Toolbox, sinogram and SIRT",
                    "notes_text": "",
                    "keywords": ["ASTRA Toolbox", "sinogram", "SIRT"],
                },
            ],
        )
        self.storage.create_meeting(
            "meeting-summary",
            "Slide summary test",
            "2026-07-23T09:00:00Z",
        )
        self.storage.attach_presentation("meeting-summary", "deck-summary")

    def tearDown(self) -> None:
        self.storage.database.dispose()
        self.temp_dir.cleanup()

    def _populate_transcript(self) -> str:
        first = (
            "On slide 1, near-field holography uses Fresnel propagation and phase retrieval."
        )
        self.storage.upsert_transcript(
            "meeting-summary",
            first,
            segment_id="rolling",
            revision=1,
            is_final=False,
        )
        self.storage.set_active_slide(
            "meeting-summary",
            2,
            auto_match=True,
            match_score=12.0,
            source="automatic",
        )
        final = (
            first
            + " On slide 2, the sinogram is reconstructed with ASTRA Toolbox and SIRT."
        )
        words = [
            {
                "text": token,
                "probability": 0.42 if token.rstrip(".,").casefold() == "sinogram" else 0.95,
                "needs_review": token.rstrip(".,").casefold() == "sinogram",
            }
            for token in final.split()
        ]
        self.storage.upsert_transcript(
            "meeting-summary",
            final,
            segment_id="rolling",
            revision=2,
            is_final=True,
            words=words,
            average_confidence=0.9,
            low_confidence_count=1,
        )
        return final

    def test_slide_events_split_the_final_transcript(self) -> None:
        self._populate_transcript()

        sections = self.storage.build_slide_transcript_sections("meeting-summary")

        self.assertEqual([item["slide_number"] for item in sections], [1, 2])
        self.assertIn("Fresnel propagation", sections[0]["transcript"])
        self.assertIn("ASTRA Toolbox", sections[1]["transcript"])
        events = self.storage.load_slide_events("meeting-summary")
        self.assertEqual(events[0]["source"], "initial")
        self.assertEqual(events[1]["source"], "automatic")

    async def test_summary_extras_are_generated_and_persisted(self) -> None:
        self._populate_transcript()
        service = MeetingSummaryService(storage=self.storage, llm=_StubLLM())

        summary = await service.summarize("meeting-summary")

        self.assertEqual(len(summary.slide_summaries), 2)
        self.assertEqual(summary.slide_summaries[0].slide_number, 1)
        self.assertIn("ASTRA Toolbox", summary.technical_terms)
        self.assertFalse(any("sinogram" in item.casefold() for item in summary.transcription_uncertainties))

        stored = self.storage.load_summary("meeting-summary")
        assert stored is not None
        self.assertEqual(len(stored["slide_summaries"]), 2)
        self.assertIn("SIRT", stored["technical_terms"])
        details = self.storage.get_meeting_details("meeting-summary")
        assert details is not None
        self.assertEqual(len(details["summary"]["slide_summaries"]), 2)


if __name__ == "__main__":
    unittest.main()
