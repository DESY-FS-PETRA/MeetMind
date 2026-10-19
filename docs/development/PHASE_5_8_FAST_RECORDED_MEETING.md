# Phase 5.8 — Fast Recorded Meeting Processing

## Goal

Process an existing audio/video recording as fast as the local CPU/GPU permits instead of replaying it through the real-time WebSocket pipeline.

## New UI mode

`Fast recorded meeting` appears under **Audio capture mode**. Choose a WAV/MP3/M4A/OGG/WebM/FLAC/AAC/Opus or MP4/MOV/MKV file, optionally upload a PPTX/PDF presentation, and click **Process Recording**.

The existing modes remain unchanged:

- Meeting microphone (processed) — live meeting
- Raw microphone diagnostic — acoustic diagnostic
- Audio file streaming test — real-time regression of the live WebSocket path
- Fast recorded meeting — direct offline batch processing

## Backend pipeline

1. Upload original recording to a temporary local file.
2. Reuse the already-loaded Faster-Whisper model.
3. Run `BatchedInferencePipeline` with VAD and word timestamps.
4. Apply hallucination guard, adaptive scientific vocabulary, confidence tracking, and transcript cleanup.
5. While batch segments are persisted, match raw speech to the uploaded presentation so slide transitions get transcript offsets.
6. Finalize the database meeting using the recording duration.
7. Generate the normal Ollama structured report, slide summaries, technical terms, and uncertainty list.
8. Return transcript + report in one response and keep the meeting in Meeting History.

## Configuration

Add to `.env` if you want to override the default:

```env
WHISPER_OFFLINE_BATCH_SIZE=8
```

Start with `8`. If GPU memory is tight, use `4`. If the GPU has abundant memory, you can test `12` or `16`; the best value depends on model size and GPU.

## API

`POST /recorded-meetings/process`

Multipart fields:

- `file` — recording
- `title` — meeting title
- `presentation_id` — optional already-uploaded presentation

Response includes:

```json
{
  "mode": "fast-recorded",
  "meeting_id": "...",
  "transcript": [],
  "summary": {},
  "processing": {
    "audio_duration_seconds": 720.0,
    "transcription_seconds": 38.0,
    "summary_seconds": 8.0,
    "total_seconds": 47.0,
    "transcription_speed_x": 18.95,
    "batch_size": 8
  }
}
```

The numbers above are illustrative only; actual speed depends on hardware, recording, Whisper model, and Ollama latency.

## Safety / resource behavior

Fast recorded processing is rejected while a live meeting is active. This prevents concurrent GPU-heavy live and batch Whisper inference. Temporary uploaded files are deleted after processing. A failed import also removes its partial meeting row so Meeting History is not polluted.

## Tests

Phase 5.8 adds an offline-processing unit test. The full backend suite now contains 57 tests.

```powershell
cd D:\meeting-ai-assistant\backend
..\venv\Scripts\activate
python -m unittest discover -s tests -v
```

Expected final line:

```text
Ran 57 tests
OK
```
