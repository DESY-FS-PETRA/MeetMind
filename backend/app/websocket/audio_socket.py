from __future__ import annotations

import asyncio
import os
import subprocess
from contextlib import suppress

from fastapi import WebSocket, WebSocketDisconnect

from app.audio.pcm_chunker import PCMChunker
from app.core.state import audio_queue, meeting_engine


FFMPEG_COMMAND = (
    "ffmpeg",
    "-hide_banner",
    "-loglevel",
    "error",
    "-f",
    "webm",
    "-i",
    "pipe:0",
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
)


_active_audio_socket: WebSocket | None = None
_active_audio_lock = asyncio.Lock()


async def _register_audio_socket(websocket: WebSocket) -> None:
    global _active_audio_socket

    async with _active_audio_lock:
        previous = _active_audio_socket
        _active_audio_socket = websocket

    if previous is not None and previous is not websocket:
        print("Replacing stale audio WebSocket")
        with suppress(Exception):
            await previous.close(code=4001, reason="Replaced by a newer audio connection")


async def _unregister_audio_socket(websocket: WebSocket) -> None:
    global _active_audio_socket

    async with _active_audio_lock:
        if _active_audio_socket is websocket:
            _active_audio_socket = None


def _popen_creation_flags() -> int:
    """Prevent an extra FFmpeg console window on Windows."""
    if os.name == "nt":
        return subprocess.CREATE_NO_WINDOW
    return 0


async def _queue_ready_chunks(chunker: PCMChunker, pcm_data: bytes) -> None:
    meeting_id = meeting_engine.current_meeting_id
    if not meeting_id:
        print("Decoded audio discarded: no active meeting")
        return

    for chunk in chunker.add(pcm_data):
        print(f"Decoded PCM chunk ready: {len(chunk)} bytes")
        audio_queue.put(chunk, meeting_id)


async def _read_ffmpeg_stdout(
    process: subprocess.Popen[bytes],
    chunker: PCMChunker,
) -> None:
    assert process.stdout is not None

    while True:
        # Popen pipes are blocking. Running the read in a worker thread keeps
        # FastAPI's asyncio event loop responsive and works with Windows'
        # SelectorEventLoop (used by Uvicorn reload mode).
        pcm_data = await asyncio.to_thread(process.stdout.read, 32_768)
        if not pcm_data:
            break
        await _queue_ready_chunks(chunker, pcm_data)


async def _read_ffmpeg_stderr(process: subprocess.Popen[bytes]) -> None:
    assert process.stderr is not None

    while True:
        line = await asyncio.to_thread(process.stderr.readline)
        if not line:
            break

        message = line.decode("utf-8", errors="replace").strip()
        if message:
            print("FFmpeg:", message)


async def _write_ffmpeg_stdin(
    process: subprocess.Popen[bytes],
    data: bytes,
) -> None:
    assert process.stdin is not None

    if process.poll() is not None:
        raise RuntimeError(
            f"FFmpeg stopped unexpectedly with exit code {process.returncode}"
        )

    await asyncio.to_thread(process.stdin.write, data)
    await asyncio.to_thread(process.stdin.flush)


async def _stop_ffmpeg(process: subprocess.Popen[bytes]) -> None:
    if process.stdin is not None and not process.stdin.closed:
        with suppress(BrokenPipeError, OSError):
            await asyncio.to_thread(process.stdin.close)

    try:
        await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=5)
    except asyncio.TimeoutError:
        process.kill()
        await asyncio.to_thread(process.wait)


