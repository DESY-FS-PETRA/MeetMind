from __future__ import annotations

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field


class ActionItem(BaseModel):
    task: str = Field(
        min_length=1,
        description="A concrete assigned task or explicit future commitment.",
    )
    owner: str | None = Field(
        default=None,
        description="Exact person or team named as responsible; null only if absent.",
    )
    deadline: str | None = Field(
        default=None,
        description="Exact deadline phrase stated in the transcript; null if absent.",
    )


class SlideSummary(BaseModel):
    slide_number: int = Field(ge=1)
    title: str = Field(default="")
    summary: str = Field(default="")
    key_terms: list[str] = Field(default_factory=list)


class DiscussionQuestion(BaseModel):
    question: str = Field(min_length=1)
    status: Literal["answered", "unresolved"]
    answer: str | None = Field(
        default=None,
        description="Concise transcript-grounded answer when answered; null if unresolved.",
    )


class MeetingSummaryContent(BaseModel):
    summary: str = Field(
        description="Concise abstractive summary in original wording, not copied sentences."
    )
    key_points: list[str] = Field(
        default_factory=list,
        description="Distinct important discussion points and outcomes.",
    )
    decisions: list[str] = Field(
        default_factory=list,
        description="Every explicit agreement, decision, selection, or approved choice.",
    )
    action_items: list[ActionItem] = Field(
        default_factory=list,
        description="Every explicit assignment or future commitment with owner/deadline.",
    )
    discussion_questions: list[DiscussionQuestion] = Field(
        default_factory=list,
        description="Meaningful technical questions, classified as answered or unresolved.",
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description="Only unresolved questions or undecided items. Answered questions must not appear here.",
    )
    slide_summaries: list[SlideSummary] = Field(
        default_factory=list,
        description="One factual summary for each slide that had spoken discussion.",
    )
    technical_terms: list[str] = Field(
        default_factory=list,
        description="Canonical scientific terms actually discussed in the transcript.",
    )
    transcription_uncertainties: list[str] = Field(
        default_factory=list,
        description="Low-confidence or potentially misrecognized transcript terms.",
    )


class MeetingSummary(MeetingSummaryContent):
    meeting_id: str
    generated_at: datetime
    provider: str
    model: str | None = None
    transcript_segments: int
    transcript_characters: int
