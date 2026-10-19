from __future__ import annotations

import asyncio
import json

from app.rag.service import RAGService
from app.storage.meeting_storage import MeetingStorage


async def main() -> None:
    storage = MeetingStorage()
    service = RAGService(storage=storage)

    print("=== RAG STATUS ===")
    status = await service.status()
    print(json.dumps(status, indent=2, ensure_ascii=False))

    print("\n=== INDEX ===")
    indexed = await service.index_all(force=False)
    print(json.dumps(indexed, indent=2, ensure_ascii=False))

    print("\n=== SEARCH TEST ===")
    result = await service.search("ASTRA Toolbox tomography reconstruction", top_k=5)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    print("\nTip: semantic_used=true means the Ollama embedding model is active.")
    print("If semantic_used=false, install the configured model and rerun:")
    print(f"  ollama pull {service.embedding_model}")


if __name__ == "__main__":
    asyncio.run(main())
