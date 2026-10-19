from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from app.rag.service import RAGService
from app.storage.meeting_storage import MeetingStorage


class Phase643ScientificTaxonomyPolishTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / "phase643.db"
        self.storage = MeetingStorage(f"sqlite:///{db_path.as_posix()}")
        self._meeting(
            "shahin",
            "shahin 5",
            "Synthetic stereo X-ray projections for CNN training used Otsu segmentation, connected components, random reassembly, and ASTRA Toolbox.",
        )
        self._meeting(
            "holo",
            "[DEMO] Near-Field Holography Reconstruction",
            "Near-field X-ray holography used Fresnel propagation, phase retrieval, denoising, SSIM, PSNR and FRC for reconstruction validation.",
        )

    def tearDown(self) -> None:
        self.storage.database.dispose()
        self.tempdir.cleanup()

    def _meeting(self, meeting_id: str, title: str, summary: str) -> None:
        self.storage.create_meeting(meeting_id, title, "2026-08-14T10:00:00+00:00")
        self.storage.upsert_transcript(meeting_id, summary, segment_id="final", is_final=True)
        self.storage.complete_meeting(meeting_id, "2026-08-14T10:30:00+00:00")
        self.storage.save_summary(
            meeting_id,
            {
                "summary": summary,
                "key_points": [summary],
                "decisions": [],
                "action_items": [],
                "discussion_questions": [],
                "open_questions": [],
                "slide_summaries": [],
                "technical_terms": [],
                "transcription_uncertainties": [],
                "generated_at": "2026-08-14T10:31:00+00:00",
                "provider": "test",
                "model": None,
                "transcript_segments": 1,
                "transcript_characters": len(summary),
            },
        )

    @staticmethod
    def _transport() -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/tags"):
                return httpx.Response(200, json={"models": [{"name": "embeddinggemma:latest"}, {"name": "qwen3:4b-instruct"}]})
            if request.url.path.endswith("/api/embed"):
                payload = json.loads(request.content.decode("utf-8"))
                inputs = payload.get("input") or []
                if isinstance(inputs, str):
                    inputs = [inputs]
                vectors = []
                for item in inputs:
                    lower = item.casefold()
                    vectors.append([
                        1.0 if any(k in lower for k in ("otsu", "astra", "cnn", "stereo")) else 0.2,
                        1.0 if any(k in lower for k in ("phase retrieval", "fresnel", "frc", "holograph")) else 0.2,
                        0.6 if "x-ray" in lower else 0.1,
                    ])
                return httpx.Response(200, json={"embeddings": vectors})
            if request.url.path.endswith("/api/chat"):
                # The method catalogue path should not depend on this prose.
                return httpx.Response(200, json={"message": {"content": "No common methods were found."}})
            return httpx.Response(404)
        return httpx.MockTransport(handler)

    def test_method_catalog_query_is_union_taxonomy(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        query = "What image-processing or reconstruction methods were discussed across meetings?"
        operation = service._cross_meeting_operation(query)
        self.assertEqual(operation, "union")
        self.assertTrue(service._is_cross_meeting_method_catalog_query(query, operation))

    async def test_method_catalog_separates_methods_data_generation_and_metrics(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        result = await service.ask(
            "What image-processing or reconstruction methods were discussed across meetings?",
            top_k=8,
        )
        self.assertEqual(result["cross_meeting_operation"], "union")
        self.assertEqual(set(result["meetings_used"]), {
            "shahin 5", "[DEMO] Near-Field Holography Reconstruction"
        })
        answer = result["answer"]
        self.assertIn("Image processing / segmentation", answer)
        self.assertIn("Otsu segmentation", answer)
        self.assertIn("Connected-component labeling", answer)
        self.assertIn("Synthetic-data / projection generation", answer)
        self.assertIn("ASTRA Toolbox projection generation", answer)
        self.assertIn("Reconstruction / image formation", answer)
        self.assertIn("Phase retrieval", answer)
        self.assertIn("Evaluation metrics", answer)
        self.assertIn("SSIM", answer)
        self.assertIn("FRC", answer)
        self.assertNotIn("No common methods", answer)

    def test_canonicalizer_repairs_otsu_and_acronym_spelling(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        text = "Ots- segmentation and Astra Toolbox were used. Ssim, Psnr and Frc were reported."
        cleaned = service._canonicalize_answer_terms(text)
        self.assertIn("Otsu segmentation", cleaned)
        self.assertIn("ASTRA Toolbox", cleaned)
        self.assertIn("SSIM", cleaned)
        self.assertIn("PSNR", cleaned)
        self.assertIn("FRC", cleaned)

    def test_comparison_heading_is_labeled_as_inference(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        answer = "**Comparison**: Both meetings involve X-ray imaging [S1][S2]."
        labeled = service._label_comparison_inference(answer)
        self.assertIn("Evidence-based comparison (MeetMind inference)", labeled)
        self.assertNotIn("**Comparison**", labeled)


if __name__ == "__main__":
    unittest.main()
