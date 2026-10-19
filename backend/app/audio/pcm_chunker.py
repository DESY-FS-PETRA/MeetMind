from __future__ import annotations


class PCMChunker:
    """Collect PCM s16le mono audio into overlapping fixed-duration chunks.

    Overlap protects words that cross a chunk boundary. After the first chunk,
    each subsequent chunk reuses the tail of the previous chunk and adds new
    audio. A transcript stitcher removes the duplicated words later.
    """

    def __init__(
        self,
        sample_rate: int = 16_000,
        channels: int = 1,
        sample_width: int = 2,
        chunk_seconds: float = 8.0,
        overlap_seconds: float = 2.0,
        min_flush_seconds: float = 0.5,
    ) -> None:
        if chunk_seconds <= 0:
            raise ValueError("chunk_seconds must be greater than zero")
        if overlap_seconds < 0 or overlap_seconds >= chunk_seconds:
            raise ValueError("overlap_seconds must be >= 0 and < chunk_seconds")
        if min_flush_seconds < 0:
            raise ValueError("min_flush_seconds must be >= 0")

        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        self.chunk_seconds = chunk_seconds
        self.overlap_seconds = overlap_seconds
        self.min_flush_seconds = min_flush_seconds
        self._buffer = bytearray()
        self._has_emitted = False

        bytes_per_second = sample_rate * channels * sample_width
        self._chunk_bytes = int(bytes_per_second * chunk_seconds)
        self._overlap_bytes = int(bytes_per_second * overlap_seconds)
        self._hop_bytes = self._chunk_bytes - self._overlap_bytes
        self._min_flush_bytes = int(bytes_per_second * min_flush_seconds)

    def add(self, data: bytes) -> list[bytes]:
        if not data:
            return []

        self._buffer.extend(data)
        ready: list[bytes] = []

        while len(self._buffer) >= self._chunk_bytes:
            ready.append(bytes(self._buffer[: self._chunk_bytes]))
            del self._buffer[: self._hop_bytes]
            self._has_emitted = True

        return ready

    def flush(self) -> bytes | None:
        """Return the final chunk only when it contains meaningful new audio."""
        if not self._buffer:
            return None

        if self._has_emitted:
            # The buffer starts with audio already included in the previous
            # chunk. Require at least a small amount of genuinely new audio.
            new_audio_bytes = max(0, len(self._buffer) - self._overlap_bytes)
            if new_audio_bytes < self._min_flush_bytes:
                self._buffer.clear()
                return None
        elif len(self._buffer) < self._min_flush_bytes:
            self._buffer.clear()
            return None

        remaining = bytes(self._buffer)
        self._buffer.clear()
        return remaining
