from app.audio.queue import AudioQueue
from app.engine.meeting_engine import MeetingEngine
from app.events.bus import EventBus
from app.presentation.service import PresentationService
from app.presentation.slide_context import SlideContextService
from app.vocabulary.service import AdaptiveVocabularyService


audio_queue = AudioQueue()
event_bus = EventBus()
meeting_engine = MeetingEngine(event_bus, audio_queue)
vocabulary_service = AdaptiveVocabularyService()
presentation_service = PresentationService(
    storage=meeting_engine.storage,
    vocabulary=vocabulary_service,
)
slide_context_service = SlideContextService(meeting_engine.storage)
