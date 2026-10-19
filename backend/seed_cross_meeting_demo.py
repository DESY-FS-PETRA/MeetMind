from __future__ import annotations

import argparse
import asyncio

from app.rag.service import RAGService
from app.storage.meeting_storage import MeetingStorage

DEMO_MEETING_ID = "meetmind-demo-nfh-001"
DEMO_TITLE = "[DEMO] Near-Field Holography Reconstruction"


def create_demo(storage: MeetingStorage) -> bool:
    if storage.get_meeting(DEMO_MEETING_ID) is not None:
        return False

    storage.create_meeting(DEMO_MEETING_ID, DEMO_TITLE, "2026-08-13T13:00:00+00:00")
    segments = [
        (
            "intro",
            "This demo meeting reviewed near-field X-ray holography. The team discussed Fresnel propagation, "
            "phase retrieval, and how detector intensity is converted into a quantitative phase reconstruction.",
        ),
        (
            "quality",
            "The discussion compared raw and denoised holograms. Reconstruction fidelity was evaluated with "
            "SSIM and PSNR, while FRC was proposed to check whether high spatial frequencies remain preserved.",
        ),
        (
            "next",
            "The group agreed that image-domain metrics alone are not enough for a reconstruction workflow. "
            "An open question is whether denoising changes fine phase gradients even when global similarity is high.",
        ),
    ]
    for index, (segment_id, text) in enumerate(segments):
        storage.upsert_transcript(
            DEMO_MEETING_ID,
            text,
            segment_id=segment_id,
            created_at=f"2026-08-13T13:{index * 8:02d}:00+00:00",
            revision=1,
            is_final=True,
            average_confidence=0.98,
        )
    storage.complete_meeting(DEMO_MEETING_ID, "2026-08-13T13:28:00+00:00")
    storage.save_summary(
        DEMO_MEETING_ID,
        {
            "summary": (
                "This clearly labeled demo meeting focused on near-field X-ray holography, Fresnel propagation, "
                "phase retrieval, and reconstruction-quality validation. It discussed using SSIM and PSNR for "
                "global fidelity and FRC for spatial-frequency preservation."
            ),
            "key_points": [
                "Near-field holography reconstruction uses Fresnel propagation and phase retrieval.",
                "SSIM and PSNR measure global reconstruction fidelity, while FRC probes spatial-frequency preservation.",
                "Denoising should be evaluated in the reconstructed phase domain, not only in the hologram domain.",
            ],
            "decisions": [
                "Use reconstruction-domain validation in addition to image-domain metrics for denoising experiments."
            ],
            "action_items": [
                {
                    "task": "Compare raw and denoised phase reconstructions with FRC.",
                    "owner": "Demo team",
                    "deadline": None,
                    "completed": False,
                }
            ],
            "discussion_questions": [
                {
                    "question": "Can global similarity remain high while fine phase gradients are degraded?",
                    "answer": "The meeting did not resolve this; FRC and local phase analysis were proposed.",
                    "status": "unresolved",
                }
            ],
            "open_questions": [
                "Does denoising preserve fine phase gradients and high spatial frequencies in the reconstruction?"
            ],
            "slide_summaries": [
                {
                    "slide_number": 1,
                    "title": "Near-Field Holography",
                    "summary": "Overview of Fresnel propagation and phase retrieval for near-field X-ray holography.",
                    "key_terms": ["near-field holography", "Fresnel propagation", "phase retrieval"],
                },
                {
                    "slide_number": 2,
                    "title": "Reconstruction Validation",
                    "summary": "Comparison of SSIM, PSNR, and FRC for evaluating reconstruction fidelity and spatial resolution.",
                    "key_terms": ["SSIM", "PSNR", "FRC", "spatial frequency"],
                },
            ],
            "technical_terms": [
                "near-field holography",
                "Fresnel propagation",
                "phase retrieval",
                "SSIM",
                "PSNR",
                "FRC",
            ],
            "transcription_uncertainties": [],
            "generated_at": "2026-08-13T13:29:00+00:00",
            "provider": "meetmind-demo",
            "model": None,
            "transcript_segments": len(segments),
            "transcript_characters": sum(len(item[1]) for item in segments),
        },
    )
    return True


def remove_demo(storage: MeetingStorage) -> bool:
    return storage.delete_meeting(DEMO_MEETING_ID)


async def reindex(storage: MeetingStorage) -> dict:
    service = RAGService(storage=storage)
    return await service.index_all(force=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Add or remove MeetMind's clearly labeled cross-meeting demo meeting.")
    parser.add_argument("--remove", action="store_true", help="Delete the demo meeting and its cascaded RAG chunks.")
    parser.add_argument("--no-index", action="store_true", help="Do not refresh the RAG index after the change.")
    args = parser.parse_args()

    storage = MeetingStorage()
    try:
        if args.remove:
            changed = remove_demo(storage)
            print("Removed demo meeting." if changed else "Demo meeting was not present.")
        else:
            changed = create_demo(storage)
            print("Created demo meeting." if changed else "Demo meeting already exists; nothing changed.")

        if not args.no_index and not args.remove:
            result = asyncio.run(reindex(storage))
            print(
                "RAG index ready: "
                f"{result.get('total_meetings', 0)} meetings, "
                f"{result.get('chunks', 0)} chunks, "
                f"semantic={bool(result.get('semantic_enabled'))}."
            )
        print(f"Demo title: {DEMO_TITLE}")
    finally:
        storage.database.dispose()


if __name__ == "__main__":
    main()
