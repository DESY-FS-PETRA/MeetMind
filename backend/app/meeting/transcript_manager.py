from datetime import datetime

from app.meeting.storage import MeetingStorage
from app.events.events import TranscriptCreated


class TranscriptManager:


    def __init__(self):

        self.transcripts = []

        self.storage = MeetingStorage()



    def add(
        self,
        text
    ):


        item = {

            "time":
            datetime.now().isoformat(),

            "speaker":
            "unknown",

            "text":
            text
        }


        self.transcripts.append(
            item
        )


        print(
            "Transcript saved:",
            text
        )


    def save_meeting(self):

        file = self.storage.save_transcript(
            self.transcripts
        )


        print(
            "Meeting saved:",
            file
        )

    def handle_transcript( self,event: TranscriptCreated):

        self.add(event.text)