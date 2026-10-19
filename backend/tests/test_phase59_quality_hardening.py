from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.presentation.offline_alignment import OfflineSlideAligner
from app.schemas.summary import ActionItem, DiscussionQuestion
from app.services.meeting_summary_service import MeetingSummaryService
from app.storage.meeting_storage import MeetingStorage
from app.transcription.result import TranscriptionResult, WordResult
from app.transcription.scientific_validator import ScientificTranscriptValidator


class ScientificGroundingTests(unittest.TestCase):
    def test_real_meeting_style_asr_errors_are_corrected_before_summary(self) -> None:
        presentation = {
            "slides": [
                {
                    "slide_number": 2,
                    "title": "Background",
                    "body_text": (
                        "Sina conducted X-ray stereo experiment. "
                        "Use 2 X-rays to illuminate sample at the same time."
                    ),
                    "notes_text": "",
                    "keywords": ["X-ray"],
                },
                {
                    "slide_number": 3,
                    "title": "Data Generation Pipeline",
                    "body_text": "Try to synthetically generate data",
                    "notes_text": "",
                    "keywords": ["data augmentation"],
                },
            ]
        }
        text = (
            "SINA conducted X-ray serial experiments and we eliminate a sample. "
            "The next step is to sensitively generate data using UTSU segmentation "
            "and connect components. CINA showed the experiment."
        )
        result = TranscriptionResult(
            text=text,
            words=tuple(WordResult(token, 0.25) for token in text.split()),
            average_confidence=0.25,
        )
        corrected, notes = ScientificTranscriptValidator().correct_result(
            result, presentation=presentation
        )
        self.assertIn("Sina conducted X-ray stereo experiment", corrected.text)
        self.assertIn("illuminate a sample", corrected.text)
        self.assertIn("synthetically generate", corrected.text)
        self.assertIn("Otsu segmentation", corrected.text)
        self.assertIn("connected components", corrected.text)
        self.assertIn("Sina showed", corrected.text)
        self.assertTrue(any(item.requires_review for item in notes if "Otsu" in item.replacement))


