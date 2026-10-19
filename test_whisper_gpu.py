
from faster_whisper import WhisperModel


model = WhisperModel(
    "small",
    device="cuda",
    compute_type="float16"
)


print("Whisper loaded on GPU")