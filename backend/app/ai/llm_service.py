from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.ai.prompts import SYSTEM_PROMPT, build_summary_prompt
from app.ai.structured_enricher import StructuredMeetingEnricher
from app.schemas.summary import ActionItem, MeetingSummaryContent


class LLMProviderError(RuntimeError):
    """Raised when an explicitly selected LLM provider cannot complete a request."""


@dataclass(frozen=True)
class LLMStatus:
    configured_provider: str
    active_provider: str | None
    available: bool
    model: str | None
    message: str
    installed_models: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "configured_provider": self.configured_provider,
            "active_provider": self.active_provider,
            "available": self.available,
            "model": self.model,
            "message": self.message,
            "installed_models": self.installed_models,
        }


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


class LLMService:
    """Meeting summarizer supporting Ollama, OpenAI, and an explicit fallback.

    Provider modes:
    - ``ollama``: use the local Ollama server. Fail visibly unless fallback is allowed.
    - ``openai``: use OpenAI. Fail visibly unless fallback is allowed.
    - ``auto``: try Ollama, then OpenAI, then the extractive fallback.
    - ``fallback``: always use the local extractive fallback.
    """

    def __init__(
        self,
        *,
        provider_mode: str | None = None,
        ollama_base_url: str | None = None,
        ollama_model: str | None = None,
        ollama_timeout_seconds: float | None = None,
        allow_fallback: bool | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
        self.provider_mode = (
            provider_mode or os.getenv("LLM_PROVIDER", "auto")
        ).strip().lower()
        if self.provider_mode not in {"auto", "ollama", "openai", "fallback"}:
            raise ValueError(
                "LLM_PROVIDER must be one of: auto, ollama, openai, fallback"
            )

        raw_base_url = (
            ollama_base_url
            or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        ).strip()
        self.ollama_api_base = self._normalise_ollama_api_base(raw_base_url)
        self.ollama_model = (
            ollama_model or os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct")
        ).strip()
        self.ollama_timeout_seconds = float(
            ollama_timeout_seconds
            if ollama_timeout_seconds is not None
            else os.getenv("OLLAMA_TIMEOUT_SECONDS", "180")
        )
        self.ollama_num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "32768"))
        self.ollama_keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "10m").strip()
        self.ollama_think = _env_bool("OLLAMA_THINK", False)
        self.allow_fallback = (
            allow_fallback
            if allow_fallback is not None
            else _env_bool("LLM_ALLOW_FALLBACK", self.provider_mode == "auto")
        )
        self._http_transport = http_transport
        self._structured_enricher = StructuredMeetingEnricher()

    @staticmethod
    def _normalise_ollama_api_base(base_url: str) -> str:
        base = base_url.rstrip("/")
        return base if base.endswith("/api") else f"{base}/api"

    @property
    def openai_enabled(self) -> bool:
        return bool(self.api_key)

    async def summarize(
        self,
        *,
        title: str,
        transcript: str,
        presentation_context: str | None = None,
    ) -> tuple[MeetingSummaryContent, str, str | None]:
        if self.provider_mode == "fallback":
            return self._summarize_locally(transcript), "extractive-fallback", None

        failures: list[str] = []
        providers = self._provider_order()
        for provider in providers:
            try:
                if provider == "ollama":
                    result = await self._summarize_with_ollama(
                        title=title,
                        transcript=transcript,
                        presentation_context=presentation_context,
                    )
                    return result, "ollama", self.ollama_model

                if provider == "openai":
                    if not self.openai_enabled:
                        failures.append("OpenAI API key is not configured")
                        continue
                    result = await self._summarize_with_openai(
                        title=title,
                        transcript=transcript,
                        presentation_context=presentation_context,
                    )
                    return result, "openai", self.openai_model
            except Exception as exc:
                message = self._friendly_provider_error(provider, exc)
                failures.append(message)
                print(f"{provider.capitalize()} summarization failed:", repr(exc))

        if self.allow_fallback or self.provider_mode == "auto":
            return self._summarize_locally(transcript), "extractive-fallback", None

        details = "; ".join(failures) or "No configured LLM provider was available"
        raise LLMProviderError(details)

    def _provider_order(self) -> list[str]:
        if self.provider_mode == "ollama":
            return ["ollama"]
        if self.provider_mode == "openai":
            return ["openai"]
        return ["ollama", "openai"]

    async def status(self) -> LLMStatus:
        if self.provider_mode == "fallback":
            return LLMStatus(
                configured_provider="fallback",
                active_provider="extractive-fallback",
                available=True,
                model=None,
                message="Local extractive fallback is enabled.",
                installed_models=[],
            )

        if self.provider_mode in {"ollama", "auto"}:
            try:
                models = await self._list_ollama_models()
                installed = self._model_is_installed(self.ollama_model, models)
                if installed:
                    return LLMStatus(
                        configured_provider=self.provider_mode,
                        active_provider="ollama",
                        available=True,
                        model=self.ollama_model,
                        message="Ollama is running and the configured model is installed.",
                        installed_models=models,
                    )

                return LLMStatus(
                    configured_provider=self.provider_mode,
                    active_provider=None,
                    available=False,
                    model=self.ollama_model,
                    message=(
                        f"Ollama is running, but model '{self.ollama_model}' is not installed. "
                        f"Run: ollama pull {self.ollama_model}"
                    ),
                    installed_models=models,
                )
            except Exception as exc:
                if self.provider_mode == "ollama":
                    return LLMStatus(
                        configured_provider="ollama",
                        active_provider=None,
                        available=False,
                        model=self.ollama_model,
                        message=self._friendly_provider_error("ollama", exc),
                        installed_models=[],
                    )

        if self.provider_mode in {"openai", "auto"} and self.openai_enabled:
            return LLMStatus(
                configured_provider=self.provider_mode,
                active_provider="openai",
                available=True,
                model=self.openai_model,
                message="OpenAI is configured. Availability is verified on first request.",
                installed_models=[],
            )

        return LLMStatus(
            configured_provider=self.provider_mode,
            active_provider=None,
            available=False,
            model=None,
            message="No available LLM provider is configured.",
            installed_models=[],
        )

    async def _summarize_with_ollama(
        self,
        *,
        title: str,
        transcript: str,
        presentation_context: str | None = None,
    ) -> MeetingSummaryContent:
        schema = MeetingSummaryContent.model_json_schema()
        schema_text = json.dumps(schema, ensure_ascii=False)
        prompt = build_summary_prompt(
            title,
            transcript,
            schema_text=schema_text,
            presentation_context=presentation_context,
        )

        payload: dict[str, Any] = {
            "model": self.ollama_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": schema,
            "think": self.ollama_think,
            "keep_alive": self.ollama_keep_alive,
            "options": {
                "temperature": 0,
                "num_ctx": self.ollama_num_ctx,
            },
        }

        timeout = httpx.Timeout(
            self.ollama_timeout_seconds,
            connect=min(10.0, self.ollama_timeout_seconds),
        )
        async with httpx.AsyncClient(
            timeout=timeout,
            transport=self._http_transport,
        ) as client:
            response = await client.post(f"{self.ollama_api_base}/chat", json=payload)
            response.raise_for_status()
            body = response.json()

        raw_text = str(body.get("message", {}).get("content", "")).strip()
        if not raw_text:
            raise RuntimeError("Ollama returned an empty structured response")

        parsed = MeetingSummaryContent.model_validate_json(raw_text)
        return self._structured_enricher.enrich(parsed, transcript)

    async def _list_ollama_models(self) -> list[str]:
        timeout = httpx.Timeout(10.0, connect=3.0)
        async with httpx.AsyncClient(
            timeout=timeout,
            transport=self._http_transport,
        ) as client:
            response = await client.get(f"{self.ollama_api_base}/tags")
            response.raise_for_status()
            payload = response.json()

        models: list[str] = []
        for item in payload.get("models", []):
            name = str(item.get("name") or item.get("model") or "").strip()
            if name:
                models.append(name)
        return sorted(set(models))

    @staticmethod
    def _model_is_installed(requested: str, installed: list[str]) -> bool:
        if requested in installed:
            return True
        requested_base = requested.removesuffix(":latest")
        for name in installed:
            name_base = name.removesuffix(":latest")
            if requested_base == name_base:
                return True
        return False

    async def _summarize_with_openai(
        self,
        *,
        title: str,
        transcript: str,
        presentation_context: str | None = None,
    ) -> MeetingSummaryContent:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "The openai package is not installed. Run pip install -r requirements.txt"
            ) from exc

        client = AsyncOpenAI(
            api_key=self.api_key,
            timeout=60.0,
            max_retries=2,
        )

        response = await client.responses.create(
            model=self.openai_model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_summary_prompt(
                        title,
                        transcript,
                        presentation_context=presentation_context,
                    ),
                },
            ],
            text={"format": {"type": "json_object"}},
        )

        raw_text = response.output_text.strip()
        if not raw_text:
            raise RuntimeError("The LLM returned an empty response")

        payload: dict[str, Any] = json.loads(raw_text)
        parsed = MeetingSummaryContent.model_validate(payload)
        return self._structured_enricher.enrich(parsed, transcript)

    def _friendly_provider_error(self, provider: str, exc: Exception) -> str:
        if provider == "ollama":
            if isinstance(exc, httpx.ConnectError):
                return (
                    "Cannot connect to Ollama. Start the Ollama application or run "
                    "'ollama serve', then try again."
                )
            if isinstance(exc, httpx.TimeoutException):
                return (
                    f"Ollama timed out after {self.ollama_timeout_seconds:g} seconds. "
                    "The model may still be loading; try again or increase "
                    "OLLAMA_TIMEOUT_SECONDS."
                )
            if isinstance(exc, httpx.HTTPStatusError):
                try:
                    error = exc.response.json().get("error")
                except Exception:
                    error = exc.response.text
                if exc.response.status_code == 404:
                    return (
                        f"Ollama model '{self.ollama_model}' was not found. "
                        f"Run: ollama pull {self.ollama_model}"
                    )
                return f"Ollama request failed: {error or exc.response.status_code}"
            return f"Ollama failed: {exc}"

        return f"OpenAI failed: {exc}"

    @staticmethod
    def _normalise_segment(text: str) -> str:
        return " ".join(text.split()).strip()

    def _summarize_locally(self, transcript: str) -> MeetingSummaryContent:
        # This fallback is intentionally transparent: it keeps development and
        # demos working without pretending to be an LLM-generated analysis.
        segments = [
            self._normalise_segment(part)
            for part in re.split(r"(?<=[.!?])\s+|\n+", transcript)
            if self._normalise_segment(part)
        ]

        unique_segments: list[str] = []
        seen: set[str] = set()
        for segment in segments:
            key = segment.casefold()
            if key not in seen:
                unique_segments.append(segment)
                seen.add(key)

        summary_segments = unique_segments[:4]
        summary = " ".join(summary_segments)
        if len(summary) > 900:
            summary = summary[:897].rstrip() + "..."
        if not summary:
            summary = "No usable speech was captured for this meeting."

        key_points = [self._trim(item, 220) for item in unique_segments[:6]]

        decisions = [
            self._trim(item, 220)
            for item in unique_segments
            if self._contains_any(
                item,
                (
                    "decided",
                    "agreed",
                    "we will use",
                    "we'll use",
                    "selected",
                    "chosen",
                ),
            )
        ][:5]

        action_items: list[ActionItem] = []
        for item in unique_segments:
            if self._contains_any(
                item,
                (
                    "action item",
                    "todo",
                    "to-do",
                    "need to",
                    "needs to",
                    "should implement",
                    "will implement",
                    "will prepare",
                    "follow up",
                ),
            ):
                action_items.append(
                    ActionItem(task=self._trim(item, 240), owner=None, deadline=None)
                )
            if len(action_items) >= 5:
                break

        open_questions = [
            self._trim(item, 220)
            for item in unique_segments
            if item.endswith("?")
        ][:5]

        return MeetingSummaryContent(
            summary=summary,
            key_points=key_points,
            decisions=decisions,
            action_items=action_items,
            open_questions=open_questions,
        )

    @staticmethod
    def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
        lowered = text.casefold()
        return any(marker in lowered for marker in markers)

    @staticmethod
    def _trim(text: str, limit: int) -> str:
        return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."