class OfflineGlobalAlignmentTests(unittest.TestCase):
    def test_setup_chatter_is_excluded_and_ordered_scientific_slides_advance(self) -> None:
        slides = [
            {"slide_number": 1, "title": "From Tomogram to Synthetic Dataset", "body_text": "stereo projections CNN", "notes_text": "", "keywords": ["CNN"]},
            {"slide_number": 2, "title": "Background", "body_text": "X-ray stereo experiment depth information multi-layer CNN", "notes_text": "", "keywords": ["multi-layer"]},
            {"slide_number": 3, "title": "Data Generation Pipeline", "body_text": "data augmentation subvolumes randomly rearrange components synthetically generate data", "notes_text": "", "keywords": ["data augmentation"]},
            {"slide_number": 4, "title": "Synthetic Data Generation", "body_text": "<number>", "notes_text": "", "keywords": []},
            {"slide_number": 5, "title": "CNN Performance on Synthetic Data", "body_text": "Used 4k samples for training Stereo image size 512x512", "notes_text": "", "keywords": ["CNN"]},
            {"slide_number": 6, "title": "Thank you for your attention!", "body_text": "Are there any questions?", "notes_text": "", "keywords": []},
        ]
        transcript = (
            "My Zoom is not working. Should I share the whole screen?\n"
            "I am giving a short update from tomogram to synthetic dataset, a pipeline to generate stereo projections to train a CNN.\n"
            "For the background, the X-ray stereo experiment provides depth information for multi-layer objects.\n"
            "There is no stereo X-ray dataset, so I started with data augmentation and subvolumes.\n"
            "I then randomly rearranged the components of the microchip and segmented individual layers.\n"
            "I generated 5000 samples. I used 4k samples for training and cropped the stereo images to 512x512.\n"
            "The network performance is quite good. Thanks for your attention. Are there any questions?"
        )
        boundaries = OfflineSlideAligner().align(transcript, {"slides": slides})
        numbers = [item.slide_number for item in boundaries]
        self.assertEqual(numbers, [1, 2, 3, 4, 5, 6])
        self.assertGreater(boundaries[0].offset, transcript.find("Zoom"))
        self.assertGreaterEqual(boundaries[5].offset, transcript.find("Thanks for your attention"))

    def test_appendix_alignment_does_not_stall_after_early_text_heavy_slides(self) -> None:
        slides = [
            {"slide_number": 1, "title": "From Tomogram to Synthetic Dataset", "body_text": "stereo projections CNN", "notes_text": "", "keywords": ["CNN"]},
            {"slide_number": 2, "title": "Background", "body_text": "Sina conducted X-ray stereo experiment depth information multi-layer CNN", "notes_text": "", "keywords": ["multi-layer"]},
            {"slide_number": 3, "title": "Data Generation Pipeline", "body_text": "no stereo X-ray dataset data augmentation subvolumes randomly rearrange components", "notes_text": "", "keywords": ["data augmentation", "x-ray"]},
            {"slide_number": 4, "title": "Synthetic Data Generation", "body_text": "<number>", "notes_text": "", "keywords": []},
            {"slide_number": 5, "title": "CNN Performance on Synthetic Data", "body_text": "Used 4k samples for training and 500 samples for validation and testing Stereo image size 512x512", "notes_text": "", "keywords": ["CNN"]},
            {"slide_number": 6, "title": "Thank you for your attention!", "body_text": "Are there any questions?", "notes_text": "", "keywords": []},
            {"slide_number": 7, "title": "Data Distributions", "body_text": "<number>", "notes_text": "", "keywords": []},
            {"slide_number": 8, "title": "CNN Performance Metrics", "body_text": "<number>", "notes_text": "", "keywords": ["CNN"]},
            {"slide_number": 9, "title": "Performance on Measurement Data", "body_text": "<number>", "notes_text": "", "keywords": []},
        ]
        transcript = (
            "Zoom is not working and I need to share the screen. "
            "I am giving a short update from tomogram to synthetic dataset, a pipeline to generate stereo projections to train a CNN. "
            "Sina conducted an X-ray stereo experiment and the shift between projections encodes depth information. "
            "There is no stereo X-ray dataset, so I used data augmentation and subvolumes. "
            "Then I randomly rearranged the components and synthetically generated the volumes. "
            "I generated five thousand samples and used 4,000 samples for training with 500 for validation and testing. "
            "The stereo image size is 512x512 and the network performance is quite good. "
            "Thanks for your attention. Are there any questions? "
            "We discuss why the numerical approach is under-determined and the connections between layers. "
            "One more thing: these are the distributions of the components, but background distributions are not implemented. "
            "The left is the actual measurement data and the right is the simulation."
        )
        boundaries = OfflineSlideAligner().align(transcript, {"slides": slides})
        numbers = [item.slide_number for item in boundaries]
        self.assertIn(4, numbers)
        self.assertIn(5, numbers)
        self.assertIn(6, numbers)
        self.assertIn(7, numbers)
        self.assertIn(9, numbers)
        self.assertLess(numbers.index(6), numbers.index(7))
        self.assertGreaterEqual(
            next(item.offset for item in boundaries if item.slide_number == 6),
            transcript.find("Thanks for your attention"),
        )


class IntelligenceValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MeetingSummaryService.__new__(MeetingSummaryService)

    def test_false_positive_presentation_actions_are_removed(self) -> None:
        transcript = (
            "Normally should be fine. I will finish it just one more thing to say. "
            "Shahin will implement the background distribution next week."
        )
        items = [
            ActionItem(task="Be fine.", owner="Normally"),
            ActionItem(task="Finish it just one more thing to say.", owner="I"),
            ActionItem(task="Implement the background distribution.", owner="Shahin", deadline="next week"),
        ]
        valid = self.service._validate_action_items(items, transcript)
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0].owner, "Shahin")

    def test_answered_question_is_removed_from_open_questions(self) -> None:
        transcript = (
            "What is the problem with the numerical approach when you have multiple layers? "
            "It assumes a simple shift. It breaks down because two projections do not provide enough information. "
            "How does the distance between layers compare to the experiment? I don't know, to be honest."
        )
        sections = [
            {
                "slide_number": 2,
                "title": "Background",
                "body_text": "numerical approach multi-layer objects depth information",
                "keywords": ["multi-layer"],
                "transcript": transcript,
            }
        ]
        llm_items = [
            DiscussionQuestion(
                question="Why does the numerical approach break down for multilayer objects?",
                status="unresolved",
            )
        ]
        questions, open_items = self.service._build_discussion_questions(
            llm_items,
            [
                "Why does the numerical approach break down for multilayer objects?",
                "How does the distance between layers compare to the experiment?",
            ],
            transcript,
            sections,
        )
        answered = [item for item in questions if item.status == "answered"]
        unresolved = [item for item in questions if item.status == "unresolved"]
        self.assertTrue(any("numerical approach" in item.question.casefold() for item in answered))
        self.assertTrue(any("distance between layers" in item.question.casefold() for item in unresolved))
        self.assertFalse(any("numerical approach" in item.casefold() for item in open_items))
        self.assertTrue(any("distance between layers" in item.casefold() for item in open_items))

    def test_scientific_review_queue_ignores_ordinary_low_confidence_words(self) -> None:
        transcript = "The Otsu segmentation is used with ASTRA Toolbox."
        sections = [
            {
                "slide_number": 4,
                "title": "Synthetic Data Generation",
                "body_text": "",
                "keywords": ["ASTRA Toolbox"],
                "transcript": transcript,
            }
        ]
        transcript_items = [
            {
                "is_final": True,
                "words": [
                    {"text": "because", "probability": 0.05, "needs_review": True},
                    {"text": "today", "probability": 0.02, "needs_review": True},
                    {
                        "text": "Otsu",
                        "probability": 0.25,
                        "needs_review": True,
                        "scientific_corrections": [
                            {
                                "original": "UTSU segmentation",
                                "replacement": "Otsu segmentation",
                                "source": "domain",
                                "requires_review": True,
                            }
                        ],
                    },
                    {"text": "ASTRA", "probability": 0.09, "needs_review": False, "context_confirmed": True},
                ],
            }
        ]
        result = self.service._build_uncertainties(
            ["I don't know why it looks so weird"],
            transcript,
            transcript_items,
            ["Otsu segmentation", "ASTRA Toolbox"],
            sections,
        )
        self.assertEqual(result, ['Review correction: "UTSU segmentation" → "Otsu segmentation"'])

    def test_technical_terms_are_canonicalized_before_storage(self) -> None:
        transcript = (
            "The X-ray stereo experiment uses Otsu segmentation and connected components. "
            "Synthetic projections are generated with ASTRA Toolbox."
        )
        terms = self.service._build_technical_terms(
            ["X-ray serial experiments", "UTSU segmentation", "connect components", "astra toolbox"],
            transcript,
            [{
                "slide_number": 2,
                "title": "Background",
                "body_text": "X-ray stereo experiment",
                "keywords": ["ASTRA Toolbox"],
                "transcript": transcript,
            }],
        )
        self.assertIn("X-ray stereo experiment", terms)
        self.assertIn("Otsu segmentation", terms)
        self.assertIn("connected components", terms)
        self.assertIn("ASTRA Toolbox", terms)
        self.assertNotIn("X-ray serial experiments", terms)
        self.assertNotIn("UTSU segmentation", terms)
        self.assertNotIn("connect components", terms)


class SummaryExtrasCompatibilityTests(unittest.TestCase):
    def test_discussion_questions_are_persisted_in_summary_extras(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = MeetingStorage(
                database_url=f"sqlite:///{(Path(directory) / 'db.sqlite').as_posix()}"
            )
            storage.create_meeting("m", "Test", "2026-08-10T10:00:00Z")
            storage.save_summary(
                "m",
                {
                    "summary": "Test",
                    "key_points": [],
                    "decisions": [],
                    "action_items": [],
                    "open_questions": [],
                    "discussion_questions": [
                        {"question": "Why?", "status": "answered", "answer": "Because."}
                    ],
                    "generated_at": "2026-08-10T10:01:00Z",
                    "provider": "test",
                    "model": None,
                    "transcript_segments": 0,
                    "transcript_characters": 0,
                },
            )
            loaded = storage.load_summary("m")
            self.assertEqual(loaded["discussion_questions"][0]["status"], "answered")
            storage.database.dispose()


if __name__ == "__main__":
    unittest.main()
