from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from fastapi import UploadFile

from app.presentation.service import PresentationService
from app.storage.meeting_storage import MeetingStorage
from app.vocabulary.service import AdaptiveVocabularyService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract slide text and scientific vocabulary from a PPTX or PDF."
    )
    parser.add_argument("presentation", type=Path)
    return parser.parse_args()


async def run(path: Path) -> None:
    source = path.resolve()
    if not source.exists():
        raise SystemExit(f"Presentation not found: {source}")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        storage = MeetingStorage(
            database_url=f"sqlite:///{(root / 'presentation_test.db').as_posix()}"
        )
        try:
            service = PresentationService(
                storage=storage,
                vocabulary=AdaptiveVocabularyService(),
                root=root / "uploads",
            )
            with source.open("rb") as stream:
                upload = UploadFile(filename=source.name, file=stream)
                payload = await service.upload(upload)

            print("=== PRESENTATION STATUS ===")
            print(
                json.dumps(
                    {
                        "title": payload["title"],
                        "filename": payload["filename"],
                        "source_type": payload["source_type"],
                        "slide_count": payload["slide_count"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            print("\n=== SLIDES ===")
            for slide in payload["slides"]:
                print(f"\n[{slide['slide_number']}] {slide['title']}")
                print("Terms:", ", ".join(slide["keywords"]) or "(none)")
                preview = " ".join(slide["body_text"].split())[:300]
                print("Text:", preview or "(no extractable text)")
                if slide["notes_text"]:
                    notes = " ".join(slide["notes_text"].split())[:200]
                    print("Notes:", notes)
        finally:
            storage.database.dispose()


if __name__ == "__main__":
    asyncio.run(run(parse_args().presentation))
