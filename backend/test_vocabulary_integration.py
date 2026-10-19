from __future__ import annotations

import json

from app.transcription.result import TranscriptionResult, WordResult
from app.vocabulary.service import AdaptiveVocabularyService


def main() -> None:
    service = AdaptiveVocabularyService()
    print("=== MASTER GLOSSARY ===")
    print(json.dumps(service.global_status(), indent=2, ensure_ascii=False))

    meeting_id = "vocabulary-diagnostic"
    initial = service.start_meeting(meeting_id)
    print("\n=== INITIAL CONTEXT ===")
    print(json.dumps(initial.to_dict(), indent=2, ensure_ascii=False))

    sample = (
        "We will reconstruct the cone-beam tomography data with ASTA football, "
        "then compare SIRT with filtered back projection and inspect the ptychography results."
    )
    update = service.observe(meeting_id, sample)
    print("\n=== DETECTED TOPICS ===")
    print(json.dumps((update or service.snapshot(meeting_id)).to_dict(), indent=2, ensure_ascii=False))

    result = TranscriptionResult(
        text="We used ASTA football and tomo pie for reconstruction.",
        words=(
            WordResult("We", 0.98),
            WordResult("used", 0.97),
            WordResult("ASTA", 0.55),
            WordResult("football", 0.50),
            WordResult("and", 0.94),
            WordResult("tomo", 0.58),
            WordResult("pie", 0.54),
            WordResult("for", 0.96),
            WordResult("reconstruction.", 0.95),
        ),
        average_confidence=0.78,
    )
    corrected, correction_update = service.correct_result(meeting_id, result)
    print("\n=== TERMINOLOGY CORRECTION ===")
    print("Before:", result.text)
    print("After: ", corrected.text)
    print(json.dumps(list(corrected.corrections), indent=2, ensure_ascii=False))

    context = service.context_for(meeting_id)
    print("\n=== ACTIVE WHISPER CONTEXT ===")
    print("Categories:", ", ".join(context.categories) or "core only")
    print("Active terms:", len(context.active_terms))
    print("Hotwords preview:", (context.hotwords or "")[:500])


if __name__ == "__main__":
    main()
