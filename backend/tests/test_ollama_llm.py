from __future__ import annotations

import json
import unittest

import httpx

from app.ai.llm_service import LLMProviderError, LLMService


class OllamaLLMServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_structured_ollama_summary_is_validated(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/chat")
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "qwen3:4b")
            self.assertFalse(payload["stream"])
            self.assertIsInstance(payload["format"], dict)
            content = {
                "summary": "The team selected Ollama for local summarization.",
                "key_points": ["Meeting data remains local."],
                "decisions": ["Use Ollama."],
                "action_items": [
                    {"task": "Integrate the local endpoint", "owner": "Vahid", "deadline": None}
                ],
                "open_questions": [],
            }
            return httpx.Response(
                200,
                json={"message": {"role": "assistant", "content": json.dumps(content)}},
            )

        service = LLMService(
            provider_mode="ollama",
            ollama_model="qwen3:4b",
            allow_fallback=False,
            http_transport=httpx.MockTransport(handler),
        )
        result, provider, model = await service.summarize(
            title="Architecture review",
            transcript="We decided to use Ollama. Vahid will integrate it.",
        )

        self.assertEqual(provider, "ollama")
        self.assertEqual(model, "qwen3:4b")
        self.assertEqual(result.decisions, ["Use Ollama."])
        self.assertEqual(result.action_items[0].owner, "Vahid")

    async def test_postprocessor_recovers_items_omitted_by_small_model(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            content = {
                "summary": (
                    "The team decided to use Ollama for local meeting summarization. "
                    "Vahid will integrate it by Friday."
                ),
                "key_points": ["Ollama keeps transcripts local."],
                "decisions": [],
                "action_items": [],
                "open_questions": [
                    "Which embedding model will be used for RAG?"
                ],
            }
            return httpx.Response(
                200,
                json={"message": {"role": "assistant", "content": json.dumps(content)}},
            )

        service = LLMService(
            provider_mode="ollama",
            ollama_model="qwen3:4b-instruct",
            allow_fallback=False,
            http_transport=httpx.MockTransport(handler),
        )
        result, provider, model = await service.summarize(
            title="Ollama integration test",
            transcript=(
                "The team reviewed the AI meeting assistant. "
                "They agreed to use Ollama for local meeting summarization so "
                "transcripts remain on the workstation. "
                "Vahid will integrate the Ollama endpoint into FastAPI before Friday. "
                "The embedding model for the future RAG phase has not yet been selected."
            ),
        )

        self.assertEqual(provider, "ollama")
        self.assertEqual(model, "qwen3:4b-instruct")
        self.assertIn(
            "Use Ollama for local meeting summarization so transcripts remain on the workstation.",
            result.decisions,
        )
        self.assertEqual(len(result.action_items), 1)
        self.assertEqual(result.action_items[0].owner, "Vahid")
        self.assertEqual(result.action_items[0].deadline, "Friday")
        self.assertEqual(
            result.action_items[0].task,
            "Integrate the Ollama endpoint into FastAPI.",
        )

    async def test_status_detects_installed_model(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/tags")
            return httpx.Response(200, json={"models": [{"name": "qwen3:4b"}]})

        service = LLMService(
            provider_mode="ollama",
            ollama_model="qwen3:4b",
            http_transport=httpx.MockTransport(handler),
        )
        status = await service.status()
        self.assertTrue(status.available)
        self.assertEqual(status.active_provider, "ollama")

    async def test_explicit_ollama_mode_does_not_hide_failure(self) -> None:
        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "model not found"})

        service = LLMService(
            provider_mode="ollama",
            ollama_model="missing:model",
            allow_fallback=False,
            http_transport=httpx.MockTransport(handler),
        )
        with self.assertRaises(LLMProviderError) as context:
            await service.summarize(title="Test", transcript="Some transcript")
        self.assertIn("ollama pull missing:model", str(context.exception))

    async def test_auto_mode_can_fall_back(self) -> None:
        async def handler(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline")

        service = LLMService(
            provider_mode="auto",
            allow_fallback=True,
            http_transport=httpx.MockTransport(handler),
        )
        result, provider, model = await service.summarize(
            title="Test",
            transcript="A short sentence. Another short sentence.",
        )
        self.assertEqual(provider, "extractive-fallback")
        self.assertIsNone(model)
        self.assertTrue(result.summary)


if __name__ == "__main__":
    unittest.main()
