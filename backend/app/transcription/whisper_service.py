from __future__ import annotations

import os
from dataclasses import dataclass, replace
from statistics import mean

from faster_whisper import BatchedInferencePipeline, WhisperModel

from app.transcription.result import TranscriptionResult, WordResult


@dataclass(frozen=True, slots=True)
class TimedTranscriptionResult:
    start: float
    end: float
    result: TranscriptionResult


@dataclass(frozen=True, slots=True)
class BatchTranscriptionResult:
    segments: tuple[TimedTranscriptionResult, ...]
    duration_seconds: float
    duration_after_vad_seconds: float | None
    language: str | None

    @property
    def text(self) -> str:
        return " ".join(
            item.result.text.strip()
            for item in self.segments
            if item.result.text.strip()
        ).strip()


class WhisperService:
    def __init__(self) -> None:
        self.model_name = os.getenv("WHISPER_MODEL", "small.en")
        self.language = os.getenv("WHISPER_LANGUAGE", "en") or None
        self.device = os.getenv("WHISPER_DEVICE", "cuda")
        default_compute_type = "float16" if self.device == "cuda" else "int8"
        self.compute_type = os.getenv(
            "WHISPER_COMPUTE_TYPE",
            default_compute_type,
        )
        self.pause_punctuation_seconds = float(
            os.getenv("WHISPER_PUNCTUATION_PAUSE_SECONDS", "0.65")
        )
        self.repetition_penalty = float(
            os.getenv("WHISPER_REPETITION_PENALTY", "1.15")
        )
        self.no_repeat_ngram_size = int(
            os.getenv("WHISPER_NO_REPEAT_NGRAM_SIZE", "3")
        )
        self.compression_ratio_threshold = float(
            os.getenv("WHISPER_COMPRESSION_RATIO_THRESHOLD", "2.2")
        )
        hallucination_threshold = float(
            os.getenv("WHISPER_HALLUCINATION_SILENCE_THRESHOLD", "1.0")
        )
        self.hallucination_silence_threshold = (
            hallucination_threshold if hallucination_threshold > 0 else None
        )

        print(
            "Loading Whisper model "
            f"{self.model_name} on {self.device}/{self.compute_type}..."
        )
        self.model = WhisperModel(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
        )
        self.batched = BatchedInferencePipeline(model=self.model)
        print("Whisper ready")

    def transcribe(
        self,
        filename: str,
        *,
        hotwords: str | None = None,
        initial_prompt: str | None = None,
    ) -> TranscriptionResult:
        segments, _ = self.model.transcribe(
            filename,
            language=self.language,
            beam_size=5,
            temperature=0.0,
            repetition_penalty=self.repetition_penalty,
            no_repeat_ngram_size=self.no_repeat_ngram_size,
            compression_ratio_threshold=self.compression_ratio_threshold,
            condition_on_previous_text=False,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": 700,
                "speech_pad_ms": 500,
            },
            no_speech_threshold=0.5,
            log_prob_threshold=-1.0,
            hallucination_silence_threshold=self.hallucination_silence_threshold,
            hotwords=hotwords,
            initial_prompt=initial_prompt,
        )

        segment_list = list(segments)
        words: list[WordResult] = []
        fallback_text: list[str] = []

        for segment in segment_list:
            text = segment.text.strip()
            if text:
                fallback_text.append(text)

            if not segment.words:
                continue

            for word in segment.words:
                token = word.word.strip()
                if not token:
                    continue
                words.append(
                    WordResult(
                        text=token,
                        probability=float(word.probability),
                        start=float(word.start),
                        end=float(word.end),
                    )
                )

        if words:
            words = self._insert_pause_punctuation(words)
            text = " ".join(word.text for word in words).strip()
            probabilities = [
                word.probability
                for word in words
                if word.probability is not None
            ]
            average_confidence = mean(probabilities) if probabilities else None
            return TranscriptionResult(
                text=text,
                words=tuple(words),
                average_confidence=average_confidence,
            )

        text = " ".join(fallback_text).strip()
        return TranscriptionResult.from_text(text)

    def transcribe_batched(
        self,
        filename: str,
        *,
        batch_size: int | None = None,
        hotwords: str | None = None,
        initial_prompt: str | None = None,
    ) -> BatchTranscriptionResult:
        """Transcribe a complete recording faster than real time.

        This path intentionally does not simulate microphone playback. The
        complete file is decoded once and Faster-Whisper batches VAD speech
        chunks for GPU inference.
        """
        resolved_batch_size = max(1, int(
            batch_size or os.getenv("WHISPER_OFFLINE_BATCH_SIZE", "8")
        ))
        segments, info = self.batched.transcribe(
            filename,
            language=self.language,
            batch_size=resolved_batch_size,
            beam_size=5,
            temperature=0.0,
            repetition_penalty=self.repetition_penalty,
            no_repeat_ngram_size=self.no_repeat_ngram_size,
            compression_ratio_threshold=self.compression_ratio_threshold,
            condition_on_previous_text=False,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 400,
            },
            no_speech_threshold=0.5,
            log_prob_threshold=-1.0,
            hallucination_silence_threshold=self.hallucination_silence_threshold,
            hotwords=hotwords,
            initial_prompt=initial_prompt,
        )

        output: list[TimedTranscriptionResult] = []
        for segment in segments:
            text = segment.text.strip()
            words: list[WordResult] = []
            for word in segment.words or []:
                token = word.word.strip()
                if not token:
                    continue
                words.append(
                    WordResult(
                        text=token,
                        probability=(
                            float(word.probability)
                            if word.probability is not None
                            else None
                        ),
                        start=float(word.start) if word.start is not None else None,
                        end=float(word.end) if word.end is not None else None,
                    )
                )

            if words:
                probabilities = [
                    word.probability
                    for word in words
                    if word.probability is not None
                ]
                result = TranscriptionResult(
                    text=" ".join(word.text for word in words).strip(),
                    words=tuple(words),
                    average_confidence=(
                        mean(probabilities) if probabilities else None
                    ),
                )
            else:
                result = TranscriptionResult.from_text(text)

            if not result.text.strip():
                continue
            output.append(
                TimedTranscriptionResult(
                    start=float(segment.start),
                    end=float(segment.end),
                    result=result,
                )
            )

        return BatchTranscriptionResult(
            segments=tuple(output),
            duration_seconds=float(getattr(info, "duration", 0.0) or 0.0),
            duration_after_vad_seconds=(
                float(info.duration_after_vad)
                if getattr(info, "duration_after_vad", None) is not None
                else None
            ),
            language=getattr(info, "language", self.language),
        )

    def _insert_pause_punctuation(
        self,
        words: list[WordResult],
    ) -> list[WordResult]:
        if self.pause_punctuation_seconds <= 0 or len(words) < 2:
            return words

        punctuated = list(words)
        for index in range(len(punctuated) - 1):
            current = punctuated[index]
            following = punctuated[index + 1]
            if current.end is None or following.start is None:
                continue

            gap = following.start - current.end
            if gap < self.pause_punctuation_seconds:
                continue

            if current.text.endswith(("?", "!", ".")):
                continue

            if current.text.endswith((",", ";", ":")):
                punctuated[index] = replace(
                    current,
                    text=f"{current.text[:-1]}.",
                )
            else:
                punctuated[index] = replace(current, text=f"{current.text}.")

            punctuated[index + 1] = replace(
                following,
                text=self._capitalize_first_alpha(following.text),
            )

        return punctuated

    @staticmethod
    def _capitalize_first_alpha(text: str) -> str:
        chars = list(text)
        for index, char in enumerate(chars):
            if char.isalpha():
                chars[index] = char.upper()
                break
        return "".join(chars)
