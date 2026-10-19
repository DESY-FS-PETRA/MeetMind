from __future__ import annotations

from pydantic import BaseModel, Field


class RAGSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=8, ge=1, le=20)
    meeting_ids: list[str] | None = None


class RAGChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=12000)


class RAGAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    history: list[RAGChatMessage] = Field(default_factory=list)
    top_k: int = Field(default=8, ge=1, le=20)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    timezone: str | None = Field(default=None, max_length=100)
