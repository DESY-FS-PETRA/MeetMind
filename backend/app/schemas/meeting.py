from __future__ import annotations

from pydantic import BaseModel, Field


class StartMeetingRequest(BaseModel):
    title: str = Field(default="Conference Meeting", min_length=1, max_length=200)
    presentation_id: str | None = Field(default=None, max_length=36)
    conference_talk_id: str | None = Field(default=None, max_length=36)
    context_terms: list[str] = Field(default_factory=list)


class UpdateMeetingRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class SlideAutoRequest(BaseModel):
    enabled: bool = True
