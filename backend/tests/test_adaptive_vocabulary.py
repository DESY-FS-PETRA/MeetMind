from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.storage.meeting_storage import MeetingStorage
from app.transcription.result import TranscriptionResult, WordResult
from app.vocabulary.service import AdaptiveVocabularyService


class AdaptiveVocabularyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = AdaptiveVocabularyService()

    def test_master_glossary_has_at_least_1000_unique_terms_and_all_categories(self) -> None:
        status = self.service.global_status()
        self.assertGreaterEqual(status["term_count"], 1000)
        self.assertEqual(status["category_count"], 12)
        canonical = [term.canonical_term.casefold() for term in self.service.terms]
        self.assertEqual(len(canonical), len(set(canonical)))

    def test_initial_context_is_bounded_and_contains_core_terms(self) -> None:
        self.service.start_meeting("meeting-core")
        context = self.service.context_for("meeting-core")
        self.assertLessEqual(len(context.active_terms), self.service.max_hotwords)
        self.assertIn("ASTRA Toolbox", context.active_terms)
        self.assertIn("near-field holography", context.active_terms)
        self.assertIsNotNone(context.hotwords)

    def test_holography_and_ptychography_topics_are_detected(self) -> None:
        self.service.start_meeting("meeting-holo")
        update = self.service.observe(
            "meeting-holo",
            "We discuss near-field holography, Fresnel propagation, phase retrieval and multi-slice ptychography. "
            "The coherent imaging experiment uses a reconstructed wavefront and propagation distance. "
            "The ptychographic reconstruction will compare probe retrieval and position refinement.",
        )
        self.assertIsNotNone(update)
        assert update is not None
        self.assertIn("holography_phase_coherence", update.categories)
        self.assertIn("ptychography_cdi", update.categories)
        self.assertIn("Fresnel propagation", update.active_terms)
        self.assertIn("multi-slice ptychography", update.active_terms)

    def test_tomography_topic_selects_astra_and_reconstruction_terms(self) -> None:
        self.service.start_meeting("meeting-tomo")
        update = self.service.observe(
            "meeting-tomo",
            "The sinogram will be reconstructed with the ASTA football package using SIRT and cone-beam geometry. "
            "We will compare filtered back projection, iterative reconstruction and center-of-rotation correction. "
            "The computed tomography data contain projection artifacts.",
        )
        self.assertIsNotNone(update)
        assert update is not None
        self.assertIn("tomography_inverse", update.categories)
        self.assertIn("ASTRA Toolbox", update.active_terms)
        self.assertIn("SIRT", update.active_terms)
        self.assertIn("filtered back projection", update.active_terms)

    def test_exact_asr_alias_is_corrected_to_canonical_term(self) -> None:
        meeting_id = "meeting-correction"
        self.service.start_meeting(meeting_id)
        result = TranscriptionResult(
            text="We used ASTA football for reconstruction.",
            words=(
                WordResult("We", 0.96, 0.0, 0.2),
                WordResult("used", 0.95, 0.2, 0.5),
                WordResult("ASTA", 0.55, 0.5, 0.8),
                WordResult("football", 0.51, 0.8, 1.2),
                WordResult("for", 0.94, 1.2, 1.4),
                WordResult("reconstruction.", 0.93, 1.4, 2.0),
            ),
            average_confidence=0.8,
        )
        corrected, update = self.service.correct_result(meeting_id, result)
        self.assertEqual(
            corrected.text,
            "We used ASTRA Toolbox for reconstruction.",
        )
        self.assertEqual(corrected.corrections[0]["replacement"], "ASTRA Toolbox")
        self.assertIsNotNone(update)

    def test_unrelated_high_confidence_words_are_not_changed(self) -> None:
        meeting_id = "meeting-safe"
        self.service.start_meeting(meeting_id)
        result = TranscriptionResult(
            text="The football match starts later.",
            words=tuple(
                WordResult(token, 0.98) for token in "The football match starts later.".split()
            ),
            average_confidence=0.98,
        )
        corrected, update = self.service.correct_result(meeting_id, result)
        self.assertEqual(corrected.text, result.text)
        self.assertIsNone(update)

    def test_general_meeting_does_not_activate_scientific_category(self) -> None:
        meeting_id = "meeting-general"
        self.service.start_meeting(meeting_id)
        update = self.service.observe(
            meeting_id,
            "I am jumping in for Philip today because he cannot attend the meeting. "
            "I will talk about the summer school, the people who attended, the castle, "
            "the accommodation and the schedule for the week.",
        )
        snapshot = update or self.service.snapshot(meeting_id)
        assert snapshot is not None
        self.assertEqual(snapshot.categories, ())
        self.assertNotIn("X-ray beam induced current", snapshot.active_terms)
        self.assertLessEqual(len(snapshot.active_terms), 24)

    def test_metalinguistic_error_example_is_not_corrected(self) -> None:
        meeting_id = "meeting-protected-example"
        self.service.start_meeting(meeting_id)
        result = TranscriptionResult(
            text="ASTRA Toolbox is not confused with ASTA football.",
            words=tuple(
                WordResult(token, 0.45 if token in {"ASTA", "football."} else 0.95)
                for token in "ASTRA Toolbox is not confused with ASTA football.".split()
            ),
            average_confidence=0.8,
        )

        corrected, update = self.service.correct_result(meeting_id, result)

        self.assertEqual(corrected.text, result.text)
        self.assertIsNone(update)

    def test_reference_scientific_aliases_are_corrected(self) -> None:
        meeting_id = "meeting-reference-aliases"
        self.service.start_meeting(meeting_id)
        self.service.set_slide_context(
            meeting_id,
            slide_number=5,
            slide_title="Tomography and ptychography",
            slide_terms=[
                "sinogram",
                "cSAXS code",
                "sCMOS detector",
                "Ollama",
                "machine learning",
            ],
            auto_match=True,
        )
        result = TranscriptionResult(
            text="The synogram uses CSX code and an SCMOS detector for l learning with llama summary.",
            words=tuple(
                WordResult(token, 0.5)
                for token in "The synogram uses CSX code and an SCMOS detector for l learning with llama summary.".split()
            ),
            average_confidence=0.5,
        )

        corrected, update = self.service.correct_result(meeting_id, result)

        self.assertIn("sinogram", corrected.text)
        self.assertIn("cSAXS code", corrected.text)
        self.assertIn("sCMOS detector", corrected.text)
        self.assertIn("machine learning", corrected.text)
        self.assertIn("Ollama summary", corrected.text)
        self.assertIsNotNone(update)