async def _stream_webm(websocket: WebSocket) -> bool:
    chunker = PCMChunker(chunk_seconds=8.0, overlap_seconds=2.0, min_flush_seconds=0.5)

    try:
        # Use the standard blocking subprocess API instead of
        # asyncio.create_subprocess_exec. The latter is unavailable when
        # Uvicorn --reload uses a SelectorEventLoop on Windows.
        process: subprocess.Popen[bytes] = subprocess.Popen(
            FFMPEG_COMMAND,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            creationflags=_popen_creation_flags(),
        )
    except FileNotFoundError:
        print("FFmpeg was not found in PATH")
        await websocket.close(code=1011, reason="FFmpeg is not available")
        return False
    except OSError as exc:
        print("Could not start FFmpeg:", exc)
        await websocket.close(code=1011, reason="Could not start FFmpeg")
        return False

    stdout_task = asyncio.create_task(_read_ffmpeg_stdout(process, chunker))
    stderr_task = asyncio.create_task(_read_ffmpeg_stderr(process))
    flush_final_chunk = True
    client_requested_stop = False

    try:
        while True:
            message = await websocket.receive()
            message_type = message.get("type")

            if message_type == "websocket.disconnect":
                code = message.get("code", 1000)
                flush_final_chunk = code != 4001
                print(f"Audio WebSocket disconnected code={code}")
                break

            webm_chunk = message.get("bytes")
            if webm_chunk:
                print(f"Received WebM: {len(webm_chunk)} bytes")
                await _write_ffmpeg_stdin(process, webm_chunk)
                continue

            control_text = message.get("text")
            if control_text:
                if control_text.strip().lower() == "stop":
                    client_requested_stop = True
                    print("Audio stop control received")
                    break
                print("Unknown audio control message ignored:", control_text)

    except WebSocketDisconnect as exc:
        flush_final_chunk = exc.code != 4001
        print(f"Audio WebSocket disconnected code={exc.code}")
    except (BrokenPipeError, ConnectionResetError) as exc:
        print("FFmpeg input pipe closed:", exc)
    except Exception as exc:
        print("Audio stream error:", exc)
    finally:
        await _stop_ffmpeg(process)

        # FFmpeg closes its output pipes after exiting. Wait for both reader
        # tasks so all decoded PCM is passed to the chunker before flushing.
        results = await asyncio.gather(
            stdout_task,
            stderr_task,
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                print("FFmpeg reader error:", result)

        remaining = chunker.flush() if flush_final_chunk else None
        if remaining:
            print(f"Flushing final PCM chunk: {len(remaining)} bytes")
            meeting_id = meeting_engine.current_meeting_id
            if meeting_id:
                audio_queue.put(remaining, meeting_id)
            else:
                print("Final PCM chunk discarded: no active meeting")
        elif not flush_final_chunk:
            print("Discarded partial audio from replaced connection")

        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()

    return client_requested_stop


async def _stream_pcm(websocket: WebSocket) -> None:
    """Compatibility path for test_audio_socket.py."""
    chunker = PCMChunker(chunk_seconds=8.0, overlap_seconds=2.0, min_flush_seconds=0.5)

    try:
        while True:
            pcm_data = await websocket.receive_bytes()
            print(f"Received PCM: {len(pcm_data)} bytes")
            await _queue_ready_chunks(chunker, pcm_data)
    except WebSocketDisconnect:
        print("PCM test client disconnected")
    finally:
        remaining = chunker.flush()
        meeting_id = meeting_engine.current_meeting_id
        if remaining and meeting_id:
            audio_queue.put(remaining, meeting_id)


async def audio_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    await _register_audio_socket(websocket)

    audio_format = websocket.query_params.get("format", "webm").lower()
    client_id = websocket.query_params.get("client_id", "unknown")
    print(f"Audio client connected; format={audio_format}; client_id={client_id}")

    try:
        if audio_format == "pcm":
            await _stream_pcm(websocket)
        else:
            client_requested_stop = await _stream_webm(websocket)
            if client_requested_stop:
                with suppress(Exception):
                    await websocket.send_json({"type": "audio_finalized"})
                with suppress(Exception):
                    await websocket.close(code=1000, reason="Audio finalized")
    finally:
        await _unregister_audio_socket(websocket)
