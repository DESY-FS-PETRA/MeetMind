from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from app.rag.service import RAGService
from app.storage.meeting_storage import MeetingStorage


class Phase63LiveUtilitiesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / "phase63.db"
        self.storage = MeetingStorage(f"sqlite:///{db_path.as_posix()}")
        self.requests: list[httpx.Request] = []

    def tearDown(self) -> None:
        self.storage.database.dispose()
        self.tempdir.cleanup()

    def _transport(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if request.url.host == "geocoding-api.open-meteo.com":
                return httpx.Response(
                    200,
                    json={
                        "results": [
                            {
                                "name": "Hamburg",
                                "country": "Germany",
                                "latitude": 53.55,
                                "longitude": 10.0,
                                "timezone": "Europe/Berlin",
                            }
                        ]
                    },
                )
            if request.url.host == "api.open-meteo.com":
                return httpx.Response(
                    200,
                    json={
                        "current": {
                            "temperature_2m": 22.4,
                            "apparent_temperature": 21.7,
                            "weather_code": 2,
                            "wind_speed_10m": 13.2,
                        },
                        "daily": {
                            "temperature_2m_max": [24.8],
                            "temperature_2m_min": [15.1],
                            "precipitation_probability_max": [20],
                            "weather_code": [2],
                        },
                    },
                )
            if request.url.path.endswith("/api/chat"):
                return httpx.Response(200, json={"message": {"content": "unused"}})
            return httpx.Response(404)

        return httpx.MockTransport(handler)

    async def test_weather_with_browser_coordinates_uses_live_weather_not_ollama(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        result = await service.ask(
            "tell me weather temperature for today",
            latitude=53.55,
            longitude=10.0,
            timezone_name="Europe/Berlin",
        )
        self.assertEqual(result["route"], "weather")
        self.assertEqual(result["sources"], [])
        self.assertFalse(result["needs_location"])
        self.assertIn("22.4°C", result["answer"])
        self.assertIn("24.8°C", result["answer"])
        self.assertTrue(any(req.url.host == "api.open-meteo.com" for req in self.requests))
        self.assertFalse(any(req.url.path.endswith("/api/chat") for req in self.requests))

    async def test_weather_named_city_geocodes_then_fetches_forecast(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        result = await service.ask("What's the weather in Hamburg today?")
        self.assertEqual(result["route"], "weather")
        self.assertIn("Hamburg, Germany", result["answer"])
        self.assertTrue(any(req.url.host == "geocoding-api.open-meteo.com" for req in self.requests))
        self.assertTrue(any(req.url.host == "api.open-meteo.com" for req in self.requests))

    async def test_weather_without_location_requests_location_instead_of_hallucinating(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        result = await service.ask("weather today")
        self.assertEqual(result["route"], "weather")
        self.assertTrue(result["needs_location"])
        self.assertIn("specify a city", result["answer"].lower())
        self.assertEqual(self.requests, [])


class Phase63CitationAndPromptTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / "citations.db"
        self.storage = MeetingStorage(f"sqlite:///{db_path.as_posix()}")
        self.storage.create_meeting("m1", "Imaging Meeting", "2026-08-14T09:00:00+00:00")
        transcript = "Otsu segmentation and connected components were used before ASTRA Toolbox projection generation."
        self.storage.upsert_transcript("m1", transcript, segment_id="final", is_final=True, average_confidence=0.95)
        self.storage.complete_meeting("m1", "2026-08-14T09:30:00+00:00")
        self.storage.save_summary(
            "m1",
            {
                "summary": "The pipeline used Otsu segmentation, connected components, and ASTRA Toolbox.",
                "key_points": ["Otsu segmentation was used before connected-component labeling."],
                "decisions": [], "action_items": [], "discussion_questions": [], "open_questions": [],
                "slide_summaries": [{"slide_number": 4, "title": "Synthetic Data", "summary": "Synthetic volumes were segmented with Otsu before connected-component labeling.", "key_terms": ["Otsu segmentation"]}],
                "technical_terms": ["Otsu segmentation", "connected components", "ASTRA Toolbox"],
                "transcription_uncertainties": [],
                "generated_at": "2026-08-14T09:31:00+00:00", "provider": "ollama", "model": "qwen3:4b-instruct",
                "transcript_segments": 1, "transcript_characters": len(transcript),
            },
        )
        self.prompts: list[str] = []

    def tearDown(self) -> None:
        self.storage.database.dispose()
        self.tempdir.cleanup()

    def _transport(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/tags"):
                return httpx.Response(200, json={"models": [{"name": "embeddinggemma:latest"}, {"name": "qwen3:4b-instruct"}]})
            if request.url.path.endswith("/api/embed"):
                payload = json.loads(request.content.decode())
                inputs = payload.get("input") or []
                if isinstance(inputs, str): inputs = [inputs]
                return httpx.Response(200, json={"embeddings": [[1.0, 0.2, 0.1] for _ in inputs]})
            if request.url.path.endswith("/api/chat"):
                prompt = json.loads(request.content.decode())["messages"][-1]["content"]
                self.prompts.append(prompt)
                if (
                    "BOTH your general scientific knowledge" in prompt
                    or "general scientific answer has already been generated separately" in prompt
                ):
                    return httpx.Response(200, json={"message": {"content": "From your meetings: It was used for segmentation [S1][S3][S4]."}})
                return httpx.Response(200, json={"message": {"content": "The Fourier transform is $$F(\\omega)=\\int f(t)e^{-i\\omega t}\\,dt.$$"}})
            return httpx.Response(404)
        return httpx.MockTransport(handler)

    async def test_cited_sources_are_contiguously_renumbered(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        result = await service.ask("Tell me about Otsu segmentation", top_k=6)
        self.assertEqual(result["route"], "hybrid")
        ids = [item["source_id"] for item in result["sources"]]
        self.assertEqual(ids, [f"S{i}" for i in range(1, len(ids) + 1)])
        self.assertNotIn("[S4]", result["answer"])

    async def test_general_prompt_requests_concise_markdown_and_latex_delimiters(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        result = await service.ask("What is the Fourier transform?")
        self.assertEqual(result["route"], "general")
        prompt = self.prompts[-1]
        self.assertIn("compact answer", prompt)
        self.assertIn("$...$", prompt)
        self.assertIn("$$...$$", prompt)
        self.assertIn("Markdown", prompt)

    def test_technical_terms_are_lower_priority_than_grounded_content(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        self.assertLess(service._source_bonus("technical_terms"), service._source_bonus("slide_summary"))
        self.assertLess(service._source_bonus("technical_terms"), service._source_bonus("key_point"))


if __name__ == "__main__":
    unittest.main()


class Phase631RegressionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / "phase631.db"
        self.storage = MeetingStorage(f"sqlite:///{db_path.as_posix()}")
        self.requests: list[httpx.Request] = []

    def tearDown(self) -> None:
        self.storage.database.dispose()
        self.tempdir.cleanup()

    def _weather_transport(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if request.url.host == "geocoding-api.open-meteo.com":
                name = request.url.params.get("name")
                if str(name).casefold() == "hamburg":
                    return httpx.Response(200, json={"results": [{
                        "name": "Hamburg", "country": "Germany", "latitude": 53.55,
                        "longitude": 10.0, "timezone": "Europe/Berlin",
                    }]})
                return httpx.Response(200, json={"results": []})
            if request.url.host == "api.open-meteo.com":
                return httpx.Response(200, json={
                    "current": {"temperature_2m": 21.5, "apparent_temperature": 21.0, "weather_code": 1, "wind_speed_10m": 8.0},
                    "daily": {"temperature_2m_max": [24.0], "temperature_2m_min": [15.0], "precipitation_probability_max": [10], "weather_code": [1]},
                })
            if request.url.path.endswith("/api/chat"):
                return httpx.Response(200, json={"message": {"content": "should not be used"}})
            return httpx.Response(404)
        return httpx.MockTransport(handler)

    async def test_generic_temperature_for_today_is_not_misread_as_location(self):
        service = RAGService(storage=self.storage, http_transport=self._weather_transport())
        result = await service.ask("tell me weather temperature for today")
        self.assertEqual(result["route"], "weather")
        self.assertTrue(result["needs_location"])
        self.assertEqual(self.requests, [])
        self.assertIsNone(service._extract_weather_location("tell me weather temperature for today"))
        self.assertIsNone(service._extract_weather_location("tell me weather tempruter for today"))

    async def test_plain_city_followup_after_weather_location_request_stays_in_weather_route(self):
        service = RAGService(storage=self.storage, http_transport=self._weather_transport())
        history = [
            {"role": "user", "content": "weather today"},
            {"role": "assistant", "content": "I can fetch live weather, but I need a location. Please specify a city or postal code."},
        ]
        result = await service.ask("hamburg", history=history)
        self.assertEqual(result["route"], "weather")
        self.assertFalse(result["needs_location"])
        self.assertIn("Hamburg, Germany", result["answer"])
        self.assertIn("21.5°C", result["answer"])
        self.assertTrue(any(req.url.host == "geocoding-api.open-meteo.com" for req in self.requests))
        self.assertTrue(any(req.url.host == "api.open-meteo.com" for req in self.requests))

    def test_plain_location_followup_rejects_generic_weather_word(self):
        service = RAGService(storage=self.storage, http_transport=self._weather_transport())
        history = [{"role": "assistant", "content": "I need a location. Please specify a city."}]
        self.assertFalse(service._is_weather_location_followup("temperature", history))
        self.assertTrue(service._is_weather_location_followup("Hamburg", history))

    def test_compact_answer_sources_drops_technical_terms_and_caps_context(self):
        service = RAGService(storage=self.storage, http_transport=self._weather_transport())
        sources = [
            {"source_id": "S1", "source_type": "slide_summary", "excerpt": "slide evidence"},
            {"source_id": "S2", "source_type": "technical_terms", "excerpt": "Otsu segmentation"},
            {"source_id": "S3", "source_type": "transcript", "excerpt": "transcript evidence"},
            {"source_id": "S4", "source_type": "summary", "excerpt": "summary evidence"},
            {"source_id": "S5", "source_type": "key_point", "excerpt": "key evidence"},
        ]
        compact = service._compact_answer_sources(sources, max_sources=3, drop_technical_terms=True)
        self.assertEqual(len(compact), 3)
        self.assertNotIn("technical_terms", {item["source_type"] for item in compact})



class Phase632RoutingAndScienceRegressionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / "phase632.db"
        self.storage = MeetingStorage(f"sqlite:///{db_path.as_posix()}")
        self.storage.create_meeting("m1", "shahin 5", "2026-08-14T09:00:00+00:00")
        transcript = (
            "The synthetic data pipeline uses Otsu segmentation, connected components, "
            "and ASTRA Toolbox to generate stereo X-ray projections for CNN training."
        )
        self.storage.upsert_transcript(
            "m1", transcript, segment_id="final", is_final=True, average_confidence=0.95
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
                        "slide_number": 4,
                        "title": "Synthetic Data",
                        "summary": "Synthetic volumes were segmented with Otsu before connected-component labeling.",
                        "key_terms": ["Otsu segmentation"],
                    }
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
        self.requests: list[httpx.Request] = []
        self.prompts: list[str] = []

    def tearDown(self) -> None:
        self.storage.database.dispose()
        self.tempdir.cleanup()

    def _transport(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if request.url.host == "geocoding-api.open-meteo.com":
                name = str(request.url.params.get("name") or "")
                if name.casefold() == "hamburg":
                    return httpx.Response(200, json={"results": [{
                        "name": "Hamburg", "country": "Germany", "latitude": 53.55,
                        "longitude": 10.0, "timezone": "Europe/Berlin",
                    }]})
                return httpx.Response(200, json={"results": []})
            if request.url.host == "api.open-meteo.com":
                return httpx.Response(200, json={
                    "current": {
                        "temperature_2m": 22.0,
                        "apparent_temperature": 21.5,
                        "weather_code": 2,
                        "wind_speed_10m": 9.0,
                    },
                    "daily": {
                        "temperature_2m_max": [25.0],
                        "temperature_2m_min": [16.0],
                        "precipitation_probability_max": [10],
                        "weather_code": [2],
                    },
                })
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
                if "BOTH your general scientific knowledge" in prompt:
                    return httpx.Response(200, json={"message": {"content": (
                        "General context: Otsu is an automatic thresholding method.\n\n"
                        "From your meetings: Shahin used it in the synthetic-data pipeline [S1]."
                    )}})
                return httpx.Response(200, json={"message": {"content": (
                    "Shahin's talk was about generating synthetic stereo X-ray projections for CNN training [S1]."
                )}})
            return httpx.Response(404)

        return httpx.MockTransport(handler)

    async def test_weather_followup_with_in_prefix_resolves_city(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        history = [
            {"role": "user", "content": "weather today"},
            {"role": "assistant", "content": "I can fetch live weather, but I need a location. Please specify a city."},
        ]
        result = await service.ask("in hamburg", history=history)
        self.assertEqual(result["route"], "weather")
        self.assertFalse(result["needs_location"])
        self.assertIn("Hamburg, Germany", result["answer"])
        geocode = next(req for req in self.requests if req.url.host == "geocoding-api.open-meteo.com")
        self.assertEqual(str(geocode.url.params.get("name")).casefold(), "hamburg")

    async def test_new_otsu_topic_after_weather_history_is_hybrid_not_contaminated(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        history = [
            {"role": "user", "content": "weather in Hamburg"},
            {"role": "assistant", "content": "For Hamburg, it's 22°C now."},
        ]
        result = await service.ask("Tell me about Otsu segmentation.", history=history, top_k=6)
        self.assertEqual(result["route"], "hybrid")
        self.assertTrue(result["meeting_evidence_used"])
        hybrid_prompt = self.prompts[-1]
        self.assertIn("Current question:\nTell me about Otsu segmentation.", hybrid_prompt)
        self.assertNotIn("weather in Hamburg Tell me about Otsu", hybrid_prompt)

    def test_named_talk_question_is_archive_route_even_lowercase(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        route = service._route_question("what is the shahin's talk about?", [])
        self.assertEqual(route, "meeting_rag")
        self.assertEqual(service._query_intent("what is the shahin's talk about?"), "goal")

    def test_self_contained_short_topic_does_not_inherit_previous_user_query(self):
        history = [{"role": "user", "content": "Tell me about Otsu segmentation."}]
        query = RAGService._build_retrieval_query("what is the shahin's talk about?", history)
        self.assertEqual(query, "what is the shahin's talk about?")
        followup = RAGService._build_retrieval_query("what about the second method?", history)
        self.assertIn("Otsu segmentation", followup)

    def test_equation_policy_suppresses_unrequested_formula_but_allows_fourier_definition(self):
        otsu = RAGService._equation_policy("Tell me about Otsu segmentation")
        fourier = RAGService._equation_policy("What is the Fourier transform?")
        self.assertIn("Prefer prose", otsu)
        self.assertIn("canonical defining equation", fourier)

    async def test_explicit_shahin_talk_after_otsu_chat_stays_archive_only(self):
        service = RAGService(storage=self.storage, http_transport=self._transport())
        history = [
            {"role": "user", "content": "Tell me about Otsu segmentation."},
            {"role": "assistant", "content": "General context: Otsu is a thresholding method.\n\nFrom your meetings: It was used [S1]."},
        ]
        result = await service.ask("what is the shahin's talk about?", history=history, top_k=6)
        self.assertEqual(result["route"], "meeting_rag")
        self.assertNotIn("General context:", result["answer"])
        self.assertTrue(result["meeting_evidence_used"])
        self.assertEqual(result["sources"][0]["source_type"], "summary")
