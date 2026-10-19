from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import selectinload

from app.database.models import (
    ActionItemModel,
    MeetingModel,
    MeetingPresentationModel,
    MeetingSlideEventModel,
    MeetingSummaryExtrasModel,
    MeetingSummaryModel,
    MeetingVocabularyModel,
    PresentationModel,
    PresentationSlideModel,
    TranscriptSegmentModel,
)
from app.database.session import Database


class MeetingStorage:
    """Database-backed persistence used by the meeting and AI services.

    The public methods intentionally preserve the interface used by the earlier
    JSON implementation so the transcription pipeline does not need to know
    whether SQLite or PostgreSQL is behind it.
    """

    def __init__(
        self,
        database_url: str | None = None,
        *,
        database: Database | None = None,
    ) -> None:
        self.database = database or Database(database_url)
        self.database.create_schema()

    def create_meeting(self, meeting_id: str, title: str, started_at: str) -> dict[str, Any]:
        created_at = datetime.now(timezone.utc)
        meeting = MeetingModel(
            id=meeting_id,
            title=title.strip() or "Conference Meeting",
            status="active",
            created_at=created_at,
            start_time=self._parse_datetime(started_at) or created_at,
            end_time=None,
            transcript_count=0,
            final_transcript="",
            average_confidence=None,
            low_confidence_count=0,
        )
        with self.database.session_factory.begin() as session:
            session.add(meeting)
        return self._meeting_to_dict(meeting)

    def save_transcript(
        self,
        meeting_id: str,
        text: str,
        *,
        event_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        return self.upsert_transcript(
            meeting_id,
            text,
            segment_id=event_id or str(uuid4()),
            event_id=event_id,
            created_at=created_at,
            revision=1,
            is_final=False,
        )

    def upsert_transcript(
        self,
        meeting_id: str,
        text: str,
        *,
        segment_id: str,
        event_id: str | None = None,
        created_at: str | None = None,
        revision: int = 1,
        is_final: bool = False,
        words: list[dict] | None = None,
        average_confidence: float | None = None,
        low_confidence_count: int = 0,
    ) -> dict[str, Any]:
        with self.database.session_factory.begin() as session:
            meeting = session.get(MeetingModel, meeting_id)
            if meeting is None:
                raise FileNotFoundError(f"Meeting {meeting_id} was not found")

            segment = session.scalar(
                select(TranscriptSegmentModel).where(
                    TranscriptSegmentModel.meeting_id == meeting_id,
                    TranscriptSegmentModel.segment_id == segment_id,
                )
            )
            timestamp = self._parse_datetime(created_at) or datetime.now(timezone.utc)

            if segment is None:
                segment = TranscriptSegmentModel(
                    meeting_id=meeting_id,
                    event_id=event_id,
                    segment_id=segment_id,
                    revision=revision,
                    is_final=is_final,
                    created_at=timestamp,
                    speaker="unknown",
                    text=text,
                    words=list(words or []),
                    average_confidence=average_confidence,
                    low_confidence_count=low_confidence_count,
                )
                session.add(segment)
            elif revision >= segment.revision:
                segment.event_id = event_id
                segment.revision = revision
                segment.is_final = is_final
                segment.created_at = timestamp
                segment.text = text
                segment.words = list(words or [])
                segment.average_confidence = average_confidence
                segment.low_confidence_count = low_confidence_count

            # Flush first so newly inserted segments are visible to the
            # aggregate query even though the Session uses autoflush=False.
            session.flush()
            self._refresh_meeting_transcript_metadata(session, meeting)
            session.flush()
            return self._segment_to_dict(segment)

    def load_transcript(self, meeting_id: str) -> list[dict[str, Any]]:
        with self.database.session_factory() as session:
            rows = session.scalars(
                select(TranscriptSegmentModel)
                .where(TranscriptSegmentModel.meeting_id == meeting_id)
                .order_by(TranscriptSegmentModel.created_at, TranscriptSegmentModel.id)
            ).all()
            return [self._segment_to_dict(row) for row in rows]

    def load_final_transcript_text(self, meeting_id: str) -> str:
        with self.database.session_factory() as session:
            meeting = session.get(MeetingModel, meeting_id)
            if meeting is None:
                return ""
            if meeting.final_transcript.strip():
                return meeting.final_transcript.strip()

            rows = session.scalars(
                select(TranscriptSegmentModel)
                .where(TranscriptSegmentModel.meeting_id == meeting_id)
                .order_by(TranscriptSegmentModel.created_at, TranscriptSegmentModel.id)
            ).all()
            final_rows = [row for row in rows if row.is_final]
            selected = final_rows or rows
            return "\n".join(row.text.strip() for row in selected if row.text.strip()).strip()

    def complete_meeting(self, meeting_id: str, end_time: str) -> dict[str, Any]:
        with self.database.session_factory.begin() as session:
            meeting = session.get(MeetingModel, meeting_id)
            if meeting is None:
                raise FileNotFoundError(f"Meeting {meeting_id} was not found")

            meeting.status = "completed"
            meeting.end_time = self._parse_datetime(end_time) or datetime.now(timezone.utc)
            self._refresh_meeting_transcript_metadata(session, meeting)
            session.flush()
            return self._meeting_to_dict(meeting)

    def get_meeting(self, meeting_id: str) -> dict[str, Any] | None:
        with self.database.session_factory() as session:
            meeting = session.get(MeetingModel, meeting_id)
            return self._meeting_to_dict(meeting) if meeting else None

    def get_meeting_details(self, meeting_id: str) -> dict[str, Any] | None:
        with self.database.session_factory() as session:
            meeting = session.scalar(
                select(MeetingModel)
                .options(
                    selectinload(MeetingModel.transcript_segments),
                    selectinload(MeetingModel.summary).selectinload(
                        MeetingSummaryModel.action_items
                    ),
                    selectinload(MeetingModel.vocabulary_state),
                )
                .where(MeetingModel.id == meeting_id)
            )
            if meeting is None:
                return None

            payload = self._meeting_to_dict(meeting)
            payload["transcript"] = [
                self._segment_to_dict(item)
                for item in sorted(
                    meeting.transcript_segments,
                    key=lambda item: (item.created_at, item.id),
                )
            ]
            summary_extras = (
                session.get(MeetingSummaryExtrasModel, meeting_id)
                if meeting.summary
                else None
            )
            payload["summary"] = (
                self._summary_to_dict(meeting.summary, extras=summary_extras)
                if meeting.summary
                else None
            )
            payload["vocabulary"] = (
                self._vocabulary_to_dict(meeting.vocabulary_state)
                if meeting.vocabulary_state
                else None
            )
            payload["presentation"] = self._get_meeting_presentation_with_session(
                session,
                meeting_id,
            )
            return payload

    def list_meetings(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))

        filters = []
        if search and search.strip():
            pattern = f"%{search.strip()}%"
            filters.append(
                or_(
                    MeetingModel.title.ilike(pattern),
                    MeetingModel.final_transcript.ilike(pattern),
                )
            )

        with self.database.session_factory() as session:
            total = session.scalar(
                select(func.count(MeetingModel.id)).where(*filters)
            ) or 0
            meetings = session.scalars(
                select(MeetingModel)
                .where(*filters)
                .order_by(MeetingModel.start_time.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            completed = session.scalar(
                select(func.count(MeetingModel.id)).where(
                    MeetingModel.status == "completed"
                )
            ) or 0

            return {
                "items": [self._meeting_to_dict(item) for item in meetings],
                "total": int(total),
                "completed": int(completed),
                "limit": limit,
                "offset": offset,
            }

    def update_meeting(self, meeting_id: str, *, title: str) -> dict[str, Any] | None:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("Meeting title cannot be empty")

        with self.database.session_factory.begin() as session:
            meeting = session.get(MeetingModel, meeting_id)
            if meeting is None:
                return None
            meeting.title = clean_title
            session.flush()
            return self._meeting_to_dict(meeting)

    def delete_meeting(self, meeting_id: str) -> bool:
        with self.database.session_factory.begin() as session:
            result = session.execute(
                delete(MeetingModel).where(MeetingModel.id == meeting_id)
            )
            return bool(result.rowcount)


    def create_presentation(
        self,
        *,
        presentation_id: str,
        filename: str,
        source_type: str,
        title: str,
        storage_path: str,
        slides: list[dict[str, Any]],
    ) -> dict[str, Any]:
        created_at = datetime.now(timezone.utc)
        with self.database.session_factory.begin() as session:
            if session.get(PresentationModel, presentation_id) is not None:
                raise ValueError(f"Presentation {presentation_id} already exists")
            model = PresentationModel(
                id=presentation_id,
                filename=filename,
                source_type=source_type,
                title=title.strip() or filename,
                storage_path=storage_path,
                created_at=created_at,
                slide_count=len(slides),
            )
            session.add(model)
            for item in slides:
                session.add(
                    PresentationSlideModel(
                        presentation_id=presentation_id,
                        slide_number=int(item["slide_number"]),
                        title=str(item.get("title") or ""),
                        body_text=str(item.get("body_text") or ""),
                        notes_text=str(item.get("notes_text") or ""),
                        keywords=list(item.get("keywords") or []),
                    )
                )
            session.flush()
        result = self.get_presentation(presentation_id)
        if result is None:
            raise RuntimeError("Presentation was not persisted")
        return result

    def get_presentation(self, presentation_id: str) -> dict[str, Any] | None:
        with self.database.session_factory() as session:
            model = session.get(PresentationModel, presentation_id)
            if model is None:
                return None
            slides = session.scalars(
                select(PresentationSlideModel)
                .where(PresentationSlideModel.presentation_id == presentation_id)
                .order_by(PresentationSlideModel.slide_number)
            ).all()
            return self._presentation_to_dict(model, slides=slides)

    def attach_presentation(
        self,
        meeting_id: str,
        presentation_id: str,
        *,
        active_slide_number: int = 1,
        auto_match: bool = True,
    ) -> dict[str, Any]:
        with self.database.session_factory.begin() as session:
            meeting = session.get(MeetingModel, meeting_id)
            if meeting is None:
                raise FileNotFoundError(f"Meeting {meeting_id} was not found")
            presentation = session.get(PresentationModel, presentation_id)
            if presentation is None:
                raise FileNotFoundError(f"Presentation {presentation_id} was not found")
            if active_slide_number < 1 or active_slide_number > presentation.slide_count:
                raise ValueError("Active slide number is outside the presentation")

            link = session.get(MeetingPresentationModel, meeting_id)
            if link is None:
                link = MeetingPresentationModel(meeting_id=meeting_id)
                session.add(link)
            link.presentation_id = presentation_id
            link.active_slide_number = active_slide_number
            link.auto_match = bool(auto_match)
            link.last_match_score = None
            link.updated_at = datetime.now(timezone.utc)

            # Re-attaching a deck starts a fresh slide timeline for this meeting.
            session.execute(
                delete(MeetingSlideEventModel).where(
                    MeetingSlideEventModel.meeting_id == meeting_id
                )
            )
            session.add(
                MeetingSlideEventModel(
                    meeting_id=meeting_id,
                    slide_number=int(active_slide_number),
                    source="initial",
                    match_score=None,
                    transcript_character_offset=0,
                    transcript_word_offset=0,
                    changed_at=meeting.start_time or datetime.now(timezone.utc),
                )
            )
            session.flush()
        result = self.get_meeting_presentation(meeting_id)
        if result is None:
            raise RuntimeError("Presentation link was not persisted")
        return result

    def get_meeting_presentation(self, meeting_id: str) -> dict[str, Any] | None:
        with self.database.session_factory() as session:
            return self._get_meeting_presentation_with_session(session, meeting_id)

    def set_active_slide(
        self,
        meeting_id: str,
        slide_number: int,
        *,
        auto_match: bool | None = None,
        match_score: float | None = None,
        source: str = "manual",
    ) -> dict[str, Any]:
        with self.database.session_factory.begin() as session:
            link = session.get(MeetingPresentationModel, meeting_id)
            if link is None:
                raise FileNotFoundError(f"Meeting {meeting_id} has no presentation")
            presentation = session.get(PresentationModel, link.presentation_id)
            if presentation is None:
                raise FileNotFoundError("Linked presentation was not found")
            if slide_number < 1 or slide_number > presentation.slide_count:
                raise ValueError(
                    f"Slide number must be between 1 and {presentation.slide_count}"
                )

            previous_slide = int(link.active_slide_number or 1)
            changed = previous_slide != int(slide_number)
            link.active_slide_number = int(slide_number)
            if auto_match is not None:
                link.auto_match = bool(auto_match)
            link.last_match_score = match_score
            link.updated_at = datetime.now(timezone.utc)

            if changed:
                meeting = session.get(MeetingModel, meeting_id)
                transcript = (meeting.final_transcript if meeting is not None else "") or ""
                session.add(
                    MeetingSlideEventModel(
                        meeting_id=meeting_id,
                        slide_number=int(slide_number),
                        source=(source.strip().lower() or "manual")[:24],
                        match_score=match_score,
                        transcript_character_offset=len(transcript),
                        transcript_word_offset=len(transcript.split()),
                        changed_at=link.updated_at,
                    )
                )
            session.flush()
        result = self.get_meeting_presentation(meeting_id)
        if result is None:
            raise RuntimeError("Slide state was not persisted")
        return result

    def set_slide_auto_match(
        self,
        meeting_id: str,
        enabled: bool,
    ) -> dict[str, Any]:
        with self.database.session_factory.begin() as session:
            link = session.get(MeetingPresentationModel, meeting_id)
            if link is None:
                raise FileNotFoundError(f"Meeting {meeting_id} has no presentation")
            link.auto_match = bool(enabled)
            link.last_match_score = None
            link.updated_at = datetime.now(timezone.utc)
            session.flush()
        result = self.get_meeting_presentation(meeting_id)
        if result is None:
            raise RuntimeError("Slide mode was not persisted")
        return result

    def replace_slide_events(
        self,
        meeting_id: str,
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Replace the slide timeline after whole-recording global alignment."""
        with self.database.session_factory.begin() as session:
            meeting = session.get(MeetingModel, meeting_id)
            link = session.get(MeetingPresentationModel, meeting_id)
            if meeting is None or link is None:
                raise FileNotFoundError(f"Meeting {meeting_id} has no presentation")
            presentation = session.get(PresentationModel, link.presentation_id)
            if presentation is None:
                raise FileNotFoundError("Linked presentation was not found")

            session.execute(
                delete(MeetingSlideEventModel).where(
                    MeetingSlideEventModel.meeting_id == meeting_id
                )
            )
            clean_events: list[dict[str, Any]] = []
            last_slide: int | None = None
            last_offset = -1
            for event in sorted(
                events, key=lambda item: int(item.get("transcript_character_offset", 0))
            ):
                slide_number = int(event.get("slide_number") or 0)
                offset = max(0, int(event.get("transcript_character_offset") or 0))
                if not 1 <= slide_number <= int(presentation.slide_count or 0):
                    continue
                if slide_number == last_slide or offset < last_offset:
                    continue
                source = str(event.get("source") or "offline-global")[:24]
                score = event.get("match_score")
                row = MeetingSlideEventModel(
                    meeting_id=meeting_id,
                    slide_number=slide_number,
                    source=source,
                    match_score=float(score) if score is not None else None,
                    transcript_character_offset=offset,
                    transcript_word_offset=len((meeting.final_transcript or "")[:offset].split()),
                    changed_at=meeting.start_time or datetime.now(timezone.utc),
                )
                session.add(row)
                clean_events.append(
                    {
                        "slide_number": slide_number,
                        "transcript_character_offset": offset,
                        "source": source,
                        "match_score": row.match_score,
                    }
                )
                last_slide = slide_number
                last_offset = offset

            if clean_events:
                link.active_slide_number = int(clean_events[-1]["slide_number"])
                link.auto_match = True
                link.last_match_score = clean_events[-1].get("match_score")
                link.updated_at = datetime.now(timezone.utc)
            session.flush()
        return self.load_slide_events(meeting_id)

    def load_slide_events(self, meeting_id: str) -> list[dict[str, Any]]:
        with self.database.session_factory() as session:
            rows = session.scalars(
                select(MeetingSlideEventModel)
                .where(MeetingSlideEventModel.meeting_id == meeting_id)
                .order_by(MeetingSlideEventModel.transcript_character_offset, MeetingSlideEventModel.id)
            ).all()
            return [
                {
                    "id": row.id,
                    "meeting_id": row.meeting_id,
                    "slide_number": int(row.slide_number),
                    "source": row.source,
                    "match_score": row.match_score,
                    "transcript_character_offset": int(row.transcript_character_offset or 0),
                    "transcript_word_offset": int(row.transcript_word_offset or 0),
                    "changed_at": self._isoformat(row.changed_at),
                }
                for row in rows
            ]

    def build_slide_transcript_sections(
        self,
        meeting_id: str,
        *,
        max_section_characters: int = 3500,
    ) -> list[dict[str, Any]]:
        """Align the final rolling transcript with the uploaded slide timeline.

        Slide changes are recorded with the current transcript offset. Explicit
        phrases such as ``on slide 4`` are also used as deterministic anchors,
        which makes imported recordings and the reference test deck align even
        when automatic matching changes a little late.
        """
        payload = self.get_meeting_presentation(meeting_id)
        transcript = self.load_final_transcript_text(meeting_id)
        if payload is None or not transcript:
            return []

        slide_count = int(payload.get("slide_count") or 0)
        slides = {
            int(item["slide_number"]): item
            for item in payload.get("slides") or []
        }
        timeline_boundaries: list[dict[str, Any]] = []
        for event in self.load_slide_events(meeting_id):
            number = int(event["slide_number"])
            if 1 <= number <= slide_count:
                timeline_boundaries.append(
                    {
                        "slide_number": number,
                        "offset": max(0, min(len(transcript), int(event["transcript_character_offset"]))),
                        "source": event.get("source") or "timeline",
                    }
                )

        explicit_boundaries: list[dict[str, Any]] = []
        explicit_pattern = re.compile(r"\b(?:on\s+)?slide\s+(\d{1,3})\b", re.IGNORECASE)
        for match in explicit_pattern.finditer(transcript):
            number = int(match.group(1))
            if 1 <= number <= slide_count:
                explicit_boundaries.append(
                    {
                        "slide_number": number,
                        "offset": match.start(),
                        "source": "spoken-slide-number",
                    }
                )
        if slide_count:
            for match in re.finditer(r"\bon\s+the\s+final\s+slide\b", transcript, re.IGNORECASE):
                explicit_boundaries.append(
                    {
                        "slide_number": slide_count,
                        "offset": match.start(),
                        "source": "spoken-final-slide",
                    }
                )

        # A recording that explicitly announces several slide numbers provides
        # a more reliable alignment signal than asynchronous auto-match events.
        # Mixing both can split one spoken slide into small fragments when the
        # database event arrives a few words early or late. Use the spoken
        # sequence as the primary timeline once at least two distinct slide
        # announcements are present; otherwise retain the live timeline.
        explicit_slide_numbers = {
            int(item["slide_number"]) for item in explicit_boundaries
        }
        if len(explicit_slide_numbers) >= 2:
            boundaries = list(explicit_boundaries)
            zero_timeline = [
                item
                for item in timeline_boundaries
                if int(item["offset"]) == 0 and int(item["slide_number"]) == 1
            ]
            boundaries.extend(zero_timeline[:1])
        else:
            boundaries = [*timeline_boundaries, *explicit_boundaries]

        if not boundaries:
            boundaries.append({"slide_number": 1, "offset": 0, "source": "fallback"})
        elif min(item["offset"] for item in boundaries) > 0:
            first = min(boundaries, key=lambda item: int(item["offset"]))
            if str(first.get("source") or "") != "offline-global":
                boundaries.append({"slide_number": 1, "offset": 0, "source": "fallback"})

        # At equal offsets, explicit speech anchors are more precise than the
        # asynchronous database event. Collapse consecutive duplicate slides.
        source_priority = {
            "spoken-slide-number": 3,
            "spoken-final-slide": 3,
            "manual": 2,
            "automatic": 1,
            "initial": 0,
            "fallback": 0,
        }
        boundaries.sort(
            key=lambda item: (
                int(item["offset"]),
                -source_priority.get(str(item["source"]), 0),
            )
        )
        unique: list[dict[str, Any]] = []
        seen_offsets: set[tuple[int, int]] = set()
        for item in boundaries:
            key = (int(item["offset"]), int(item["slide_number"]))
            if key in seen_offsets:
                continue
            seen_offsets.add(key)
            if unique and unique[-1]["slide_number"] == item["slide_number"]:
                continue
            unique.append(item)

        sections: list[dict[str, Any]] = []
        for index, item in enumerate(unique):
            start_offset = int(item["offset"])
            end_offset = (
                int(unique[index + 1]["offset"])
                if index + 1 < len(unique)
                else len(transcript)
            )
            if end_offset <= start_offset:
                continue
            text = transcript[start_offset:end_offset].strip()
            if not text:
                continue
            number = int(item["slide_number"])
            slide = slides.get(number, {})
            section = {
                "slide_number": number,
                "title": str(slide.get("title") or f"Slide {number}"),
                "keywords": list(slide.get("keywords") or []),
                "body_text": str(slide.get("body_text") or ""),
                "notes_text": str(slide.get("notes_text") or ""),
                "transcript": text[:max_section_characters],
                "start_character": start_offset,
                "end_character": end_offset,
                "source": item.get("source") or "timeline",
            }
            if sections and sections[-1]["slide_number"] == number:
                merged = f"{sections[-1]['transcript']} {section['transcript']}".strip()
                sections[-1]["transcript"] = merged[:max_section_characters]
                sections[-1]["end_character"] = end_offset
            else:
                sections.append(section)
        return sections

    def build_presentation_context(
        self,
        meeting_id: str,
        *,
        max_characters: int = 12000,
    ) -> str:
        payload = self.get_meeting_presentation(meeting_id)
        if payload is None:
            return ""
        sections = {
            int(item["slide_number"]): item
            for item in self.build_slide_transcript_sections(meeting_id)
        }
        lines = [
            f"Presentation: {payload.get('title') or payload.get('filename')}",
        ]
        for slide in payload.get("slides") or []:
            number = int(slide.get("slide_number") or 0)
            title = str(slide.get("title") or f"Slide {number}")
            keywords = ", ".join(str(item) for item in slide.get("keywords") or [])
            line = f"Slide {number}: {title}"
            if keywords:
                line += f" | visible terms: {keywords}"
            lines.append(line)
            section = sections.get(number)
            if section and section.get("transcript"):
                spoken = re.sub(r"\s+", " ", str(section["transcript"]).strip())
                lines.append(f"Spoken while this slide was active: {spoken[:1800]}")
            if sum(len(item) + 1 for item in lines) >= max_characters:
                break
        return "\n".join(lines)[:max_characters]

    def _get_meeting_presentation_with_session(
        self,
        session,
        meeting_id: str,
    ) -> dict[str, Any] | None:
        link = session.get(MeetingPresentationModel, meeting_id)
        if link is None:
            return None
        presentation = session.get(PresentationModel, link.presentation_id)
        if presentation is None:
            return None
        slides = session.scalars(
            select(PresentationSlideModel)
            .where(PresentationSlideModel.presentation_id == presentation.id)
            .order_by(PresentationSlideModel.slide_number)
        ).all()
        payload = self._presentation_to_dict(presentation, slides=slides)
        payload.update(
            {
                "meeting_id": meeting_id,
                "active_slide_number": int(link.active_slide_number or 1),
                "auto_match": bool(link.auto_match),
                "last_match_score": link.last_match_score,
                "updated_at": self._isoformat(link.updated_at),
            }
        )
        payload["active_slide"] = next(
            (
                item
                for item in payload["slides"]
                if item["slide_number"] == payload["active_slide_number"]
            ),
            payload["slides"][0] if payload["slides"] else None,
        )
        return payload

    def save_vocabulary_state(
        self,
        meeting_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with self.database.session_factory.begin() as session:
            meeting = session.get(MeetingModel, meeting_id)
            if meeting is None:
                raise FileNotFoundError(f"Meeting {meeting_id} was not found")

            model = session.get(MeetingVocabularyModel, meeting_id)
            if model is None:
                model = MeetingVocabularyModel(meeting_id=meeting_id)
                session.add(model)

            model.categories = list(payload.get("categories") or [])
            model.category_labels = list(payload.get("category_labels") or [])
            model.active_terms = list(payload.get("active_terms") or [])
            model.category_scores = dict(payload.get("category_scores") or {})
            model.revision = int(payload.get("revision", 1))
            model.observed_characters = int(payload.get("observed_characters", 0))
            model.correction_count = int(payload.get("correction_count", 0))
            model.is_final = bool(payload.get("is_final", False))
            model.updated_at = (
                self._parse_datetime(payload.get("updated_at"))
                or datetime.now(timezone.utc)
            )
            session.flush()
            return self._vocabulary_to_dict(model)

    def load_vocabulary_state(self, meeting_id: str) -> dict[str, Any] | None:
        with self.database.session_factory() as session:
            model = session.get(MeetingVocabularyModel, meeting_id)
            return self._vocabulary_to_dict(model) if model else None

    def save_summary(self, meeting_id: str, summary: dict[str, Any]) -> None:
        with self.database.session_factory.begin() as session:
            meeting = session.get(MeetingModel, meeting_id)
            if meeting is None:
                raise FileNotFoundError(f"Meeting {meeting_id} was not found")

            model = session.get(MeetingSummaryModel, meeting_id)
            if model is None:
                model = MeetingSummaryModel(meeting_id=meeting_id)
                session.add(model)

            model.summary = str(summary.get("summary", ""))
            model.key_points = list(summary.get("key_points") or [])
            model.decisions = list(summary.get("decisions") or [])
            model.open_questions = list(summary.get("open_questions") or [])
            model.generated_at = (
                self._parse_datetime(summary.get("generated_at"))
                or datetime.now(timezone.utc)
            )
            model.provider = str(summary.get("provider", "unknown"))
            model.model = summary.get("model")
            model.transcript_segments = int(summary.get("transcript_segments", 0))
            model.transcript_characters = int(summary.get("transcript_characters", 0))

            model.action_items.clear()
            for position, item in enumerate(summary.get("action_items") or []):
                model.action_items.append(
                    ActionItemModel(
                        position=position,
                        task=str(item.get("task", "")).strip(),
                        owner=item.get("owner"),
                        deadline=item.get("deadline"),
                        completed=bool(item.get("completed", False)),
                    )
                )

            session.flush()
            extras = session.get(MeetingSummaryExtrasModel, meeting_id)
            if extras is None:
                extras = MeetingSummaryExtrasModel(meeting_id=meeting_id)
                session.add(extras)
            extras.slide_summaries = list(summary.get("slide_summaries") or [])
            extras.technical_terms = list(summary.get("technical_terms") or [])
            extras.transcription_uncertainties = list(
                summary.get("transcription_uncertainties") or []
            )
            extras.discussion_questions = list(
                summary.get("discussion_questions") or []
            )

    def load_summary(self, meeting_id: str) -> dict[str, Any] | None:
        with self.database.session_factory() as session:
            model = session.scalar(
                select(MeetingSummaryModel)
                .options(selectinload(MeetingSummaryModel.action_items))
                .where(MeetingSummaryModel.meeting_id == meeting_id)
            )
            if model is None:
                return None
            extras = session.get(MeetingSummaryExtrasModel, meeting_id)
            return self._summary_to_dict(model, extras=extras)

    def get_path(self, meeting_id: str):
        """Legacy compatibility shim.

        Phase 5 stores meetings in SQL. Code should no longer write files using
        this path, but the method remains to make older extensions fail less
        abruptly while they are migrated.
        """
        return None

    def _refresh_meeting_transcript_metadata(self, session, meeting: MeetingModel) -> None:
        rows = session.scalars(
            select(TranscriptSegmentModel)
            .where(TranscriptSegmentModel.meeting_id == meeting.id)
            .order_by(TranscriptSegmentModel.created_at, TranscriptSegmentModel.id)
        ).all()
        final_rows = [row for row in rows if row.is_final]
        selected = final_rows or rows

        meeting.transcript_count = len(rows)
        meeting.final_transcript = "\n".join(
            row.text.strip() for row in selected if row.text.strip()
        ).strip()

        confidences = [
            row.average_confidence
            for row in selected
            if row.average_confidence is not None
        ]
        meeting.average_confidence = (
            sum(confidences) / len(confidences) if confidences else None
        )
        meeting.low_confidence_count = sum(
            int(row.low_confidence_count or 0) for row in selected
        )

    @classmethod
    def _meeting_to_dict(cls, meeting: MeetingModel) -> dict[str, Any]:
        return {
            "meeting_id": meeting.id,
            "title": meeting.title,
            "status": meeting.status,
            "created_at": cls._isoformat(meeting.created_at),
            "start_time": cls._isoformat(meeting.start_time),
            "end_time": cls._isoformat(meeting.end_time),
            "transcript_count": int(meeting.transcript_count or 0),
            "final_transcript": meeting.final_transcript or "",
            "average_confidence": meeting.average_confidence,
            "low_confidence_count": int(meeting.low_confidence_count or 0),
        }

    @classmethod
    def _segment_to_dict(cls, segment: TranscriptSegmentModel) -> dict[str, Any]:
        return {
            "id": segment.event_id,
            "segment_id": segment.segment_id,
            "revision": int(segment.revision or 1),
            "is_final": bool(segment.is_final),
            "time": cls._isoformat(segment.created_at),
            "speaker": segment.speaker,
            "text": segment.text,
            "words": list(segment.words or []),
            "average_confidence": segment.average_confidence,
            "low_confidence_count": int(segment.low_confidence_count or 0),
        }

    @classmethod
    def _summary_to_dict(
        cls,
        model: MeetingSummaryModel,
        *,
        extras: MeetingSummaryExtrasModel | None = None,
    ) -> dict[str, Any]:
        return {
            "meeting_id": model.meeting_id,
            "summary": model.summary,
            "key_points": list(model.key_points or []),
            "decisions": list(model.decisions or []),
            "action_items": [
                {
                    "id": item.id,
                    "task": item.task,
                    "owner": item.owner,
                    "deadline": item.deadline,
                    "completed": bool(item.completed),
                }
                for item in sorted(model.action_items, key=lambda item: item.position)
            ],
            "open_questions": list(model.open_questions or []),
            "slide_summaries": list(extras.slide_summaries or []) if extras else [],
            "technical_terms": list(extras.technical_terms or []) if extras else [],
            "transcription_uncertainties": (
                list(extras.transcription_uncertainties or []) if extras else []
            ),
            "discussion_questions": (
                list(extras.discussion_questions or []) if extras else []
            ),
            "generated_at": cls._isoformat(model.generated_at),
            "provider": model.provider,
            "model": model.model,
            "transcript_segments": int(model.transcript_segments or 0),
            "transcript_characters": int(model.transcript_characters or 0),
        }

    @classmethod
    def _presentation_to_dict(
        cls,
        model: PresentationModel,
        *,
        slides: list[PresentationSlideModel] | None = None,
    ) -> dict[str, Any]:
        return {
            "presentation_id": model.id,
            "filename": model.filename,
            "source_type": model.source_type,
            "title": model.title,
            "created_at": cls._isoformat(model.created_at),
            "slide_count": int(model.slide_count or 0),
            "slides": [
                {
                    "slide_number": int(slide.slide_number),
                    "title": slide.title,
                    "body_text": slide.body_text,
                    "notes_text": slide.notes_text,
                    "keywords": list(slide.keywords or []),
                }
                for slide in (slides or [])
            ],
        }

    @classmethod
    def _vocabulary_to_dict(cls, model: MeetingVocabularyModel) -> dict[str, Any]:
        return {
            "meeting_id": model.meeting_id,
            "categories": list(model.categories or []),
            "category_labels": list(model.category_labels or []),
            "active_terms": list(model.active_terms or []),
            "active_term_count": len(model.active_terms or []),
            "category_scores": dict(model.category_scores or {}),
            "revision": int(model.revision or 0),
            "observed_characters": int(model.observed_characters or 0),
            "correction_count": int(model.correction_count or 0),
            "is_final": bool(model.is_final),
            "updated_at": cls._isoformat(model.updated_at),
        }

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _isoformat(value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
