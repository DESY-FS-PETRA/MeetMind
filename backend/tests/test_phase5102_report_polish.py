from __future__ import annotations

import unittest

from app.schemas.summary import SlideSummary
from app.services.meeting_summary_service import MeetingSummaryService
from app.transcription.result import TranscriptionResult, WordResult
from app.transcription.scientific_validator import ScientificTranscriptValidator


class ContextualCanonicalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = ScientificTranscriptValidator()

    @staticmethod
    def _result(text: str) -> TranscriptionResult:
        words = tuple(WordResult(token, 0.55, None, None) for token in text.split())
        return TranscriptionResult(text=text, words=words, average_confidence=0.55)

    def test_rain_blocks_becomes_gray_blocks_only_in_grayscale_context(self) -> None:
        result = self._result("If I make it a grayscale map it would be some rain blocks.")
        fixed, corrections = self.validator.correct_result(result, presentation=None)
        self.assertIn("gray blocks", fixed.text.casefold())
        self.assertTrue(any(c.original.casefold().startswith("rain") for c in corrections))

        unrelated = self._result("After the rain blocks the road we stop driving.")
        untouched, _ = self.validator.correct_result(unrelated, presentation=None)
        self.assertIn("rain blocks", untouched.text.casefold())

    def test_two_and_a_half_becomes_2_5d_only_with_3d_context(self) -> None:
        result = self._result("It is not really 3D. It is two and a half.")
        fixed, corrections = self.validator.correct_result(result, presentation=None)
        self.assertIn("2.5d", fixed.text.casefold())
        self.assertTrue(any(c.replacement.casefold().startswith("2.5d") for c in corrections))

        unrelated = self._result("The measurement lasted two and a half hours.")
        untouched, _ = self.validator.correct_result(unrelated, presentation=None)
        self.assertIn("two and a half", untouched.text.casefold())


class AbstractiveSlideSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MeetingSummaryService.__new__(MeetingSummaryService)

    def test_data_generation_pipeline_is_paraphrased(self) -> None:
        spoken = (
            "So yes the problem there is currently no stereo X-ray dataset available so my goal was to generate "
            "training data by myself. I rotated my original tomograms by 90, 180 and 270 degrees and flipped it "
            "along the X axis and then cut out small sub-volumes. It turned out that this was not enough and the "
            "data was not diverse enough."
        )
        section = {
            "slide_number": 3,
            "title": "Data Generation Pipeline",
            "body_text": "rotation flipping sub-volumes",
            "notes_text": "",
            "keywords": ["X-ray", "training data"],
            "transcript": spoken,
        }
        llm = [SlideSummary(slide_number=3, title=section["title"], summary=spoken, key_terms=[])]
        result = self.service._build_slide_summaries(llm, [section])
        summary = result[0].summary
        self.assertIn("rotations", summary.casefold())
        self.assertIn("flips", summary.casefold())
        self.assertIn("data diversity", summary.casefold())
        self.assertNotIn("so yes", summary.casefold())
        self.assertLessEqual(len(summary.split()), 55)

    def test_measurement_slide_is_abstractive_and_grounded(self) -> None:
        spoken = (
            "The left is the actual measurement data and right is the simulation so you see that because the "
            "background is just zeros currently this is something."
        )
        section = {
            "slide_number": 9,
            "title": "Performance on Measurement Data",
            "body_text": "measurement data simulation",
            "notes_text": "",
            "keywords": [],
            "transcript": spoken,
        }
        result = self.service._build_slide_summaries([], [section])
        summary = result[0].summary
        self.assertIn("measurement data", summary.casefold())
        self.assertIn("simulated data", summary.casefold())
        self.assertIn("zero-valued background", summary.casefold())
        self.assertNotIn("the left is", summary.casefold())


class QAPolishTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MeetingSummaryService.__new__(MeetingSummaryService)
        self.sections = [{
            "slide_number": 6,
            "title": "Discussion",
            "body_text": "CNN performance multilayer numerical approach stereo projections",
            "keywords": ["CNN", "stereo projections"],
            "transcript": "",
        }]

    def test_performance_question_and_answer_are_polished(self) -> None:
        transcript = (
            "How well does a network perform when trained with those kind of data? "
            "The performance is quite good other than some small outliers. "
            "There are overlapping features where the network struggles."
        )
        questions, open_questions = self.service._build_discussion_questions(
            [], [], transcript, self.sections
        )
        self.assertEqual(len(questions), 1)
        self.assertEqual(
            questions[0].question,
            "How well does the network perform when trained on the synthetic data?",
        )
        self.assertEqual(questions[0].status, "answered")
        self.assertIn("performed well overall", (questions[0].answer or "").casefold())
        self.assertEqual(open_questions, [])

    def test_cnn2_question_is_canonicalized(self) -> None:
        polished = self.service._polish_question(
            "If you don't have enough info from two projections would you expect a CNN2?"
        )
        self.assertEqual(
            polished,
            "If two projections do not contain enough information, why would a CNN be expected to work?",
        )


if __name__ == "__main__":
    unittest.main()
