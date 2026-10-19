from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.rag.service import RAGService
from app.storage.meeting_storage import MeetingStorage


class Phase62QueryRouterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / "router.db"
        self.storage = MeetingStorage(f"sqlite:///{db_path.as_posix()}")
        self.storage.create_meeting("m1", "Tomography Update", "2026-08-14T09:00:00+00:00")
        transcript = (
            "We reconstructed tomography data with ASTRA Toolbox and SIRT. "
            "The presentation focused on cone-beam geometry and sinograms."
        )
        self.storage.upsert_transcript(
            "m1",
            transcript,
            segment_id="final",
            is_final=True,
            average_confidence=0.96,
        )
        self.storage.complete_meeting("m1", "2026-08-14T09:30:00+00:00")
        self.storage.save_summary(
            "m1",
            {
                "summary": "The meeting used ASTRA Toolbox and SIRT for tomography reconstruction.",
                "key_points": ["ASTRA Toolbox was used for tomography reconstruction."],
                "decisions": [],
                "action_items": [],
                "discussion_questions": [],
                "open_questions": [],
                "slide_summaries": [],
                "technical_terms": ["ASTRA Toolbox", "SIRT", "tomography"],
                "transcription_uncertainties": [],
                "generated_at": "2026-08-14T09:31:00+00:00",
                "provider": "ollama",
                "model": "qwen3:4b-instruct",
                "transcript_segments": 1,
                "transcript_characters": len(transcript),
            },
        )
        self.chat_calls: list[str] = []
        self.request_count = 0

    def tearDown(self) -> None:
        self.storage.database.dispose()
        self.tempdir.cleanup()

    def _transport(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.request_count += 1
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
                        1.0 if "fourier" in lower else 0.0,
                        0.2,
                    ])
                return httpx.Response(200, json={"embeddings": vectors})
            if request.url.path.endswith("/api/chat"):
                payload = json.loads(request.content.decode("utf-8"))
                prompt = payload.get("messages", [])[-1].get("content", "")
                self.chat_calls.append(prompt)
                if "BOTH your general scientific knowledge" in prompt:
                    return httpx.Response(
                        200,
                        json={
                            "message": {
                                "content": (
                                    "General context: ASTRA Toolbox is software for tomographic reconstruction.\n\n"
                                    "From your meetings: ASTRA Toolbox was used for tomography reconstruction [S1]."
                                )
                            }
                        },
                    )
                if "Answer the user's question from general knowledge" in prompt:
                    return httpx.Response(
                        200,
                        json={
                            "message": {
                                "content": "The Fourier transform represents a signal in terms of its frequency components."
                            }
                        },
                    )
                return httpx.Response(
                    200,
                    json={"message": {"content": "ASTRA Toolbox was discussed in the meeting [S1]."}},
                )
            return httpx.Response(404)

        return httpx.MockTransport(handler)

    def _service(self) -> RAGService:
        fixed_tz = timezone(timedelta(hours=2), name="CEST")
        return RAGService(
            storage=self.storage,
            http_transport=self._transport(),
            now_provider=lambda: datetime(2026, 8, 14, 14, 37, tzinfo=fixed_tz),
        )

    async def test_date_question_uses_system_clock_without_rag_or_ollama(self):
        service = self._service()
        before = self.request_count
        answer = await service.ask("Can you tell me today's date?")
        self.assertEqual(answer["route"], "date_time")
        self.assertEqual(answer["sources"], [])
        self.assertIn("August 14, 2026", answer["answer"])
        self.assertEqual(self.request_count, before)

    async def test_general_question_without_archive_evidence_uses_general_ollama(self):
        service = self._service()
        answer = await service.ask("What is the Fourier transform?")
        self.assertEqual(answer["route"], "general")
        self.assertEqual(answer["sources"], [])
        self.assertIn("frequency components", answer["answer"])
        self.assertTrue(any("general knowledge" in prompt for prompt in self.chat_calls))

    async def test_general_topic_with_meeting_evidence_uses_hybrid_mode(self):
        service = self._service()
        answer = await service.ask("Tell me about ASTRA Toolbox")
        self.assertEqual(answer["route"], "hybrid")
        self.assertTrue(answer["meeting_evidence_used"])
        self.assertEqual(len(answer["sources"]), 1)
        self.assertIn("General context:", answer["answer"])
        self.assertIn("From your meetings:", answer["answer"])
        self.assertIn("[S1]", answer["answer"])

    async def test_named_person_question_stays_archive_grounded(self):
        service = self._service()
        answer = await service.ask("Do you know Vahid Rahmani?")
        self.assertEqual(answer["route"], "meeting_rag")
        self.assertFalse(answer["evidence_found"])
        self.assertEqual(answer["sources"], [])
        self.assertIn("Vahid Rahmani", answer["answer"])

    async def test_explicit_meeting_question_uses_meeting_rag(self):
        service = self._service()
        answer = await service.ask("Which meeting discussed ASTRA Toolbox?")
        self.assertEqual(answer["route"], "meeting_rag")
        self.assertTrue(answer["sources"])
        self.assertIn("[S1]", answer["answer"])


if __name__ == "__main__":
    unittest.main()
