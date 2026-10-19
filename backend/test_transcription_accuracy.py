from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

from app.audio.pcm_chunker import PCMChunker
from app.audio.wav_writer import WavWriter
from app.transcription.streaming_assembler import StreamingTranscriptAssembler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Transcribe an audio file with the same overlapping streaming "
            "pipeline used by the application and optionally calculate WER."
        )
    )
    parser.add_argument("audio", type=Path, help="Path to WAV, MP3, M4A, WebM, etc.")
    parser.add_argument(
        "--expected",
        default="",
        help="Reference transcript used to calculate word error rate.",
    )
    parser.add_argument("--model", default=os.getenv("WHISPER_MODEL", "small.en"))
    parser.add_argument("--language", default=os.getenv("WHISPER_LANGUAGE", "en"))
    parser.add_argument("--device", default=os.getenv("WHISPER_DEVICE", "cuda"))
    parser.add_argument(
        "--compute-type",
        default=os.getenv("WHISPER_COMPUTE_TYPE", "float16"),
    )
    parser.add_argument(
        "--disable-vocabulary",
        action="store_true",
        help="Run without hotwords/initial prompt for an A/B comparison.",
    )
    return parser.parse_args()


def decode_to_pcm(audio_path: Path) -> bytes:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(audio_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-f",
        "s16le",
        "pipe:1",
    ]
    result = subprocess.run(command, check=True, capture_output=True)
    return result.stdout


def normalise_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.casefold())


def word_error_rate(reference: str, hypothesis: str) -> tuple[float, int, int]:
    ref = normalise_words(reference)
    hyp = normalise_words(hypothesis)
    rows = len(ref) + 1
    cols = len(hyp) + 1
    distance = [[0] * cols for _ in range(rows)]

    for i in range(rows):
        distance[i][0] = i
    for j in range(cols):
        distance[0][j] = j

    for i in range(1, rows):
        for j in range(1, cols):
            substitution = distance[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1])
            deletion = distance[i - 1][j] + 1
            insertion = distance[i][j - 1] + 1
            distance[i][j] = min(substitution, deletion, insertion)

    errors = distance[-1][-1]
    denominator = max(1, len(ref))
    return errors / denominator, errors, len(ref)


def main() -> None:
    args = parse_args()
    if not args.audio.exists():
        raise SystemExit(f"Audio file not found: {args.audio}")

    os.environ["WHISPER_MODEL"] = args.model
    os.environ["WHISPER_LANGUAGE"] = args.language
    os.environ["WHISPER_DEVICE"] = args.device
    os.environ["WHISPER_COMPUTE_TYPE"] = args.compute_type

    # Import after setting the environment so the service uses CLI settings.
    from app.transcription.whisper_service import WhisperService
    from app.transcription.hallucination_guard import TranscriptHallucinationGuard
    from app.vocabulary.service import AdaptiveVocabularyService

    pcm = decode_to_pcm(args.audio)
    chunker = PCMChunker(
        chunk_seconds=8.0,
        overlap_seconds=2.0,
        min_flush_seconds=0.5,
    )
    chunks = chunker.add(pcm)
    final_chunk = chunker.flush()
    if final_chunk:
        chunks.append(final_chunk)

    whisper = WhisperService()
    writer = WavWriter()
    assembler = StreamingTranscriptAssembler()
    vocabulary = AdaptiveVocabularyService()
    guard = TranscriptHallucinationGuard()
    vocabulary.start_meeting("accuracy-test")
    latest_text = ""

    print(f"Decoded {len(pcm)} PCM bytes into {len(chunks)} streaming chunk(s).")
    for index, chunk in enumerate(chunks, start=1):
        filename: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp:
                filename = temp.name
            writer.save(filename, chunk, sample_rate=16_000)
            context = vocabulary.context_for("accuracy-test")
            result = whisper.transcribe(
                filename,
                hotwords=None if args.disable_vocabulary else context.hotwords,
                initial_prompt=None if args.disable_vocabulary else context.initial_prompt,
            )
            result, guard_report = guard.sanitize(
                result,
                active_terms=() if args.disable_vocabulary else context.active_terms,
            )
            if not result.text:
                print(f"\nChunk {index}/{len(chunks)}")
                print("RAW:       <removed by hallucination guard>")
                continue
            vocabulary.observe("accuracy-test", result.text)
            result, _ = vocabulary.correct_result("accuracy-test", result)
            snapshot = assembler.add("accuracy-test", result)
            latest_text = snapshot.text if snapshot is not None else latest_text
            print(f"\nChunk {index}/{len(chunks)}")
            print(f"RAW:       {result.text}")
            if result.average_confidence is not None:
                print(f"CONFIDENCE: {result.average_confidence:.2%}")
            print(f"ASSEMBLED: {latest_text}")
            if result.corrections:
                print("VOCAB:     " + "; ".join(
                    (
                        f"{item['source']} → {item['replacement']}"
                        if "source" in item and "replacement" in item
                        else item.get("type", "diagnostic")
                    )
                    for item in result.corrections
                ))
            if guard_report.changed:
                print(
                    "GUARD:     "
                    f"removed={guard_report.removed_word_count}, "
                    f"collapsed={guard_report.collapsed_word_count}"
                )
            vocabulary_snapshot = vocabulary.snapshot("accuracy-test")
            if vocabulary_snapshot and vocabulary_snapshot.category_labels:
                print("TOPICS:    " + ", ".join(vocabulary_snapshot.category_labels))
            if snapshot is not None and snapshot.low_confidence_count:
                review_words = [
                    word["text"]
                    for word in snapshot.words
                    if word.get("needs_review")
                ]
                print(f"REVIEW:    {', '.join(review_words)}")
        finally:
            if filename:
                Path(filename).unlink(missing_ok=True)

    final_snapshot = assembler.finalize("accuracy-test")
    final_text = (final_snapshot.text if final_snapshot is not None else latest_text).strip()
    print("\n=== FINAL TRANSCRIPT ===")
    print(final_text or "<empty>")
    if final_snapshot is not None and final_snapshot.average_confidence is not None:
        print(f"Average word confidence: {final_snapshot.average_confidence:.2%}")
        review_words = [
            word["text"]
            for word in final_snapshot.words
            if word.get("needs_review")
        ]
        print(
            "Words needing review: "
            + (", ".join(review_words) if review_words else "none")
        )

    if args.expected.strip():
        wer, errors, reference_words = word_error_rate(args.expected, final_text)
        print("\n=== ACCURACY ===")
        print(f"Word errors: {errors}/{reference_words}")
        print(f"WER: {wer:.2%}")
        print(f"Approx. word accuracy: {max(0.0, 1.0 - wer):.2%}")


if __name__ == "__main__":
    main()
