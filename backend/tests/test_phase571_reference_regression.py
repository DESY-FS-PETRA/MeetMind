from __future__ import annotations

import unittest

from app.transcription.result import TranscriptionResult, WordResult
from app.transcription.transcript_cleaner import TranscriptCleaner
from app.vocabulary.service import AdaptiveVocabularyService


class Phase571ReferenceRegressionTests(unittest.TestCase):
    def test_reference_errors_are_cleaned_without_rewriting_error_example(self) -> None:
        service = AdaptiveVocabularyService()
        meeting_id = "phase571-reference"
        service.start_meeting(meeting_id)
        service.set_slide_context(
            meeting_id,
            slide_number=5,
            slide_title="Reference evaluation",
            slide_terms=[
                "PETRA IV",
                "sinogram",
                "ASTRA Toolbox",
                "cSAXS code",
                "sCMOS detector",
                "machine learning",
                "Ollama",
                "autoencoder",
                "object retrieval",
                "dark-field correction",
            ],
            auto_match=True,
        )
        text = (
            "PETRA IV beamlines. TRA -4 beamline. "
            "The synogram uses CSX code and an SCMOS detector. "
            "We use auto encoders GANs autoencoder GANs for l learning. "
            "The object retrieve follows dark field correct. "
            "Create a llama summary. "
            "ASTRA Toolbox is not confused with ASTA football."
        )
        result = TranscriptionResult(
            text=text,
            words=tuple(WordResult(token, 0.45) for token in text.split()),
            average_confidence=0.45,
        )

        corrected, _ = service.correct_result(meeting_id, result)
        cleaned = TranscriptCleaner().clean_words(list(corrected.words), final=True)
        final_text = TranscriptCleaner.text(cleaned)

        self.assertIn("PETRA IV beamlines.", final_text)
        self.assertNotIn("TRA-4", final_text)
        self.assertIn("sinogram", final_text)
        self.assertIn("cSAXS code", final_text)
        self.assertIn("sCMOS detector", final_text)
        self.assertIn("autoencoder GANs", final_text)
        self.assertEqual(final_text.count("autoencoder GANs"), 1)
        self.assertIn("machine learning", final_text)
        self.assertIn("object retrieval", final_text)
        self.assertIn("dark-field correction", final_text)
        self.assertIn("an Ollama summary", final_text)
        self.assertIn("not confused with ASTA football", final_text)


if __name__ == "__main__":
    unittest.main()
