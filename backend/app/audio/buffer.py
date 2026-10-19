import time


class AudioBuffer:

    def __init__(self, max_seconds=5):

        self.chunks = []
        self.max_seconds = max_seconds
        self.start_time = time.time()


    def add(self, data: bytes):

        self.chunks.append(data)


    def ready(self):

        elapsed = time.time() - self.start_time

        return elapsed >= self.max_seconds


    def get_audio(self):

        audio = b"".join(self.chunks)

        self.chunks = []
        self.start_time = time.time()

        return audio