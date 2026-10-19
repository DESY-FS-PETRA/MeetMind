from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class MeetingModel(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transcript_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    final_transcript: Mapped[str] = mapped_column(Text, nullable=False, default="")
    average_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_confidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    transcript_segments: Mapped[list["TranscriptSegmentModel"]] = relationship(
        back_populates="meeting",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TranscriptSegmentModel.created_at",
    )
    summary: Mapped["MeetingSummaryModel | None"] = relationship(
        back_populates="meeting",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    vocabulary_state: Mapped["MeetingVocabularyModel | None"] = relationship(
        back_populates="meeting",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class TranscriptSegmentModel(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (
        UniqueConstraint("meeting_id", "segment_id", name="uq_transcript_meeting_segment"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    segment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    speaker: Mapped[str] = mapped_column(String(100), nullable=False, default="unknown")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    words: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    average_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_confidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    meeting: Mapped[MeetingModel] = relationship(back_populates="transcript_segments")


class MeetingSummaryModel(Base):
    __tablename__ = "meeting_summaries"

    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"),
        primary_key=True,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_points: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    decisions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    open_questions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transcript_segments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transcript_characters: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    meeting: Mapped[MeetingModel] = relationship(back_populates="summary")
    action_items: Mapped[list["ActionItemModel"]] = relationship(
        back_populates="summary",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ActionItemModel.position",
    )


class MeetingSummaryExtrasModel(Base):
    __tablename__ = "meeting_summary_extras"

    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meeting_summaries.meeting_id", ondelete="CASCADE"),
        primary_key=True,
    )
    slide_summaries: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    technical_terms: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    transcription_uncertainties: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    discussion_questions: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True, default=list
    )


class MeetingSlideEventModel(Base):
    __tablename__ = "meeting_slide_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slide_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="automatic")
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    transcript_character_offset: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    transcript_word_offset: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class ActionItemModel(Base):
    __tablename__ = "action_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meeting_summaries.meeting_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    deadline: Mapped[str | None] = mapped_column(String(200), nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    summary: Mapped[MeetingSummaryModel] = relationship(back_populates="action_items")


class MeetingVocabularyModel(Base):
    __tablename__ = "meeting_vocabulary_states"

    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"),
        primary_key=True,
    )
    categories: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    category_labels: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    active_terms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    category_scores: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False, default=dict)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    observed_characters: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    meeting: Mapped[MeetingModel] = relationship(back_populates="vocabulary_state")


class PresentationModel(Base):
    __tablename__ = "presentations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    slide_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PresentationSlideModel(Base):
    __tablename__ = "presentation_slides"
    __table_args__ = (
        UniqueConstraint(
            "presentation_id",
            "slide_number",
            name="uq_presentation_slide_number",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    presentation_id: Mapped[str] = mapped_column(
        ForeignKey("presentations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slide_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notes_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class MeetingPresentationModel(Base):
    __tablename__ = "meeting_presentations"

    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"),
        primary_key=True,
    )
    presentation_id: Mapped[str] = mapped_column(
        ForeignKey("presentations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    active_slide_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    auto_match: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RAGMeetingIndexModel(Base):
    __tablename__ = "rag_meeting_indexes"

    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"),
        primary_key=True,
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    semantic_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RAGChunkModel(Base):
    __tablename__ = "rag_chunks"
    __table_args__ = (
        UniqueConstraint("meeting_id", "chunk_key", name="uq_rag_meeting_chunk_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_key: Mapped[str] = mapped_column(String(180), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_label: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    slide_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class ConferenceModel(Base):
    __tablename__ = "conferences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    location: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    start_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    program_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    global_terms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    talks: Mapped[list["ConferenceTalkModel"]] = relationship(
        back_populates="conference",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ConferenceTalkModel.start_at",
    )


class ConferenceTalkModel(Base):
    __tablename__ = "conference_talks"
    __table_args__ = (
        UniqueConstraint("conference_id", "external_id", name="uq_conference_talk_external_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conference_id: Mapped[str] = mapped_column(
        ForeignKey("conferences.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    speaker: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    institution: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    session_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    track: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    room: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    day_label: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    start_at: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    end_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    abstract: Mapped[str] = mapped_column(Text, nullable=False, default="")
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    context_terms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    interesting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    meeting_id: Mapped[str | None] = mapped_column(
        ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    conference: Mapped[ConferenceModel] = relationship(back_populates="talks")
