import json
import os
from datetime import datetime


MEETING_DIR = "meetings"


class MeetingStorage:


    def __init__(self):

        os.makedirs(
            MEETING_DIR,
            exist_ok=True
        )


    def save_transcript(
        self,
        data
    ):

        filename = (
            f"{MEETING_DIR}/"
            f"meeting_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )


        with open(
            filename,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                indent=4,
                ensure_ascii=False
            )


        return filename