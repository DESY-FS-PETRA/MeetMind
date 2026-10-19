from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from app.rag.service import RAGService
from app.storage.meeting_storage import MeetingStorage


class Phase633ScientificQueryIntentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / "phase633.db"
        self.storage = MeetingStorage(f"sqlite:///{db_path.as_posix()}")
        self.storage.create_meeting("m1", "shahin 5", "2026-08-14T09:00:00+00:00")
        transcript = (
            "Shahin presented synthetic stereo X-ray data generation. "
            "Otsu segmentation and connected components were used before ASTRA Toolbox projections."
        )
        self.storage.upsert_transcript(
            "m1", transcript, segment_id="final", is_final=True, average_confidence=0.96
        )
        self.storage.complete_meeting("m1", "2026-08-14T09:30:00+00:00")
        self.storage.save_summary(
            "m1",
            {
                "summary": (
                    "Shahin presented a pipeline for generating synthetic stereo X-ray projections "
                    "for CNN training using Otsu segmentation and ASTRA Toolbox."
                ),
                "key_points": ["Otsu segmentation was used before connected-component labeling."],
                "decisions": [],
                "action_items": [],
                "discussion_questions": [],
                "open_questions": [],
                "slide_summaries": [
                    {
                        "slide_number": 2,
                        "title": "Background",
                        "summary": "Stereo X-ray imaging motivates a CNN-based multilayer separation method.",
                        "key_terms": ["stereo X-ray"],
                    },
                    {
                        "slide_number": 4,
                        "title": "Synthetic Data Generation",
                        "summary": "Synthetic volumes were segmented with Otsu before connected-component labeling.",
                        "key_terms": ["Otsu segmentation"],
                    },
                    {
                        "slide_number": 6,
                        "title": "Thank you for your attention!",
                        "summary": "The presentation concluded on this slide; the subsequent scientific discussion is captured separately in Discussion Q&A.",
                        "key_terms": [],
                    },
                ],
                "technical_terms": ["Otsu segmentation", "ASTRA Toolbox"],
                "transcription_uncertainties": [],
                "generated_at": "2026-08-14T09:31:00+00:00",
                "provider": "ollama",
                "model": "qwen3:4b-instruct",
                "transcript_segments": 1,
                "transcript_characters": len(transcript),
            },
        )
        self.prompts: list[str] = []

    def tearDown(self) -> None:
        self.storage.database.dispose()
        self.tempdir.cleanup()

    def _transport(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/tags"):
                return httpx.Response(200, json={
                    "models": [{"name": "embeddinggemma:latest"}, {"name": "qwen3:4b-instruct"}]
                })
            if request.url.path.endswith("/api/embed"):
                payload = json.loads(request.content.decode())
                values = payload.get("input") or []
                if isinstance(values, str):
                    values = [values]
                return httpx.Response(200, json={"embeddings": [[1.0, 0.2, 0.1] for _ in values]})
            if request.url.path.endswith("/api/chat"):
                prompt = json.loads(request.content.decode())["messages"][-1]["content"]
                self.prompts.append(prompt)
                if "general scientific answer has already been generated separately" in prompt:
                    return httpx.Response(200, json={"message": {"content": (
                        "From your meetings: Otsu segmentation was used in Shahin's synthetic-data pipeline [S1]."
                    )}})
                if "Answer ONLY from the meeting evidence" in prompt:
                    return httpx.Response(200, json={"message": {"content": (
                        "Shahin's talk focused on synthetic stereo X-ray projections for CNN training [S1][S2]."
                    )}})
                return httpx.Response(200, json={"message": {"content": "generic answer"}})
            return httpx.Response(404)

        return httpx.MockTransport(handler)

    def test_formula_request_after_cited_meeting_answer_is_knowledge_not_archive_only(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        history = [
            {"role": "assistant", "content": "Otsu was used in the meeting [S1]."},
        ]
        self.assertEqual(service._route_question("tell me the Otsu formula", history), "knowledge")
        self.assertEqual(service._route_question("what is the Fourier transform?", history), "knowledge")

    def test_explicit_meeting_scoped_formula_stays_strict_rag(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        self.assertEqual(
            service._route_question("What Otsu formula was discussed in the meeting?", []),
            "meeting_rag",
        )

    def test_canonical_otsu_formula_is_correct_and_renderable(self):
        answer = RAGService._canonical_scientific_answer("tell me the Otsu formula")
        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertIn("maximizes the **between-class variance**", answer)
        self.assertIn(r"\sigma_B^2(t)=\omega_0(t)\,\omega_1(t)", answer)
        self.assertIn(r"\operatorname*{arg\,max}_{t}", answer)
        self.assertIn("$$", answer)
        self.assertIn("minimizing the weighted within-class variance", answer)
        self.assertNotIn("minimizes the inter-class", answer.casefold())

    def test_canonical_otsu_explanation_does_not_claim_gaussian_mixture_requirement(self):
        answer = RAGService._canonical_scientific_answer("Tell me about Otsu segmentation")
        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertIn("maximizes between-class variance", answer)
        self.assertIn("minimizes the weighted within-class variance", answer)
        self.assertIn("does not require fitting a Gaussian-mixture model", answer)

    def test_overview_source_cleanup_removes_thank_you_slide(self):
        sources = [
            {"source_id": "S1", "source_type": "summary", "source_label": "Executive Summary", "excerpt": "Main talk overview."},
            {"source_id": "S2", "source_type": "slide_summary", "source_label": "Slide 2 · Background", "excerpt": "Stereo X-ray background."},
            {"source_id": "S3", "source_type": "slide_summary", "source_label": "Slide 6 · Thank you for your attention!", "excerpt": "The presentation concluded on this slide."},
        ]
        cleaned = RAGService._prepare_answer_sources(
            "what is the shahin's talk about?", sources, max_sources=3, drop_technical_terms=True
        )
        self.assertEqual([item["source_id"] for item in cleaned], ["S1", "S2"])

    async def test_otsu_formula_is_hybrid_and_keeps_canonical_formula(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        await service.index_all(force=True)
        history = [{"role": "assistant", "content": "Shahin used Otsu segmentation [S1]."}]
        result = await service.ask("tell me the Otsu formula", history=history, top_k=6)
        self.assertEqual(result["route"], "hybrid")
        self.assertTrue(result["meeting_evidence_used"])
        self.assertIn("General context:", result["answer"])
        self.assertIn(r"\operatorname*{arg\,max}_{t}", result["answer"])
        self.assertIn("From your meetings:", result["answer"])
        self.assertNotIn("No supporting meeting evidence", result["answer"])

    async def test_talk_overview_does_not_offer_closing_slide_as_source(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        await service.index_all(force=True)
        result = await service.ask("what is the shahin's talk about?", top_k=8)
        self.assertEqual(result["route"], "meeting_rag")
        labels = [str(item.get("source_label") or "").casefold() for item in result["sources"]]
        self.assertFalse(any("thank you" in label for label in labels))


if __name__ == "__main__":
    unittest.main()
