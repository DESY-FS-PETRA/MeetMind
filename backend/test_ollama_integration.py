from __future__ import annotations

import asyncio
import json

from dotenv import load_dotenv

load_dotenv()

from app.ai.llm_service import LLMProviderError, LLMService  # noqa: E402


SAMPLE_TRANSCRIPT = """
The team reviewed the AI meeting assistant. They agreed to use Ollama for local
meeting summarization so transcripts remain on the workstation. Vahid will
integrate the Ollama endpoint into FastAPI before Friday. The embedding model
for the future RAG phase has not yet been selected.
""".strip()


def validate_extraction(payload: dict) -> list[str]:
    errors: list[str] = []

    decisions = payload.get("decisions") or []
    if not any("ollama" in str(item).casefold() for item in decisions):
        errors.append("The explicit Ollama decision was not extracted.")

    action_items = payload.get("action_items") or []
    matching = [
        item
        for item in action_items
        if "integrate" in str(item.get("task", "")).casefold()
        and "ollama" in str(item.get("task", "")).casefold()
    ]
    if not matching:
        errors.append("The Ollama/FastAPI integration action item was not extracted.")
    else:
        item = matching[0]
        if str(item.get("owner") or "").casefold() != "vahid":
            errors.append("The action-item owner should be Vahid.")
        if "friday" not in str(item.get("deadline") or "").casefold():
            errors.append("The action-item deadline should contain Friday.")

    return errors


async def main() -> int:
    service = LLMService(provider_mode="ollama", allow_fallback=False)
    status = await service.status()

    print("=== OLLAMA STATUS ===")
    print(json.dumps(status.as_dict(), indent=2))
    if not status.available:
        print("\nOllama is not ready. Follow the message above and run this test again.")
        return 1

    print("\n=== STRUCTURED SUMMARY TEST ===")
    try:
        summary, provider, model = await service.summarize(
            title="Ollama integration test",
            transcript=SAMPLE_TRANSCRIPT,
        )
    except LLMProviderError as exc:
        print(f"FAILED: {exc}")
        return 1

    payload = summary.model_dump()
    print(f"Provider: {provider}")
    print(f"Model: {model}")
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    errors = validate_extraction(payload)
    if errors:
        print("\n=== VALIDATION FAILED ===")
        for error in errors:
            print(f"- {error}")
        return 1

    print("\n=== VALIDATION PASSED ===")
    print("Decision, action-item owner, and deadline were extracted correctly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
