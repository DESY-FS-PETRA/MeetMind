from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.storage.meeting_storage import MeetingStorage


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def migrate_directory(
    source: Path,
    *,
    database_url: str | None = None,
) -> dict[str, int]:
    storage = MeetingStorage(database_url=database_url)
    imported = 0
    skipped = 0
    failed = 0

    if not source.exists():
        storage.database.dispose()
        return {"imported": 0, "skipped": 0, "failed": 0}

    for folder in sorted(path for path in source.iterdir() if path.is_dir()):
        meeting_data = read_json(folder / "meeting.json", None)
        if not isinstance(meeting_data, dict):
            failed += 1
            print(f"SKIP {folder.name}: meeting.json is missing or invalid")
            continue

        meeting_id = str(meeting_data.get("meeting_id") or folder.name)
        if storage.get_meeting(meeting_id):
            skipped += 1
            print(f"SKIP {meeting_id}: already exists in the database")
            continue

        try:
            storage.create_meeting(
                meeting_id,
                str(meeting_data.get("title") or "Conference Meeting"),
                str(
                    meeting_data.get("start_time")
                    or meeting_data.get("created_at")
                    or ""
                ),
            )

            transcript = read_json(folder / "transcript.json", [])
            if isinstance(transcript, list):
                for index, item in enumerate(transcript):
                    if not isinstance(item, dict) or not str(item.get("text", "")).strip():
                        continue
                    storage.upsert_transcript(
                        meeting_id,
                        str(item.get("text", "")),
                        segment_id=str(
                            item.get("segment_id")
                            or item.get("id")
                            or f"legacy-{index}"
                        ),
                        event_id=item.get("id"),
                        created_at=item.get("time"),
                        revision=int(item.get("revision", 1)),
                        is_final=bool(item.get("is_final", True)),
                        words=list(item.get("words") or []),
                        average_confidence=item.get("average_confidence"),
                        low_confidence_count=int(item.get("low_confidence_count", 0)),
                    )

            if str(meeting_data.get("status", "")).casefold() == "completed":
                storage.complete_meeting(
                    meeting_id,
                    str(
                        meeting_data.get("end_time")
                        or meeting_data.get("start_time")
                        or ""
                    ),
                )

            summary = read_json(folder / "summary.json", None)
            if isinstance(summary, dict):
                summary.setdefault("meeting_id", meeting_id)
                storage.save_summary(meeting_id, summary)

            imported += 1
            print(f"IMPORTED {meeting_id}")
        except Exception as exc:  # pragma: no cover - CLI safety net
            failed += 1
            print(f"FAILED {meeting_id}: {exc!r}")

    storage.database.dispose()
    return {"imported": imported, "skipped": skipped, "failed": failed}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import Phase 1-4 JSON meeting folders into the Phase 5 database."
    )
    parser.add_argument(
        "--source",
        default="data/meetings",
        help="Directory that contains one folder per legacy meeting.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Optional SQLAlchemy URL. Defaults to DATABASE_URL/.env.",
    )
    args = parser.parse_args()

    result = migrate_directory(
        Path(args.source),
        database_url=args.database_url,
    )
    print(
        "Migration finished: "
        f"{result['imported']} imported, "
        f"{result['skipped']} skipped, "
        f"{result['failed']} failed"
    )


if __name__ == "__main__":
    main()
