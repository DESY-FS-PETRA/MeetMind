from __future__ import annotations

import unittest

from app.ai.numeric_fact_validator import NumericFactValidator
from app.schemas.summary import DiscussionQuestion, SlideSummary
from app.services.meeting_summary_service import MeetingSummaryService


class NumericFactValidatorTests(unittest.TestCase):
    def test_generated_and_training_sample_counts_remain_distinct(self) -> None:
        evidence = (
            "I generated five thousand samples. "
            "For training I used 4,000 samples. "
            "We used 500 samples for validation and testing."
        )
        bad = (
            "The generated data is projected via the ASTRA Toolbox, resulting in "
            "5,000 training samples."
        )
        fixed = NumericFactValidator.repair_summary(bad, evidence)
        self.assertIn("5,000 synthetic samples", fixed)
        self.assertIn("4,000 were used for training", fixed)
        self.assertNotIn("5,000 training samples", fixed)


    def test_real_meeting_generated_of_those_and_spaced_comma_are_parsed(self) -> None:
        evidence = (
            "What I'm getting out are those projections now, I generated just for training reasons "
            "five thousand of those. For training I used 4 ,000 samples. "
            "Used 4k samples for training and 500 samples for validation and testing."
        )
        facts = NumericFactValidator.extract_facts(evidence)
        self.assertTrue(any(f.role == "generated" and f.value == 5000 for f in facts))
        self.assertTrue(any(f.role == "training" and f.value == 4000 for f in facts))
        fixed = NumericFactValidator.repair_summary(
            "The pipeline resulted in 5,000 training samples.", evidence
        )
        self.assertNotIn("5,000 training samples", fixed)
        self.assertIn("4,000 training samples", fixed)

    def test_correct_training_count_is_not_changed(self) -> None:
        evidence = "I generated 5,000 samples and used 4,000 samples for training."
        text = "The network was trained on 4,000 training samples."
        self.assertEqual(NumericFactValidator.repair_summary(text, evidence), text)


class SemanticQATests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MeetingSummaryService.__new__(MeetingSummaryService)
        self.sections = [
            {
                "slide_number": 2,
                "title": "Background",
                "body_text": "X-ray stereo experiment depth information multi-layer objects numerical approach CNN",
                "keywords": ["CNN", "depth information"],
                "transcript": "",
            }
        ]

    def test_rephrased_multiturn_question_is_resolved_and_meta_question_removed(self) -> None:
        transcript = (
            "Because you said the stereo experiment can give the depth information, right? "
            "And what's the problem for multilayer objects if you have the depth information? "
            "I don't get your question. "
            "What the problem is with the numerical approach when you have multiple layers, why it doesn't work? "
            "What's your question? "
            "You said here to solve the problem for multilayer objects. "
            "When you try to separate two layers from each other you can do this by a numerical approach. "
            "Sina has shown us already, but this approach breaks down when you go to three or four or five layers. "
            "It assumes a simple shift and from two views you don't have enough information."
        )
        questions, open_questions = self.service._build_discussion_questions(
            [], [], transcript, self.sections
        )
        self.assertFalse(any("what's your question" in q.question.casefold() for q in questions))
        relevant = [q for q in questions if "numerical approach" in q.question.casefold()]
        self.assertTrue(relevant)
        self.assertTrue(any(q.status == "answered" for q in relevant))
        self.assertTrue(any("not enough information" in (q.answer or "").casefold() or "breaks down" in (q.answer or "").casefold() for q in relevant))
        self.assertFalse(any("numerical approach" in q.casefold() for q in open_questions))

    def test_immediate_i_dont_know_remains_unresolved(self) -> None:
        transcript = (
            "In the experiments from Sina how does the distance between the layers compare to the distance in a microchip? "
            "I don't know, to be honest."
        )
        questions, open_questions = self.service._build_discussion_questions(
            [], [], transcript, self.sections
        )
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0].status, "unresolved")
        self.assertTrue(open_questions)

    def test_confirmation_questions_are_not_promoted_to_scientific_qna(self) -> None:
        transcript = (
            "So this one will have label one and this one label two, right? "
            "It's not really 3D, right? It's two and a half. "
            "Who's next up?"
        )
        questions, open_questions = self.service._build_discussion_questions(
            [], [], transcript, self.sections
        )
        self.assertEqual(questions, [])
        self.assertEqual(open_questions, [])


class SlideSummaryPrecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MeetingSummaryService.__new__(MeetingSummaryService)

    def test_long_copied_slide_text_is_compacted(self) -> None:
        spoken = (
            "I generated 5,000 samples and split them into training test and validation set. "
            "For training I used 4,000 samples. I cropped them down to 512x512 pixels to fit on a GPU. "
            "The ground truth is on the left and the prediction is on the right. "
            "The performance is quite good other than small outliers where overlapping features are difficult. "
            "I do not want to go too much into detail about the network architecture."
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
            summary=spoken + " " + spoken,
            key_terms=["CNN", "GPU"],
        )]
        result = self.service._build_slide_summaries(llm, [section])
        self.assertEqual(len(result), 1)
        self.assertLessEqual(len(result[0].summary.split()), 65)
        self.assertIn("4,000", result[0].summary)
        self.assertIn("512x512", result[0].summary)
        self.assertNotIn(spoken + " " + spoken, result[0].summary)

    def test_post_talk_chatter_removed_from_last_slide(self) -> None:
        section = {
            "slide_number": 9,
            "title": "Performance on Measurement Data",
            "body_text": "measurement data simulation",
            "notes_text": "",
            "keywords": [],
            "transcript": (
                "The left is the actual measurement data and the right is the simulation. "
                "The background is currently zero in the simulation. Who's next up?"
            ),
        }
        result = self.service._build_slide_summaries([], [section])
        self.assertEqual(len(result), 1)
        self.assertNotIn("next up", result[0].summary.casefold())
        self.assertIn("measurement data", result[0].summary.casefold())


class ScientificReviewPrecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MeetingSummaryService.__new__(MeetingSummaryService)

    def test_generic_words_removed_and_suspicious_acronym_digit_added(self) -> None:
        transcript = "Would you expect a CNN2? The D-layer is difficult and vice-versa has low confidence."
        items = [{
            "is_final": True,
            "words": [
                {"text": "has", "probability": 0.05, "needs_review": True},
                {"text": "vice-versa", "probability": 0.23, "needs_review": True},
                {"text": "D-layer", "probability": 0.20, "needs_review": True},
                {"text": "CNN2", "probability": 0.80, "needs_review": False},
            ],
        }]
        result = self.service._build_uncertainties(
            [], transcript, items, ["CNN"], []
        )
        self.assertTrue(any("D-layer" in item for item in result))
        self.assertTrue(any('"CNN2"' in item and '"CNN"' in item for item in result))
        self.assertFalse(any(item.casefold().startswith("has ") or item.casefold() == "has" for item in result))
        self.assertFalse(any("vice-versa" in item.casefold() for item in result))


if __name__ == "__main__":
    unittest.main()
