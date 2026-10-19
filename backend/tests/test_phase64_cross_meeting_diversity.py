from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from app.rag.service import RAGService
from app.storage.meeting_storage import MeetingStorage
from seed_cross_meeting_demo import DEMO_MEETING_ID, create_demo, remove_demo


class Phase64CrossMeetingDiversityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / "phase64.db"
        self.storage = MeetingStorage(f"sqlite:///{db_path.as_posix()}")
        self._meeting(
            "m1",
            "Stereo X-ray Synthetic Data",
            "Stereo X-ray projections were generated with ASTRA Toolbox. Otsu segmentation and connected components prepared synthetic CNN training data.",
            "The talk focused on synthetic stereo X-ray data generation with Otsu segmentation, ASTRA Toolbox, and CNN training.",
        )
        self._meeting(
            "m2",
            "Near-Field Holography Reconstruction",
            "Near-field X-ray holography used Fresnel propagation and phase retrieval. FRC was proposed to validate spatial-frequency preservation.",
            "The meeting focused on near-field X-ray holography, Fresnel propagation, phase retrieval, and FRC-based reconstruction validation.",
        )

    def tearDown(self) -> None:
        self.storage.database.dispose()
        self.tempdir.cleanup()

    def _meeting(self, meeting_id: str, title: str, transcript: str, summary: str) -> None:
        self.storage.create_meeting(meeting_id, title, "2026-08-14T10:00:00+00:00")
        self.storage.upsert_transcript(meeting_id, transcript, segment_id="final", is_final=True)
        self.storage.complete_meeting(meeting_id, "2026-08-14T10:20:00+00:00")
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
                "generated_at": "2026-08-14T10:21:00+00:00",
                "provider": "test",
                "model": None,
                "transcript_segments": 1,
                "transcript_characters": len(transcript),
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
                        1.0 if any(k in lower for k in ("stereo", "astra", "otsu", "synthetic")) else 0.1,
                        1.0 if any(k in lower for k in ("holograph", "fresnel", "phase retrieval", "frc")) else 0.1,
                        0.5 if "x-ray" in lower else 0.1,
                    ])
                return httpx.Response(200, json={"embeddings": vectors})
            if request.url.path.endswith("/api/chat"):
                body = json.loads(request.content.decode("utf-8"))
                prompt = body["messages"][-1]["content"]
                if "Stereo X-ray Synthetic Data" in prompt and "Near-Field Holography Reconstruction" in prompt:
                    return httpx.Response(200, json={"message": {"content": "Stereo X-ray Synthetic Data focused on synthetic CNN training data [S1], while Near-Field Holography Reconstruction focused on Fresnel phase retrieval and FRC [S2]."}})
                return httpx.Response(200, json={"message": {"content": "The relevant meeting evidence is cited here [S1]."}})
            return httpx.Response(404)

        return httpx.MockTransport(handler)

    async def test_cross_meeting_overview_retrieves_multiple_meetings(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        result = await service.search("Compare the topics across all meetings", top_k=6)
        self.assertTrue(result["cross_meeting"])
        self.assertEqual(set(result["meetings_retrieved"]), {"Stereo X-ray Synthetic Data", "Near-Field Holography Reconstruction"})
        self.assertGreaterEqual(len(result["results"]), 2)

    async def test_cross_meeting_answer_reports_meetings_used(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        answer = await service.ask("Compare the topics across all meetings", top_k=6)
        self.assertTrue(answer["cross_meeting"])
        self.assertEqual(set(answer["meetings_used"]), {"Stereo X-ray Synthetic Data", "Near-Field Holography Reconstruction"})
        self.assertEqual(len(answer["sources"]), 2)
        self.assertIn("[S1]", answer["answer"])
        self.assertIn("[S2]", answer["answer"])

    async def test_which_meetings_query_does_not_force_unrelated_meeting(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        result = await service.search("Which meetings discussed Otsu segmentation?", top_k=6)
        titles = {item["meeting_title"] for item in result["results"]}
        self.assertEqual(titles, {"Stereo X-ray Synthetic Data"})

    async def test_cross_meeting_phrase_routes_to_archive(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        self.assertEqual(service._route_question("Summarize all meetings", []), "meeting_rag")
        self.assertEqual(service._route_question("Which meetings discussed phase retrieval?", []), "meeting_rag")

    async def test_demo_seed_is_explicit_and_reversible(self):
        self.assertTrue(create_demo(self.storage))
        demo = self.storage.get_meeting(DEMO_MEETING_ID)
        self.assertIsNotNone(demo)
        self.assertTrue(str(demo["title"]).startswith("[DEMO]"))
        self.assertFalse(create_demo(self.storage))
        self.assertTrue(remove_demo(self.storage))
        self.assertIsNone(self.storage.get_meeting(DEMO_MEETING_ID))


if __name__ == "__main__":
    unittest.main()
