from __future__ import annotations

from array import array
import math
import sys


def pcm_dbfs(pcm_data: bytes) -> float:
    """Return RMS loudness in dBFS for 16-bit little-endian mono PCM."""
    if len(pcm_data) < 2:
        return float("-inf")

    samples = array("h")
    samples.frombytes(pcm_data[: len(pcm_data) - (len(pcm_data) % 2)])

    if sys.byteorder != "little":
        samples.byteswap()

    if not samples:
        return float("-inf")

    mean_square = sum(sample * sample for sample in samples) / len(samples)
    if mean_square <= 0:
        return float("-inf")

    rms = math.sqrt(mean_square)
    return 20.0 * math.log10(rms / 32768.0)


def contains_speech_energy(pcm_data: bytes, threshold_dbfs: float = -50.0) -> bool:
    return pcm_dbfs(pcm_data) >= threshold_dbfs
