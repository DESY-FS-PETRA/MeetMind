import wave


class WavWriter:


    def save(
        self,
        filename,
        pcm_data,
        sample_rate=16000
    ):

        with wave.open(
            filename,
            "wb"
        ) as wav:

            wav.setnchannels(1)

            wav.setsampwidth(2)

            wav.setframerate(sample_rate)

            wav.writeframes(
                pcm_data
            )