from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from app.rag.service import RAGService
from app.storage.meeting_storage import MeetingStorage


class Phase641CrossMeetingGroundingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / "phase641.db"
        self.storage = MeetingStorage(f"sqlite:///{db_path.as_posix()}")
        self._meeting(
            "shahin",
            "shahin 5",
            "The talk presented synthetic stereo X-ray projection generation for CNN training using Otsu segmentation and ASTRA Toolbox.",
            "The talk focused on a pipeline for synthetic stereo X-ray projections for CNN training using Otsu segmentation, connected components, and ASTRA Toolbox.",
            open_questions=["How does the distance between layers compare with the layer spacing in a microchip?"],
            discussion_questions=[
                {
                    "question": "In Sina's experiments, how does the distance between layers compare with the layer spacing in a microchip?",
                    "answer": "",
                    "status": "unresolved",
                },
                {
                    "question": "How well does the network perform when trained on synthetic data?",
                    "answer": "The network performed well overall.",
                    "status": "answered",
                },
            ],
        )
        self._meeting(
            "holo",
            "[DEMO] Near-Field Holography Reconstruction",
            "The demo reviewed near-field X-ray holography, Fresnel propagation, phase retrieval, SSIM, PSNR and FRC.",
            "The demo focused on near-field X-ray holography, Fresnel propagation, phase retrieval, and reconstruction validation with SSIM, PSNR, and FRC.",
            open_questions=["Does denoising preserve fine phase gradients and high spatial frequencies in the reconstruction?"],
            discussion_questions=[{
                "question": "Can global similarity remain high while fine phase gradients are degraded?",
                "answer": "FRC and local phase analysis were proposed, but the issue was not resolved.",
                "status": "unresolved",
            }],
        )

    def tearDown(self) -> None:
        self.storage.database.dispose()
        self.tempdir.cleanup()

    def _meeting(self, meeting_id, title, transcript, summary, *, open_questions, discussion_questions):
        self.storage.create_meeting(meeting_id, title, "2026-08-14T10:00:00+00:00")
        self.storage.upsert_transcript(meeting_id, transcript, segment_id="final", is_final=True)
        self.storage.complete_meeting(meeting_id, "2026-08-14T10:30:00+00:00")
        self.storage.save_summary(
            meeting_id,
            {
                "summary": summary,
                "key_points": [summary],
                "decisions": [],
                "action_items": [],
                "discussion_questions": discussion_questions,
                "open_questions": open_questions,
                "slide_summaries": [],
                "technical_terms": [],
                "transcription_uncertainties": [],
                "generated_at": "2026-08-14T10:31:00+00:00",
                "provider": "test",
                "model": None,
                "transcript_segments": 1,
                "transcript_characters": len(transcript),
            },
        )

    @staticmethod
    def _transport(answer_text: str | None = None) -> httpx.MockTransport:
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
                        1.0 if any(k in lower for k in ("shahin", "stereo", "otsu", "astra", "cnn")) else 0.15,
                        1.0 if any(k in lower for k in ("holograph", "fresnel", "phase retrieval", "frc", "denoising")) else 0.15,
                        0.6 if "x-ray" in lower else 0.1,
                    ])
                return httpx.Response(200, json={"embeddings": vectors})
            if request.url.path.endswith("/api/chat"):
                content = answer_text or (
                    "- Shahin's meeting focused on synthetic stereo X-ray data generation [S2].\n"
                    "- The holography demo meeting focused on phase retrieval and FRC [S1].\n"
                    "- Both meetings discussed image metrics and reconstruction validation [S1][S2].\n"
                    "No supporting meeting evidence was found that directly compares the two meetings."
                )
                return httpx.Response(200, json={"message": {"content": content}})
            return httpx.Response(404)
        return httpx.MockTransport(handler)

    async def test_named_comparison_is_cross_meeting_synthesis(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        query = "Compare Shahin's meeting with the holography demo meeting."
        self.assertTrue(service._is_cross_meeting_query(query))
        self.assertTrue(service._is_cross_meeting_synthesis_query(query))
        result = await service.search(query, top_k=6)
        self.assertEqual(set(result["meetings_retrieved"]), {"shahin 5", "[DEMO] Near-Field Holography Reconstruction"})
        self.assertEqual({item["source_type"] for item in result["results"][:2]}, {"summary"})

    async def test_wrong_meeting_citations_are_rebound_and_fake_overlap_is_removed(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        answer = await service.ask("Compare Shahin's meeting with the holography demo meeting.", top_k=6)
        self.assertTrue(answer["cross_meeting"])
        self.assertEqual(set(answer["meetings_used"]), {"shahin 5", "[DEMO] Near-Field Holography Reconstruction"})
        self.assertNotIn("Both meetings discussed image metrics", answer["answer"])
        self.assertNotIn("No supporting meeting evidence", answer["answer"])
        # After citation repair + renumbering, the first meeting-named claim must
        # point to Shahin and the holography claim to the demo source.
        source_by_id = {item["source_id"]: item for item in answer["sources"]}
        self.assertEqual(source_by_id["S1"]["meeting_title"], "shahin 5")
        self.assertEqual(source_by_id["S2"]["meeting_title"], "[DEMO] Near-Field Holography Reconstruction")

    async def test_unresolved_questions_deduplicate_open_question_and_qna(self):
        service = RAGService(storage=self.storage, http_transport=self._transport(
            "- Shahin has one unresolved layer-spacing question [S1].\n"
            "- The holography demo has one unresolved fine-phase-gradient question [S2]."
        ))
        search = await service.search("Summarize the unresolved questions across all meetings.", top_k=8)
        prepared = service._prepare_answer_sources(
            "Summarize the unresolved questions across all meetings.",
            list(search["results"]),
            max_sources=6,
            drop_technical_terms=True,
        )
        titles = [item["meeting_title"] for item in prepared]
        self.assertEqual(titles.count("shahin 5"), 1)
        self.assertEqual(titles.count("[DEMO] Near-Field Holography Reconstruction"), 1)
        self.assertTrue(all(item["source_type"] in {"open_question", "discussion_qa"} for item in prepared))

    def test_contradictory_comparison_footer_is_removed_only_when_grounded(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        grounded = "Shahin differs from the demo [S1][S2].\nNo supporting meeting evidence was found that directly compares the two meetings."
        cleaned = service._strip_contradictory_cross_meeting_footer(grounded)
        self.assertIn("Shahin differs", cleaned)
        self.assertNotIn("No supporting meeting evidence", cleaned)
        ungrounded = "No supporting meeting evidence was found that directly compares the two meetings."
        self.assertEqual(service._strip_contradictory_cross_meeting_footer(ungrounded), ungrounded)

    def test_uncited_cross_meeting_bullets_are_grounded_or_removed(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        sources = [
            {
                "source_id": "S1", "meeting_id": "shahin", "meeting_title": "shahin 5",
                "source_type": "summary", "source_label": "Executive Summary",
                "excerpt": "Synthetic stereo X-ray projections were generated for CNN training using Otsu segmentation and ASTRA Toolbox.",
            },
            {
                "source_id": "S2", "meeting_id": "holo", "meeting_title": "[DEMO] Near-Field Holography Reconstruction",
                "source_type": "summary", "source_label": "Executive Summary",
                "excerpt": "Near-field X-ray holography used Fresnel propagation, phase retrieval, SSIM, PSNR and FRC.",
            },
        ]
        answer = (
            "The topics include:\n"
            "- Near-field X-ray holography, Fresnel propagation and phase retrieval.\n"
            "- Synthetic stereo X-ray projection generation using Otsu segmentation.\n"
            "- A completely unsupported claim about electron microscopy."
        )
        grounded = service._ground_uncited_cross_meeting_lines(answer, sources)
        self.assertIn("phase retrieval [S2]", grounded)
        self.assertIn("Otsu segmentation [S1]", grounded)
        self.assertNotIn("electron microscopy", grounded)

    def test_grouped_evidence_context_keeps_meeting_boundaries(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        context = service._format_evidence_context([
            {"source_id": "S1", "meeting_id": "a", "meeting_title": "A", "meeting_date": None, "source_label": "Executive Summary", "excerpt": "Alpha"},
            {"source_id": "S2", "meeting_id": "b", "meeting_title": "B", "meeting_date": None, "source_label": "Executive Summary", "excerpt": "Beta"},
        ])
        self.assertIn("=== MEETING GROUP 1 ===", context)
        self.assertIn("=== MEETING GROUP 2 ===", context)
        self.assertIn("Meeting ID: a", context)
        self.assertIn("Meeting ID: b", context)


if __name__ == "__main__":
    unittest.main()
