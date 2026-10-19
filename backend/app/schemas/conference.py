from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class ConferenceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    location: str = Field(default="", max_length=300)
    start_date: str | None = Field(default=None, max_length=32)
    end_date: str | None = Field(default=None, max_length=32)
    program_url: str | None = Field(default=None, max_length=2000)
    description: str = Field(default="", max_length=4000)
    global_terms: list[str] = Field(default_factory=list)


class ConferenceTalkInput(BaseModel):
    external_id: str | None = Field(default=None, max_length=120)
    title: str = Field(min_length=1, max_length=2000)
    speaker: str = Field(default="", max_length=300)
    institution: str = Field(default="", max_length=500)
    session_name: str = Field(default="", max_length=300)
    track: str = Field(default="", max_length=300)
    room: str = Field(default="", max_length=200)
    day_label: str = Field(default="", max_length=120)
    start_at: str | None = Field(default=None, max_length=40)
    end_at: str | None = Field(default=None, max_length=40)
    abstract: str = Field(default="", max_length=30000)
    keywords: list[str] = Field(default_factory=list)
    context_terms: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=12000)
    interesting: bool = False


class ConferenceTalkUpdateRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=12000)
    interesting: bool | None = None
    keywords: list[str] | None = None
    context_terms: list[str] | None = None


class ConferenceBulkImportRequest(BaseModel):
    talks: list[ConferenceTalkInput]
    replace: bool = False


class ConferenceProgramImportRequest(BaseModel):
    url: str = Field(min_length=5, max_length=2000)


class ConferenceAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    scope: str = Field(default="conference", pattern="^(conference|day|session|selected)$")
    day_label: str | None = Field(default=None, max_length=120)
    session_name: str | None = Field(default=None, max_length=300)
    talk_ids: list[str] = Field(default_factory=list)
    top_k: int = Field(default=8, ge=1, le=20)
