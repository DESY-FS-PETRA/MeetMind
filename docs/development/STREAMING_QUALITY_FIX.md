# Streaming Quality Fix

## Why words were missing

1. The previous backend cut PCM into independent 6-second chunks with no overlap. Words crossing a boundary could be split and lost.
2. Whisper VAD used only 200 ms speech padding, which could trim quiet word beginnings/endings.
3. The browser enabled echo cancellation/noise suppression. During a test where a video is played from the same computer speakers, the browser may remove parts of that video as echo.
4. The English multilingual `small` model was used. The new default is `small.en` for better English accuracy.

## Changes

- 8-second chunks with 2-second overlap (new transcript every ~6 seconds after startup).
- Conservative text stitching removes overlap duplicates.
- VAD speech padding increased to 500 ms.
- Browser has two capture modes:
  - Meeting microphone: audio processing enabled.
  - Playback / accuracy test: echo cancellation, noise suppression, and auto gain disabled.
- Opus bitrate increased from 64 kbps to 96 kbps.
- Whisper settings are configurable in `.env`.
- Added `test_transcription_accuracy.py` to calculate Word Error Rate (WER).

## Objective accuracy test

Record or save a clean audio file containing a known sentence. Then run:

```powershell
cd D:\meeting-ai-assistant\backend
..\venv\Scripts\activate

python test_transcription_accuracy.py "D:\path\sample.wav" --expected "I am jumping in for Philip today because he cannot make it or he cannot attend the meeting. I am going to talk a little about the summer school we attended. It was quite a large group."
```

The script prints each raw overlapping chunk, the stitched new text, the final transcript, and WER.

For a CPU-only test:

```powershell
python test_transcription_accuracy.py "D:\path\sample.wav" --device cpu --compute-type int8 --expected "Reference text here"
```

## Browser test

- For your own voice directly into the microphone, select **Meeting microphone (processed)**.
- For a lecture/video played through speakers, select **Playback / accuracy test (raw)**.
- Use a clean file-based test for the most reliable comparison; room acoustics and laptop speakers/microphone add their own errors.
