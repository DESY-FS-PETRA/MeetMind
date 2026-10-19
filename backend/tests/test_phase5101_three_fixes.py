from __future__ import annotations

import unittest

from app.schemas.summary import SlideSummary
from app.services.meeting_summary_service import MeetingSummaryService


class Phase5101ReviewQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MeetingSummaryService.__new__(MeetingSummaryService)

    def test_valid_uncommon_terms_are_not_reviewed_without_asr_evidence(self) -> None:
        transcript = (
            "The microchip was measured at PSI. She had a zone plate and gold particles on top. "
            "It is not really 3D; it is two and a half. The D-layer bond is difficult. "
            "Would you expect a CNN2?"
        )
        transcript_items = [{
            "is_final": True,
            "words": [
                {"text": "PSI", "probability": 0.92, "needs_review": False},
                {"text": "zone", "probability": 0.89, "needs_review": False},
                {"text": "gold", "probability": 0.91, "needs_review": False},
                {"text": "D-layer", "probability": 0.20, "needs_review": True},
                {"text": "CNN2", "probability": 0.80, "needs_review": False},
            ],
        }]
        llm_items = ["PSI", "zone plate", "gold particles", "2 and a half", "D-layer bond"]
        result = self.service._build_uncertainties(
            llm_items,
            transcript,
            transcript_items,
            ["CNN", "zone plate"],
            [],
        )
        joined = " | ".join(result)
        self.assertNotIn("PSI", joined)
        self.assertNotIn("gold particles", joined)
        self.assertNotIn("2 and a half", joined)
        self.assertIn("D-layer", joined)
        self.assertIn('"CNN2"', joined)
        self.assertIn('"CNN"', joined)


class Phase5101SlideSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MeetingSummaryService.__new__(MeetingSummaryService)

    def test_copied_slide_summary_is_compacted_and_neutralized(self) -> None:
        spoken = (
            "I generated 5,000 samples and split them into training test and validation set. "
            "For training I used 4,000 samples. I cropped them down to 512x512 pixels to fit on a GPU. "
            "The ground truth is on the left and the prediction is on the right. "
            "The performance is quite good other than small outliers where overlapping features are difficult."
        )
        section = {
            "slide_number": 5,
            "title": "CNN Performance on Synthetic Data",
            "body_text": "Used 4k samples for training and 500 samples for validation and testing. Stereo image size 512x512.",
            "notes_text": "",
            "keywords": ["CNN", "training data", "ground truth", "GPU"],
            "transcript": spoken,
        }
        llm = [SlideSummary(
            slide_number=5,
            title=section["title"],
            summary=spoken,
            key_terms=["CNN", "GPU"],
        )]
        result = self.service._build_slide_summaries(llm, [section])
        self.assertEqual(len(result), 1)
        summary = result[0].summary
        self.assertLessEqual(len(summary.split()), 55)
        self.assertFalse(summary.casefold().startswith("i generated"))
        self.assertNotEqual(summary, spoken)
        self.assertIn("5,000", summary)
        self.assertIn("4,000", summary)

    def test_thank_you_slide_is_boundary_not_q_and_a_bucket(self) -> None:
        section = {
            "slide_number": 6,
            "title": "Thank you for your attention!",
            "body_text": "Are there any questions?",
            "notes_text": "",
            "keywords": [],
            "transcript": (
                "Thanks for your attention. Because you said the stereo experiment can give depth information, right? "
                "What is the problem with the numerical approach for multilayer objects?"
            ),
        }
        llm = [SlideSummary(
            slide_number=6,
            title=section["title"],
            summary=section["transcript"],
            key_terms=["stereo experiment"],
        )]
        result = self.service._build_slide_summaries(llm, [section])
        self.assertEqual(len(result), 1)
        summary = result[0].summary
        self.assertIn("presentation concluded", summary.casefold())
        self.assertIn("discussion q&a", summary.casefold())
        self.assertNotIn("multilayer", summary.casefold())
        self.assertEqual(result[0].key_terms, [])


if __name__ == "__main__":
    unittest.main()
