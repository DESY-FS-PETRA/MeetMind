from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from app.rag.service import RAGService
from app.storage.meeting_storage import MeetingStorage


class Phase642CrossMeetingSemanticsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / "phase642.db"
        self.storage = MeetingStorage(f"sqlite:///{db_path.as_posix()}")
        self._meeting(
            "shahin",
            "shahin 5",
            "Synthetic stereo X-ray projections were generated for CNN training using Otsu segmentation, connected components, and ASTRA Toolbox.",
            "The talk focused on synthetic stereo X-ray projection generation for CNN training using Otsu segmentation, connected components, random reassembly, and ASTRA Toolbox.",
            open_questions=["How does the distance between layers compare with the layer spacing in a microchip?"],
            discussion_questions=[{
                "question": "In Sina's experiments, how does the distance between layers compare with the layer spacing in a microchip?",
                "answer": "",
                "status": "unresolved",
            }],
        )
        self._meeting(
            "holo-demo",
            "[DEMO] Near-Field Holography Reconstruction",
            "Near-field X-ray holography used Fresnel propagation, phase retrieval, denoising, SSIM, PSNR, and FRC for reconstruction validation.",
            "The demo focused on near-field X-ray holography, Fresnel propagation, phase retrieval, and reconstruction-quality validation using SSIM, PSNR, and FRC.",
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
    def _transport(chat_answer: str) -> httpx.MockTransport:
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
                return httpx.Response(200, json={"message": {"content": chat_answer}})
            return httpx.Response(404)
        return httpx.MockTransport(handler)

    def test_union_vs_intersection_semantics(self):
        service = RAGService(storage=self.storage, http_transport=self._transport("unused"))
        self.assertEqual(service._cross_meeting_operation(
            "What image-processing or reconstruction methods were discussed across meetings?"
        ), "union")
        self.assertEqual(service._cross_meeting_operation(
            "Which reconstruction methods were shared by both meetings?"
        ), "intersection")
        self.assertEqual(service._cross_meeting_operation(
            "Compare Shahin's meeting with the holography demo meeting."
        ), "comparison")
        self.assertEqual(service._cross_meeting_operation(
            "Which meetings discussed Otsu segmentation?"
        ), "membership")

    def test_named_meeting_alias_resolver(self):
        service = RAGService(storage=self.storage, http_transport=self._transport("unused"))
        resolved = service._resolve_named_meetings(
            "Compare Shahin's meeting with the holography demo meeting."
        )
        self.assertEqual([item["meeting_id"] for item in resolved], ["shahin", "holo-demo"])
        self.assertEqual(
            [item["meeting_title"] for item in resolved],
            ["shahin 5", "[DEMO] Near-Field Holography Reconstruction"],
        )
        # The parser must not invent an entity named "Compare Shahin".
        self.assertNotIn("Compare Shahin", service._required_entities(
            "Compare Shahin's meeting with the holography demo meeting."
        ))

    async def test_named_comparison_recovers_from_false_no_evidence_llm_answer(self):
        service = RAGService(
            storage=self.storage,
            http_transport=self._transport(
                "I couldn't find any information about Compare Shahin's, Shahin in the indexed meetings."
            ),
        )
        answer = await service.ask(
            "Compare Shahin's meeting with the holography demo meeting.", top_k=6
        )
        self.assertTrue(answer["evidence_found"])
        self.assertEqual(answer["cross_meeting_operation"], "comparison")
        self.assertEqual(set(answer["meetings_used"]), {
            "shahin 5", "[DEMO] Near-Field Holography Reconstruction"
        })
        self.assertNotIn("couldn't find any information", answer["answer"].casefold())
        self.assertIn("shahin 5", answer["answer"].casefold())
        self.assertIn("near-field holography reconstruction", answer["answer"].casefold())
        self.assertEqual({item["source_label"] for item in answer["sources"]}, {"Executive Summary"})

    async def test_union_query_does_not_collapse_to_intersection(self):
        service = RAGService(
            storage=self.storage,
            http_transport=self._transport(
                'No method is jointly discussed across both meetings. Thus, no strong supported overlap exists [S1].'
            ),
        )
        answer = await service.ask(
            "What image-processing or reconstruction methods were discussed across meetings?",
            top_k=6,
        )
        self.assertEqual(answer["cross_meeting_operation"], "union")
        self.assertEqual(set(answer["meetings_used"]), {
            "shahin 5", "[DEMO] Near-Field Holography Reconstruction"
        })
        self.assertNotIn("no strong supported overlap", answer["answer"].casefold())
        self.assertIn("Otsu", answer["answer"])
        self.assertIn("phase retrieval", answer["answer"].casefold())

    async def test_per_meeting_citation_coverage_adds_missing_meeting(self):
        service = RAGService(
            storage=self.storage,
            http_transport=self._transport(
                "The holography meeting used phase retrieval and FRC [S1]. Another meeting generated synthetic stereo X-ray training data."
            ),
        )
        answer = await service.ask("Compare the topics across all meetings.", top_k=6)
        self.assertEqual(set(answer["meetings_used"]), {
            "shahin 5", "[DEMO] Near-Field Holography Reconstruction"
        })
        source_meetings = {source["meeting_title"] for source in answer["sources"]}
        self.assertEqual(source_meetings, {
            "shahin 5", "[DEMO] Near-Field Holography Reconstruction"
        })

    async def test_unresolved_summary_is_deterministic_and_deduplicated(self):
        service = RAGService(
            storage=self.storage,
            http_transport=self._transport("This chat answer should not be used."),
        )
        answer = await service.ask(
            "Summarize the unresolved questions across all meetings.", top_k=8
        )
        self.assertEqual(len(answer["sources"]), 2)
        self.assertEqual(set(answer["meetings_used"]), {
            "shahin 5", "[DEMO] Near-Field Holography Reconstruction"
        })
        self.assertEqual(answer["answer"].count("**shahin 5:**"), 1)
        self.assertEqual(answer["answer"].count("**[DEMO] Near-Field Holography Reconstruction:**"), 1)
        self.assertIn("distance between layers", answer["answer"])
        self.assertTrue(
            "fine phase gradients" in answer["answer"]
            or "denoising preserve fine phase gradients" in answer["answer"]
        )


if __name__ == "__main__":
    unittest.main()
