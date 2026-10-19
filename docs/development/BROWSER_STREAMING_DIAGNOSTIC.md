# Browser Streaming Diagnostic

## Why the speaker test failed

The offline test produced 0% WER, so FFmpeg decoding, chunk overlap, Whisper, and transcript stitching are working correctly.

Playing a WAV file through laptop speakers and recording it again through the laptop microphone adds a separate acoustic channel:

- room echo and reverberation
- speaker frequency coloration
- microphone frequency response
- automatic gain changes
- background noise
- possible browser/driver audio processing

That test measures the room, speaker, and microphone more than it measures the streaming pipeline.

## New test mode

The frontend now has three audio modes:

1. `Meeting microphone (processed)` for a person speaking into the microphone.
2. `Raw microphone diagnostic` for inspecting the physical speaker-to-microphone path.
3. `Audio file streaming test` for a controlled end-to-end browser streaming test.

In file mode, the browser:

1. decodes the selected audio file with the Web Audio API;
2. routes it to a `MediaStreamAudioDestinationNode`;
3. records that stream with `MediaRecorder` as WebM/Opus;
4. sends the same 500 ms WebSocket chunks used by live meetings;
5. lets the backend decode them with FFmpeg and transcribe them with Whisper.

The file is not played through the speakers, so the microphone and room do not affect the result.

## Test procedure

1. Restart the frontend static server.
2. Open `http://localhost:3000`.
3. Press `Ctrl+F5`.
4. Confirm the browser console shows `APP.JS 2026-07-21.3 LOADED`.
5. Select `Audio file streaming test`.
6. Select `test2.wav`.
7. Click `Start Meeting`.
8. Do not click Stop. The test stops automatically when the file ends.
9. Compare the final transcript with the reference text.

## Diagnostic recording

For `Raw microphone diagnostic` and `Audio file streaming test`, a link appears after Stop:

`Download exact browser-captured audio`

Listen to that WebM file. It is the exact encoded stream that was sent to the backend. If the raw microphone recording already sounds distorted or misses words, Whisper cannot recover those missing acoustic details.

## Interpretation

- File streaming test is accurate: browser streaming and backend processing are healthy. The poor speaker test is an acoustic capture problem.
- File streaming test is inaccurate: inspect MediaRecorder/WebSocket/FFmpeg logs and the downloaded WebM.
- Raw microphone WebM sounds poor: check the selected input device, input level, distance, room noise, and audio drivers.
- Direct speech into the microphone works but computer playback does not: use tab/system-audio capture rather than recording the speakers through the microphone.
