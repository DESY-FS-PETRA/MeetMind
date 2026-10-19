import asyncio
import websockets
import wave


async def send_audio():

    uri = "ws://127.0.0.1:8000/ws/audio?format=pcm"


    async with websockets.connect(uri) as ws:

        print("Connected")


        with wave.open(
            "test.wav",
            "rb"
        ) as wav:

            pcm = wav.readframes(
                wav.getnframes()
            )


        print(
            "Sending PCM:",
            len(pcm),
            "bytes"
        )


        await ws.send(
            pcm
        )


        print(
            "Audio sent"
        )



asyncio.run(send_audio())