class VocabularyStorageTests(unittest.TestCase):
    def test_vocabulary_state_is_persisted_with_meeting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "vocabulary.db"
            storage = MeetingStorage(
                database_url=f"sqlite:///{database_path.as_posix()}"
            )
            try:
                storage.create_meeting(
                    "meeting-vocab",
                    "Vocabulary test",
                    "2026-07-22T00:00:00Z",
                )
                storage.save_vocabulary_state(
                    "meeting-vocab",
                    {
                        "categories": ["tomography_inverse"],
                        "category_labels": ["Tomography and inverse problems"],
                        "active_terms": ["ASTRA Toolbox", "TomoPy"],
                        "category_scores": {"tomography_inverse": 12.5},
                        "revision": 3,
                        "observed_characters": 180,
                        "correction_count": 1,
                        "is_final": True,
                        "updated_at": "2026-07-22T00:01:00Z",
                    },
                )
                details = storage.get_meeting_details("meeting-vocab")
                self.assertIsNotNone(details)
                assert details is not None
                self.assertEqual(
                    details["vocabulary"]["categories"],
                    ["tomography_inverse"],
                )
                self.assertEqual(details["vocabulary"]["correction_count"], 1)
            finally:
                storage.database.dispose()


if __name__ == "__main__":
    unittest.main()
