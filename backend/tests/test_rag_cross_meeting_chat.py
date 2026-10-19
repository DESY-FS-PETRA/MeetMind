from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from app.rag.service import RAGService
from app.storage.meeting_storage import MeetingStorage


class RAGCrossMeetingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / "rag.db"
        self.storage = MeetingStorage(f"sqlite:///{db_path.as_posix()}")
        self._create_meeting(
            "m1",
            "Tomography Update",
            "We reconstructed the sinogram with ASTRA Toolbox and SIRT. The team discussed cone-beam geometry.",
            summary="Tomography reconstruction used ASTRA Toolbox and SIRT.",
            terms=["ASTRA Toolbox", "SIRT", "sinogram"],
        )
        self._create_meeting(
            "m2",
            "Holography Discussion",
            "Near-field holography used Fresnel propagation and phase retrieval. The phase-retrieval method remained under discussion.",
            summary="The meeting focused on near-field holography and phase retrieval.",
            terms=["near-field holography", "Fresnel propagation", "phase retrieval"],
        )

    def tearDown(self) -> None:
        self.storage.database.dispose()
        self.tempdir.cleanup()

    def _create_meeting(self, meeting_id, title, transcript, *, summary, terms):
        self.storage.create_meeting(meeting_id, title, "2026-08-14T10:00:00+00:00")
        self.storage.upsert_transcript(
            meeting_id,
            transcript,
            segment_id="final",
            is_final=True,
            average_confidence=0.95,
        )
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
                "technical_terms": terms,
                "transcription_uncertainties": [],
                "generated_at": "2026-08-14T10:31:00+00:00",
                "provider": "ollama",
                "model": "qwen3:4b-instruct",
                "transcript_segments": 1,
                "transcript_characters": len(transcript),
            },
        )

    @staticmethod
    def _transport():
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/tags"):
                return httpx.Response(
                    200,
                    json={
                        "models": [
                            {"name": "embeddinggemma:latest"},
                            {"name": "qwen3:4b-instruct"},
                        ]
                    },
                )
            if request.url.path.endswith("/api/embed"):
                payload = json.loads(request.content.decode("utf-8"))
                inputs = payload.get("input") or []
                if isinstance(inputs, str):
                    inputs = [inputs]
                vectors = []
                for text in inputs:
                    lower = text.casefold()
                    vectors.append([
                        1.0 if "astra" in lower or "tomograph" in lower else 0.0,
                        1.0 if "holograph" in lower or "phase retrieval" in lower else 0.0,
                        0.2,
                    ])
                return httpx.Response(200, json={"model": "embeddinggemma", "embeddings": vectors})
            if request.url.path.endswith("/api/chat"):
                return httpx.Response(
                    200,
                    json={
                        "message": {
                            "content": "ASTRA Toolbox was discussed in the Tomography Update meeting [S1]."
                        }
                    },
                )
            return httpx.Response(404, json={"error": "not found"})

        return httpx.MockTransport(handler)

    async def test_indexes_all_meetings_and_semantic_searches(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        result = await service.index_all()
        self.assertEqual(result["total_meetings"], 2)
        self.assertEqual(result["indexed_meetings"], 2)
        self.assertTrue(result["semantic_enabled"])
        self.assertGreater(result["chunks"], 2)

        search = await service.search("Which meeting used ASTRA Toolbox?", top_k=4)
        self.assertTrue(search["semantic_used"])
        self.assertGreater(len(search["results"]), 0)
        self.assertEqual(search["results"][0]["meeting_title"], "Tomography Update")

    async def test_chat_answer_contains_grounded_sources(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        answer = await service.ask("Where did we discuss ASTRA Toolbox?")
        self.assertIn("[S1]", answer["answer"])
        self.assertTrue(answer["sources"])
        self.assertEqual(answer["sources"][0]["meeting_title"], "Tomography Update")

    async def test_lexical_fallback_works_without_embedding_model(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/tags"):
                return httpx.Response(200, json={"models": [{"name": "qwen3:4b-instruct"}]})
            if request.url.path.endswith("/api/chat"):
                return httpx.Response(200, json={"message": {"content": "Found in Tomography Update [S1]."}})
            return httpx.Response(404)

        service = RAGService(storage=self.storage, http_transport=httpx.MockTransport(handler))
        result = await service.index_all()
        self.assertFalse(result["semantic_enabled"])
        search = await service.search("ASTRA Toolbox", top_k=4)
        self.assertFalse(search["semantic_used"])
        self.assertEqual(search["results"][0]["meeting_title"], "Tomography Update")

    async def test_incremental_index_skips_unchanged_meetings(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        first = await service.index_all()
        second = await service.index_all()
        self.assertEqual(first["indexed_meetings"], 2)
        self.assertEqual(second["indexed_meetings"], 0)
        self.assertEqual(second["unchanged_meetings"], 2)

    async def test_unrelated_named_entity_returns_no_evidence_and_no_sources(self):
        chat_calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/tags"):
                return httpx.Response(
                    200,
                    json={"models": [{"name": "embeddinggemma:latest"}, {"name": "qwen3:4b-instruct"}]},
                )
            if request.url.path.endswith("/api/embed"):
                payload = json.loads(request.content.decode("utf-8"))
                inputs = payload.get("input") or []
                if isinstance(inputs, str):
                    inputs = [inputs]
                # Deliberately give unrelated text a non-zero semantic vector;
                # the named-entity gate must still reject the evidence.
                return httpx.Response(200, json={"embeddings": [[0.0, 0.0, 1.0] for _ in inputs]})
            if request.url.path.endswith("/api/chat"):
                chat_calls["count"] += 1
                return httpx.Response(200, json={"message": {"content": "There is no information [S1-S4]."}})
            return httpx.Response(404)

        service = RAGService(storage=self.storage, http_transport=httpx.MockTransport(handler))
        answer = await service.ask("Do you know Vahid Rahmani?")
        self.assertFalse(answer["evidence_found"])
        self.assertEqual(answer["sources"], [])
        self.assertNotIn("[S", answer["answer"])
        self.assertIn("Vahid Rahmani", answer["answer"])
        self.assertEqual(chat_calls["count"], 0)

    async def test_only_sources_actually_cited_by_llm_are_returned(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/tags"):
                return httpx.Response(
                    200,
                    json={"models": [{"name": "embeddinggemma:latest"}, {"name": "qwen3:4b-instruct"}]},
                )
            if request.url.path.endswith("/api/embed"):
                payload = json.loads(request.content.decode("utf-8"))
                inputs = payload.get("input") or []
                if isinstance(inputs, str):
                    inputs = [inputs]
                vectors = []
                for item in inputs:
                    lower = item.casefold()
                    vectors.append([1.0 if "astra" in lower else 0.2, 0.2, 0.1])
                return httpx.Response(200, json={"embeddings": vectors})
            if request.url.path.endswith("/api/chat"):
                return httpx.Response(
                    200,
                    json={"message": {"content": "ASTRA Toolbox was used for tomography reconstruction [S2]."}},
                )
            return httpx.Response(404)

        service = RAGService(storage=self.storage, http_transport=httpx.MockTransport(handler))
        answer = await service.ask("How was ASTRA Toolbox used?", top_k=4)
        self.assertTrue(answer["evidence_found"])
        self.assertEqual(len(answer["sources"]), 1)
        self.assertEqual(answer["sources"][0]["source_id"], "S1")
        self.assertIn("[S1]", answer["answer"])
        self.assertNotIn("[S2]", answer["answer"])

    async def test_llm_no_evidence_answer_drops_retrieved_sources(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/tags"):
                return httpx.Response(
                    200,
                    json={"models": [{"name": "embeddinggemma:latest"}, {"name": "qwen3:4b-instruct"}]},
                )
            if request.url.path.endswith("/api/embed"):
                payload = json.loads(request.content.decode("utf-8"))
                inputs = payload.get("input") or []
                if isinstance(inputs, str):
                    inputs = [inputs]
                return httpx.Response(200, json={"embeddings": [[1.0, 0.2, 0.1] for _ in inputs]})
            if request.url.path.endswith("/api/chat"):
                return httpx.Response(
                    200,
                    json={"message": {"content": "I couldn't find enough evidence to answer this from the retrieved meetings [S1]."}},
                )
            return httpx.Response(404)

        service = RAGService(storage=self.storage, http_transport=httpx.MockTransport(handler))
        answer = await service.ask("What exact detector serial number was used?", top_k=4)
        self.assertFalse(answer["evidence_found"])
        self.assertEqual(answer["sources"], [])
        self.assertNotIn("[S1]", answer["answer"])



if __name__ == "__main__":
    unittest.main()
