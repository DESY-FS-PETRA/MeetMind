from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

import httpx
from sqlalchemy import delete, func, select

from app.database.models import (
    ActionItemModel,
    MeetingModel,
    MeetingSummaryExtrasModel,
    MeetingSummaryModel,
    RAGChunkModel,
    RAGMeetingIndexModel,
)
from app.storage.meeting_storage import MeetingStorage


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*")
_CITATION_RE = re.compile(r"\[(S\d+)(?:\s*[-–]\s*(S?\d+))?\]", re.IGNORECASE)

_QUERY_STOPWORDS = {
    "a", "about", "all", "an", "and", "are", "as", "at", "be", "been",
    "can", "could", "did", "do", "does", "for", "from", "had", "has",
    "have", "how", "i", "in", "is", "it", "know", "me", "of", "on",
    "or", "our", "please", "presentation", "presentations", "talk", "talks", "speaker", "tell", "that",
    "meeting", "meetings", "discuss", "discussed", "discussion", "compare", "compared",
    "across", "between", "topic", "topics", "summarize", "summary",
    "the", "their", "there", "these", "they", "this", "those", "to",
    "was", "we", "were", "what", "when", "where", "which", "who",
    "why", "with", "would", "you", "your",
}

_QUESTION_STARTERS = {
    "do", "does", "did", "what", "when", "where", "which", "who", "why",
    "how", "is", "are", "was", "were", "can", "could", "would", "tell",
    "compare", "summarize",
}


@dataclass(frozen=True)
class RetrievalHit:
    chunk_id: int
    meeting_id: str
    meeting_title: str
    meeting_date: str | None
    source_type: str
    source_label: str
    slide_number: int | None
    text: str
    score: float
    semantic_score: float | None
    lexical_score: float

    def to_dict(self, source_id: str) -> dict[str, Any]:
        excerpt = re.sub(r"\s+", " ", self.text).strip()
        if len(excerpt) > 700:
            excerpt = excerpt[:697].rstrip() + "..."
        return {
            "source_id": source_id,
            "chunk_id": self.chunk_id,
            "meeting_id": self.meeting_id,
            "meeting_title": self.meeting_title,
            "meeting_date": self.meeting_date,
            "source_type": self.source_type,
            "source_label": self.source_label,
            "slide_number": self.slide_number,
            "excerpt": excerpt,
            "score": round(self.score, 4),
            "semantic_score": (
                round(self.semantic_score, 4)
                if self.semantic_score is not None
                else None
            ),
            "lexical_score": round(self.lexical_score, 4),
        }


class RAGService:
    """Local cross-meeting RAG using SQLite plus Ollama embeddings/chat.

    Text chunks are always indexed. Dense vectors are optional so the chat
    remains usable when the embedding model has not been installed yet.
    """

    def __init__(
        self,
        *,
        storage: MeetingStorage,
        ollama_base_url: str | None = None,
        llm_model: str | None = None,
        embedding_model: str | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.storage = storage
        raw_base = (ollama_base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.ollama_api_base = raw_base if raw_base.endswith("/api") else f"{raw_base}/api"
        self.llm_model = (llm_model or os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct")).strip()
        self.embedding_model = (
            embedding_model or os.getenv("RAG_EMBEDDING_MODEL", "embeddinggemma")
        ).strip()
        self.top_k = max(2, min(int(os.getenv("RAG_TOP_K", "8")), 20))
        self.chunk_words = max(80, min(int(os.getenv("RAG_CHUNK_WORDS", "180")), 500))
        self.chunk_overlap = max(0, min(int(os.getenv("RAG_CHUNK_OVERLAP_WORDS", "35")), self.chunk_words // 2))
        self.timeout_seconds = float(os.getenv("RAG_OLLAMA_TIMEOUT_SECONDS", "180"))
        self.min_score = float(os.getenv("RAG_MIN_SCORE", "0.10"))
        self.min_evidence_score = float(os.getenv("RAG_MIN_EVIDENCE_SCORE", "0.26"))
        self.min_semantic_score = float(os.getenv("RAG_MIN_SEMANTIC_SCORE", "0.38"))
        self.max_sources = max(2, min(int(os.getenv("RAG_MAX_SOURCES", "6")), 10))
        self.candidate_k = max(self.max_sources, min(int(os.getenv("RAG_CANDIDATE_K", "16")), 40))
        self._http_transport = http_transport
        self._now_provider = now_provider or (lambda: datetime.now().astimezone())

    async def status(self) -> dict[str, Any]:
        with self.storage.database.session_factory() as session:
            total_meetings = int(session.scalar(select(func.count(MeetingModel.id)).where(MeetingModel.status == "completed")) or 0)
            indexed_meetings = int(session.scalar(select(func.count(RAGMeetingIndexModel.meeting_id))) or 0)
            chunks = int(session.scalar(select(func.count(RAGChunkModel.id))) or 0)
            semantic_meetings = int(session.scalar(select(func.count(RAGMeetingIndexModel.meeting_id)).where(RAGMeetingIndexModel.semantic_ready.is_(True))) or 0)

        installed: list[str] = []
        ollama_available = False
        embedding_available = False
        llm_available = False
        message = "Lexical retrieval is available."
        try:
            installed = await self._list_models()
            ollama_available = True
            embedding_available = self._model_installed(self.embedding_model, installed)
            llm_available = self._model_installed(self.llm_model, installed)
            if embedding_available:
                message = "Semantic retrieval is available."
            else:
                message = (
                    f"Embedding model '{self.embedding_model}' is not installed; "
                    "using lexical retrieval fallback."
                )
        except Exception as exc:
            message = f"Ollama is unavailable; lexical retrieval fallback is active. ({type(exc).__name__})"

        return {
            "available": True,
            "ollama_available": ollama_available,
            "llm_available": llm_available,
            "embedding_available": embedding_available,
            "embedding_model": self.embedding_model,
            "llm_model": self.llm_model,
            "total_meetings": total_meetings,
            "indexed_meetings": indexed_meetings,
            "semantic_meetings": semantic_meetings,
            "chunks": chunks,
            "message": message,
            "installed_models": installed,
        }

    async def index_all(self, *, force: bool = False) -> dict[str, Any]:
        with self.storage.database.session_factory() as session:
            meeting_ids = list(session.scalars(
                select(MeetingModel.id)
                .where(MeetingModel.status == "completed")
                .order_by(MeetingModel.start_time)
            ).all())

        embedding_available = False
        try:
            embedding_available = self._model_installed(self.embedding_model, await self._list_models())
        except Exception:
            embedding_available = False

        indexed = 0
        skipped = 0
        total_chunks = 0
        semantic_chunks = 0
        errors: list[dict[str, str]] = []
        for meeting_id in meeting_ids:
            try:
                result = await self.index_meeting(
                    meeting_id,
                    force=force,
                    use_embeddings=embedding_available,
                )
                if result["changed"]:
                    indexed += 1
                else:
                    skipped += 1
                total_chunks += int(result["chunk_count"])
                semantic_chunks += int(result.get("semantic_chunk_count") or 0)
            except Exception as exc:
                errors.append({"meeting_id": meeting_id, "error": str(exc)})

        return {
            "indexed_meetings": indexed,
            "unchanged_meetings": skipped,
            "total_meetings": len(meeting_ids),
            "chunks": total_chunks,
            "semantic_chunks": semantic_chunks,
            "embedding_model": self.embedding_model,
            "semantic_enabled": embedding_available,
            "errors": errors,
        }

    async def ensure_current(self) -> dict[str, Any]:
        return await self.index_all(force=False)

    async def index_meeting(
        self,
        meeting_id: str,
        *,
        force: bool = False,
        use_embeddings: bool = True,
    ) -> dict[str, Any]:
        document = self._load_meeting_document(meeting_id)
        if document is None:
            raise FileNotFoundError(f"Meeting {meeting_id} was not found")

        chunks = self._build_chunks(document)
        fingerprint = self._fingerprint(document, chunks)
        with self.storage.database.session_factory() as session:
            existing = session.get(RAGMeetingIndexModel, meeting_id)
            existing_semantic = bool(existing.semantic_ready) if existing else False
            same_model = bool(existing and existing.embedding_model == self.embedding_model)
            if (
                existing
                and not force
                and existing.fingerprint == fingerprint
                and (not use_embeddings or (existing_semantic and same_model))
            ):
                return {
                    "meeting_id": meeting_id,
                    "changed": False,
                    "chunk_count": int(existing.chunk_count or 0),
                    "semantic_chunk_count": int(existing.chunk_count or 0) if existing.semantic_ready else 0,
                }

        embeddings: list[list[float] | None] = [None] * len(chunks)
        semantic_ready = False
        if use_embeddings and chunks:
            try:
                vectors = await self._embed([item["text"] for item in chunks])
                if len(vectors) == len(chunks):
                    embeddings = vectors
                    semantic_ready = True
            except Exception as exc:
                print("RAG embedding failed; keeping lexical index:", repr(exc))

        now = datetime.now(timezone.utc)
        with self.storage.database.session_factory.begin() as session:
            session.execute(delete(RAGChunkModel).where(RAGChunkModel.meeting_id == meeting_id))
            for position, (chunk, vector) in enumerate(zip(chunks, embeddings)):
                session.add(
                    RAGChunkModel(
                        meeting_id=meeting_id,
                        chunk_key=f"{chunk['source_type']}:{chunk['source_key']}:{position}",
                        source_type=chunk["source_type"],
                        source_label=chunk["source_label"],
                        slide_number=chunk.get("slide_number"),
                        text=chunk["text"],
                        metadata_json=dict(chunk.get("metadata") or {}),
                        embedding=vector,
                        embedding_model=self.embedding_model if vector is not None else None,
                        created_at=now,
                    )
                )

            state = session.get(RAGMeetingIndexModel, meeting_id)
            if state is None:
                state = RAGMeetingIndexModel(meeting_id=meeting_id)
                session.add(state)
            state.fingerprint = fingerprint
            state.chunk_count = len(chunks)
            state.embedding_model = self.embedding_model if semantic_ready else None
            state.semantic_ready = semantic_ready
            state.indexed_at = now

        return {
            "meeting_id": meeting_id,
            "changed": True,
            "chunk_count": len(chunks),
            "semantic_chunk_count": len(chunks) if semantic_ready else 0,
        }

    async def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        meeting_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        clean_query = re.sub(r"\s+", " ", query).strip()
        if not clean_query:
            raise ValueError("Search query cannot be empty")

        await self.ensure_current()
        requested_k = max(1, min(int(top_k or self.top_k), 20))
        candidate_limit = max(requested_k * 3, self.candidate_k)
        query_embedding: list[float] | None = None
        semantic_used = False
        try:
            if self._model_installed(self.embedding_model, await self._list_models()):
                vectors = await self._embed([clean_query])
                query_embedding = vectors[0] if vectors else None
                semantic_used = query_embedding is not None
        except Exception:
            query_embedding = None

        statement = (
            select(RAGChunkModel, MeetingModel)
            .join(MeetingModel, MeetingModel.id == RAGChunkModel.meeting_id)
            .where(MeetingModel.status == "completed")
        )
        if meeting_ids:
            statement = statement.where(RAGChunkModel.meeting_id.in_(meeting_ids))

        with self.storage.database.session_factory() as session:
            rows = session.execute(statement).all()

        intent = self._query_intent(clean_query)
        cross_meeting = self._is_cross_meeting_query(clean_query)
        cross_overview = self._is_cross_meeting_overview_query(clean_query)
        cross_synthesis = self._is_cross_meeting_synthesis_query(clean_query)
        hits: list[RetrievalHit] = []
        for chunk, meeting in rows:
            lexical = self._lexical_score(clean_query, chunk.text, chunk.source_label, meeting.title)
            semantic: float | None = None
            if query_embedding is not None and chunk.embedding and chunk.embedding_model == self.embedding_model:
                semantic = self._cosine(query_embedding, chunk.embedding)
            if semantic is None:
                score = lexical
            else:
                score = 0.74 * max(0.0, semantic) + 0.26 * lexical
            score += self._source_bonus(chunk.source_type)
            score += self._intent_source_adjustment(intent, chunk.source_type)
            # A broad request such as "compare the topics across all meetings" has
            # few topic-specific lexical anchors. Executive summaries are the safest
            # compact representation for that case, so make them eligible without
            # forcing unrelated transcript chunks into the result set.
            if cross_overview and chunk.source_type == "summary":
                score = max(score, self.min_evidence_score + 0.04)
            if cross_synthesis and chunk.source_type in self._cross_meeting_seed_types(intent):
                score = max(score, self.min_evidence_score + 0.035)
            if score < self.min_score and lexical <= 0:
                continue
            hits.append(
                RetrievalHit(
                    chunk_id=chunk.id,
                    meeting_id=meeting.id,
                    meeting_title=meeting.title,
                    meeting_date=(meeting.start_time.isoformat() if meeting.start_time else None),
                    source_type=chunk.source_type,
                    source_label=chunk.source_label,
                    slide_number=chunk.slide_number,
                    text=chunk.text,
                    score=score,
                    semantic_score=semantic,
                    lexical_score=lexical,
                )
            )

        hits.sort(key=lambda item: item.score, reverse=True)
        # For an explicitly named comparison the candidate set is already scoped
        # to a small number of meetings. Keep all scoped hits so an Executive
        # Summary cannot be pushed below the generic semantic candidate cutoff.
        candidates = hits if (meeting_ids and cross_overview) else hits[:candidate_limit]
        selected = self._select_retrieval_hits(
            candidates,
            requested_k=requested_k,
            cross_meeting=cross_meeting,
            cross_overview=cross_synthesis,
            semantic_used=semantic_used,
            query=clean_query,
        )

        evidence_found, gate_reason = self._evidence_gate(clean_query, selected, semantic_used)
        if not evidence_found:
            selected = []

        return {
            "query": clean_query,
            "semantic_used": semantic_used,
            "embedding_model": self.embedding_model if semantic_used else None,
            "intent": intent,
            "cross_meeting": cross_meeting,
            "cross_meeting_overview": cross_overview,
            "cross_meeting_synthesis": cross_synthesis,
            "cross_meeting_operation": self._cross_meeting_operation(clean_query),
            "meetings_retrieved": self._meeting_names_from_hits(selected),
            "evidence_found": evidence_found,
            "gate_reason": gate_reason,
            "results": [hit.to_dict(f"S{index}") for index, hit in enumerate(selected, start=1)],
        }

    async def ask(
        self,
        question: str,
        *,
        history: list[dict[str, str]] | None = None,
        top_k: int | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        timezone_name: str | None = None,
        meeting_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        clean_question = re.sub(r"\s+", " ", question).strip()
        if not clean_question:
            raise ValueError("Question cannot be empty")

        history = list(history or [])[-8:]
        route = self._route_question(clean_question, history)

        if route == "weather":
            weather = await self._weather_answer(
                clean_question,
                latitude=latitude,
                longitude=longitude,
                timezone_name=timezone_name,
                allow_plain_location=self._is_weather_location_followup(clean_question, history),
            )
            return {
                "answer": weather["answer"],
                "sources": [],
                "evidence_found": False,
                "meeting_evidence_used": False,
                "gate_reason": "live_weather",
                "semantic_used": False,
                "embedding_model": None,
                "route": "weather",
                "route_label": "Live weather",
                "live_data_source": "Open-Meteo",
                "needs_location": bool(weather.get("needs_location", False)),
            }

        if route == "date_time":
            return {
                "answer": self._date_time_answer(clean_question),
                "sources": [],
                "evidence_found": False,
                "meeting_evidence_used": False,
                "gate_reason": "system_clock",
                "semantic_used": False,
                "embedding_model": None,
                "route": "date_time",
                "route_label": "System date/time",
            }

        retrieval_query = self._build_retrieval_query(clean_question, history)

        if route == "meeting_rag" or meeting_ids:
            scoped_meeting_ids = list(meeting_ids or []) or None
            resolved_meetings: list[dict[str, str]] = []
            if not meeting_ids and self._cross_meeting_operation(clean_question) == "comparison":
                resolved_meetings = self._resolve_named_meetings(clean_question)
                # Only scope when at least two distinct named meetings were resolved.
                # Otherwise normal cross-meeting retrieval remains available.
                if len(resolved_meetings) >= 2:
                    scoped_meeting_ids = [item["meeting_id"] for item in resolved_meetings]
            search_result = await self.search(
                retrieval_query,
                top_k=top_k,
                meeting_ids=scoped_meeting_ids,
            )
            search_result["resolved_meetings"] = resolved_meetings
            return await self._answer_from_meeting_evidence(
                clean_question,
                history=history,
                search_result=search_result,
            )

        # General/scientific questions are first probed against the archive.
        # If relevant meeting evidence exists, provide a hybrid answer that
        # clearly separates model knowledge from the user's own meeting record.
        # A small set of high-risk scientific concepts can provide a deterministic
        # canonical answer so the local LLM cannot flip an optimization criterion
        # or improvise a formula.
        canonical_general = self._canonical_scientific_answer(clean_question)
        search_result = await self.search(retrieval_query, top_k=top_k)
        if self._hybrid_evidence_is_useful(retrieval_query, search_result):
            return await self._answer_hybrid(
                clean_question,
                history=history,
                search_result=search_result,
                canonical_general=canonical_general,
            )

        answer = canonical_general or await self._answer_general(clean_question, history=history)
        return {
            "answer": answer,
            "sources": [],
            "evidence_found": False,
            "meeting_evidence_used": False,
            "gate_reason": search_result.get("gate_reason"),
            "semantic_used": search_result.get("semantic_used", False),
            "embedding_model": search_result.get("embedding_model"),
            "route": "general",
            "route_label": "General knowledge",
        }

    async def _answer_from_meeting_evidence(
        self,
        question: str,
        *,
        history: list[dict[str, str]],
        search_result: dict[str, Any],
    ) -> dict[str, Any]:
        raw_sources = list(search_result.get("results") or [])
        cross_meeting = bool(search_result.get("cross_meeting") or self._is_cross_meeting_query(question))
        cross_operation = str(
            search_result.get("cross_meeting_operation")
            or self._cross_meeting_operation(question)
        )
        source_cap = self.max_sources if cross_meeting else (3 if self._query_intent(question) == "goal" else self.max_sources)
        sources = self._prepare_answer_sources(
            question,
            raw_sources,
            max_sources=source_cap,
            drop_technical_terms=(self._query_intent(question) == "goal"),
        )
        if not search_result.get("evidence_found") or not sources:
            return {
                "answer": self._no_evidence_answer(question),
                "sources": [],
                "evidence_found": False,
                "meeting_evidence_used": False,
                "gate_reason": search_result.get("gate_reason"),
                "semantic_used": search_result.get("semantic_used", False),
                "embedding_model": search_result.get("embedding_model"),
                "route": "meeting_rag",
                "route_label": "Meeting archive",
                "cross_meeting": cross_meeting,
                "meetings_used": [],
            }

        if cross_meeting and self._query_intent(question) == "open_question":
            return self._cross_meeting_unresolved_response(
                question,
                sources,
                search_result=search_result,
            )

        if self._is_cross_meeting_method_catalog_query(question, cross_operation):
            return self._cross_meeting_method_taxonomy_response(
                question,
                sources,
                search_result=search_result,
            )

        context = self._format_evidence_context(sources)
        # For a self-contained archive query, previous assistant answers are not
        # evidence and must not leak facts into a new cross-meeting synthesis.
        history_text = (
            self._format_history(history)
            if self._is_contextual_followup(question)
            else ""
        )
        shared_anchors = self._cross_meeting_shared_anchors(sources) if cross_meeting else []
        cross_rules = ""
        if cross_meeting:
            shared_text = ", ".join(shared_anchors) if shared_anchors else "(no strong shared lexical anchor)"
            operation_rule = self._cross_meeting_operation_rule(cross_operation)
            resolved_text = self._resolved_meeting_instruction(search_result.get("resolved_meetings") or [])
            cross_rules = f"""
Cross-meeting query semantics: {cross_operation.upper()}
{operation_rule}
{resolved_text}
Cross-meeting grounding rules:
- Treat each MEETING GROUP as a separate evidence container. A citation may support claims
  ONLY about the meeting named in that source card.
- First establish what each meeting is about from that meeting's own Executive Summary,
  slide summary, or key point when available. Do not define a meeting's main focus from an
  isolated open question, action item, or closing slide.
- Never call multiple sources from one meeting separate "meeting instances".
- When the user asks for a comparison, MeetMind is allowed to derive a comparison from the
  independent evidence. Do NOT require the meetings themselves to have compared one another,
  and do not append a contradictory "no direct comparison" / "no supporting evidence"
  footer after a grounded comparison.
- Claim a shared theme only when that concept is supported in evidence from at least two
  distinct meetings. Strong lexical anchors actually shared across the current evidence:
  {shared_text}
- If there is no strong supported overlap, say so explicitly instead of inventing one.
- Every sentence that names a specific meeting must cite at least one source from that same
  meeting. A sentence comparing two meetings must cite evidence from both meetings.
- When multiple meetings are relevant, write separate bullets or short sections using the exact
  meeting titles from the evidence. Do not hide one meeting behind phrases such as "another
  meeting" or "the other meeting".
"""

        prompt = f"""You are a scientific meeting knowledge assistant.
Answer ONLY from the meeting evidence below. Do not invent facts, names, numbers,
decisions, or conclusions. If the evidence is incomplete, say what is not known.
Cite ONLY the evidence you actually use, using individual citations such as [S1] or [S2].
Do not cite a source merely because it was retrieved. Every factual claim should be
supported by at least one citation. Prefer canonical scientific terminology from the evidence.
If the evidence does not support the question at all, say that no supporting meeting evidence
was found and DO NOT include any citation.
{cross_rules}
Recent chat context:
{history_text or '(none)'}

Current question:
{question}

Retrieved meeting evidence:
{context}

Return a clear, concise Markdown answer with citations. Do not add a separate Sources section;
the interface renders only the source cards that you cite. For mathematical expressions, use
standard LaTeX delimiters: $...$ for inline math and $$...$$ for display math.
"""
        answer = await self._chat(prompt)
        if cross_meeting:
            answer = self._strip_contradictory_cross_meeting_footer(answer)
            answer = self._strip_union_intersection_confusion(answer, cross_operation)
            if not answer.strip() and cross_operation in {"union", "comparison"}:
                answer = self._cross_meeting_grounded_fallback(
                    question, sources, operation=cross_operation
                )
            if cross_operation == "comparison" and self._comparison_needs_grounded_fallback(answer, sources):
                answer = self._cross_meeting_grounded_fallback(
                    question, sources, operation="comparison"
                )
            answer = self._repair_cross_meeting_citations(answer, sources)
            answer = self._ground_uncited_cross_meeting_lines(answer, sources)
            if self._answer_indicates_no_evidence(answer) and cross_operation in {"union", "comparison"}:
                answer = self._cross_meeting_grounded_fallback(
                    question, sources, operation=cross_operation
                )
            answer = self._ensure_cross_meeting_source_coverage(
                answer,
                sources,
                operation=cross_operation,
            )
            if cross_operation == "comparison":
                answer = self._label_comparison_inference(answer)
        answer = self._canonicalize_answer_terms(answer)
        if self._answer_indicates_no_evidence(answer):
            return {
                "answer": self._strip_citations(answer),
                "sources": [],
                "evidence_found": False,
                "meeting_evidence_used": False,
                "gate_reason": "llm_reported_no_evidence",
                "semantic_used": search_result.get("semantic_used", False),
                "embedding_model": search_result.get("embedding_model"),
                "route": "meeting_rag",
                "route_label": "Meeting archive",
                "cross_meeting": cross_meeting,
                "meetings_used": [],
            }

        cited_sources = self._cited_sources(answer, sources)
        answer, cited_sources = self._renumber_citations(answer, cited_sources)
        if cross_meeting and not cited_sources:
            return {
                "answer": self._no_evidence_answer(question),
                "sources": [],
                "evidence_found": False,
                "meeting_evidence_used": False,
                "gate_reason": "cross_meeting_answer_not_grounded",
                "semantic_used": search_result.get("semantic_used", False),
                "embedding_model": search_result.get("embedding_model"),
                "route": "meeting_rag",
                "route_label": "Meeting archive",
                "cross_meeting": True,
                "meetings_used": [],
            }
        return {
            "answer": answer,
            "sources": cited_sources,
            "evidence_found": True,
            "meeting_evidence_used": bool(cited_sources),
            "gate_reason": search_result.get("gate_reason"),
            "semantic_used": search_result.get("semantic_used", False),
            "embedding_model": search_result.get("embedding_model"),
            "route": "meeting_rag",
            "route_label": "Meeting archive",
            "cross_meeting": cross_meeting,
            "cross_meeting_operation": cross_operation if cross_meeting else None,
            "meetings_used": self._meeting_names_from_source_dicts(cited_sources),
        }

    async def _answer_hybrid(
        self,
        question: str,
        *,
        history: list[dict[str, str]],
        search_result: dict[str, Any],
        canonical_general: str | None = None,
    ) -> dict[str, Any]:
        sources = self._prepare_answer_sources(
            question,
            list(search_result.get("results") or []),
            max_sources=3,
            drop_technical_terms=True,
        )
        context = self._format_evidence_context(sources)
        history_text = self._format_history(history)

        if canonical_general:
            meeting_prompt = f"""You are a scientific meeting knowledge assistant.
The general scientific answer has already been generated separately and is authoritative.
Do NOT repeat, alter, correct, or replace it. Write ONLY a short paragraph beginning exactly
with `From your meetings:` using the evidence below. Mention only meeting-specific usage or
context that directly helps answer the current question. Cite every meeting claim as [S1], [S2],
etc. Prefer the smallest sufficient evidence set. Do not add a Sources section.

Current question:
{question}

Retrieved meeting evidence:
{context}
"""
            meeting_answer = await self._chat_general(meeting_prompt)
            if self._answer_indicates_no_evidence(meeting_answer):
                return {
                    "answer": canonical_general,
                    "sources": [],
                    "evidence_found": False,
                    "meeting_evidence_used": False,
                    "gate_reason": "canonical_general_only",
                    "semantic_used": search_result.get("semantic_used", False),
                    "embedding_model": search_result.get("embedding_model"),
                    "route": "general",
                    "route_label": "General knowledge",
                }
            cited_sources = self._cited_sources(meeting_answer, sources)
            meeting_answer, cited_sources = self._renumber_citations(meeting_answer, cited_sources)
            if not cited_sources:
                return {
                    "answer": canonical_general,
                    "sources": [],
                    "evidence_found": False,
                    "meeting_evidence_used": False,
                    "gate_reason": "canonical_general_only",
                    "semantic_used": search_result.get("semantic_used", False),
                    "embedding_model": search_result.get("embedding_model"),
                    "route": "general",
                    "route_label": "General knowledge",
                }
            if not meeting_answer.lstrip().casefold().startswith("from your meetings:"):
                meeting_answer = "From your meetings: " + meeting_answer.lstrip()
            return {
                "answer": f"General context:\n{canonical_general}\n\n{meeting_answer}",
                "sources": cited_sources,
                "evidence_found": True,
                "meeting_evidence_used": True,
                "gate_reason": search_result.get("gate_reason"),
                "semantic_used": search_result.get("semantic_used", False),
                "embedding_model": search_result.get("embedding_model"),
                "route": "hybrid",
                "route_label": "General knowledge + meeting archive",
            }

        scientific_reference = self._scientific_reference(question)
        prompt = f"""You are a local scientific assistant with access to the user's meeting archive.
Answer the question using BOTH your general scientific knowledge and the meeting evidence
when the meeting evidence adds useful context. Keep the two kinds of information clearly
distinguishable.

Rules:
- General scientific knowledge does NOT need a meeting citation.
- Any statement about what happened, was used, was concluded, or was discussed in the
  user's meetings MUST be grounded in the meeting evidence and cited as [S1], [S2], etc.
- Cite only evidence you actually use. Do not cite retrieved-but-unused chunks.
- Prefer the smallest sufficient evidence set (normally 1-3 meeting citations).
- Do not cite a Technical Terms list when a slide, transcript, key point, or summary
  directly supports the same statement.
- Do not invent meeting facts.
- Do not introduce a mathematical formula unless the user asks for one, a formula is part of
  the standard definition of the requested mathematical object, or it is genuinely necessary.
  Never guess or improvise an equation. When prose is sufficient, prefer prose.
- Use precise scientific terminology: do not conflate within-class/intra-class quantities with
  between-class/inter-class quantities, minimization with maximization, or related criteria.
- Prefer this structure when both parts are useful:
  General context: ...

  From your meetings: ... [S1]
- If the meeting evidence adds nothing useful, answer only from general knowledge and
  do not include citations.

Authoritative scientific note for this question:
{scientific_reference or '(none)'}

Recent chat context:
{history_text or '(none)'}

Current question:
{question}

Retrieved meeting evidence:
{context}

Return concise Markdown. Do not add a separate Sources section. For mathematical expressions,
use $...$ for inline math and $$...$$ for display math.
"""
        answer = await self._chat_general(prompt)
        if self._answer_indicates_no_evidence(answer):
            return {
                "answer": self._strip_citations(answer),
                "sources": [],
                "evidence_found": False,
                "meeting_evidence_used": False,
                "gate_reason": "llm_reported_no_evidence",
                "semantic_used": search_result.get("semantic_used", False),
                "embedding_model": search_result.get("embedding_model"),
                "route": "hybrid",
                "route_label": "General knowledge + meeting archive",
            }
        cited_sources = self._cited_sources(answer, sources)
        answer, cited_sources = self._renumber_citations(answer, cited_sources)
        return {
            "answer": answer,
            "sources": cited_sources,
            "evidence_found": bool(sources),
            "meeting_evidence_used": bool(cited_sources),
            "gate_reason": search_result.get("gate_reason"),
            "semantic_used": search_result.get("semantic_used", False),
            "embedding_model": search_result.get("embedding_model"),
            "route": "hybrid",
            "route_label": "General knowledge + meeting archive",
        }

    async def _answer_general(
        self,
        question: str,
        *,
        history: list[dict[str, str]],
    ) -> str:
        history_text = self._format_history(history)
        equation_policy = self._equation_policy(question)
        scientific_reference = self._scientific_reference(question)
        prompt = f"""You are a concise scientific assistant running locally.
Answer the user's question from general knowledge. Do not pretend the answer came from
the user's meetings. Do not invent meeting citations such as [S1]. If the question is
scientific, explain it accurately and clearly at a level useful to a researcher. Be conservative
with formulas: never invent or improvise an equation, and use precise scientific terminology.
In particular, do not conflate within-class/intra-class quantities with between-class/inter-class
quantities, minimization with maximization, or related optimization criteria.

Equation policy for this question: {equation_policy}

Authoritative scientific note for this question:
{scientific_reference or '(none)'}
When an authoritative note is present, follow it exactly and do not contradict it.

Default to a compact answer: usually 2-4 short paragraphs or up to 8 bullets. Expand only
when the user explicitly asks for detail, derivation, or a long explanation. Use Markdown
for structure. Use $...$ only for short inline symbols. Put important equations on their own
lines as display math, with a blank line before and after and $$...$$ delimiters. For example:

$$
F(\\omega)=\\int_{{-\\infty}}^{{\\infty}} f(t)e^{{-i\\omega t}}\\,\\mathrm{{d}}t
$$

Never show bare LaTeX commands such as \\frac or \\int outside math delimiters. Prefer clear
TeX notation such as \\hat{{f}}(\\omega), \\frac{{1}}{{2\\pi}}, and \\mathrm{{d}}t so equations
are readable when rendered.

Recent chat context:
{history_text or '(none)'}

Question:
{question}
"""
        return await self._chat_general(prompt)

    @staticmethod
    def _compact_answer_sources(
        sources: list[dict[str, Any]],
        *,
        max_sources: int,
        drop_technical_terms: bool,
    ) -> list[dict[str, Any]]:
        if not sources:
            return []
        working = list(sources)
        if drop_technical_terms and any(str(item.get("source_type") or "") != "technical_terms" for item in working):
            working = [item for item in working if str(item.get("source_type") or "") != "technical_terms"]

        selected: list[dict[str, Any]] = []
        seen_text: set[str] = set()
        for item in working:
            excerpt = re.sub(r"\s+", " ", str(item.get("excerpt") or "")).strip().casefold()
            signature = excerpt[:220]
            if signature and signature in seen_text:
                continue
            if signature:
                seen_text.add(signature)
            selected.append(item)
            if len(selected) >= max_sources:
                break
        return selected

    @classmethod
    def _prepare_answer_sources(
        cls,
        question: str,
        sources: list[dict[str, Any]],
        *,
        max_sources: int,
        drop_technical_terms: bool,
    ) -> list[dict[str, Any]]:
        working = cls._compact_answer_sources(
            sources,
            max_sources=max(max_sources + 2, max_sources),
            drop_technical_terms=drop_technical_terms,
        )
        intent = cls._query_intent(question)
        cross_meeting = cls._is_cross_meeting_query(question)
        if (intent == "goal" or cross_meeting) and not cls._asks_about_closing_or_qna(question):
            non_closing = [item for item in working if not cls._is_closing_source(item)]
            if non_closing:
                working = non_closing
        if cross_meeting and any(str(item.get("source_type") or "") != "technical_terms" for item in working):
            working = [item for item in working if str(item.get("source_type") or "") != "technical_terms"]
        if cross_meeting and intent == "open_question":
            issue_sources = [
                item for item in working
                if str(item.get("source_type") or "") in {"open_question", "discussion_qa"}
                and cls._source_is_unresolved_issue(item)
            ]
            if issue_sources:
                working = cls._deduplicate_issue_sources(issue_sources)
        elif cross_meeting and intent == "action_item":
            action_sources = [
                item for item in working
                if str(item.get("source_type") or "") == "action_item"
            ]
            if action_sources:
                working = action_sources
        elif cross_meeting and intent == "decision":
            decision_sources = [
                item for item in working
                if str(item.get("source_type") or "") == "decision"
            ]
            if decision_sources:
                working = decision_sources
        if cross_meeting:
            operation = cls._cross_meeting_operation(question)
            if operation in {"union", "comparison"}:
                working = cls._prioritize_cross_meeting_sources(working, operation=operation)
            working = cls._diversify_source_dicts(working, max_sources=max_sources)
        return working[:max_sources]

    @staticmethod
    def _meeting_names_from_source_dicts(sources: list[dict[str, Any]]) -> list[str]:
        names: list[str] = []
        for source in sources:
            name = str(source.get("meeting_title") or "").strip()
            if name and name not in names:
                names.append(name)
        return names

    @staticmethod
    def _meeting_names_from_hits(hits: list[RetrievalHit]) -> list[str]:
        names: list[str] = []
        for hit in hits:
            if hit.meeting_title and hit.meeting_title not in names:
                names.append(hit.meeting_title)
        return names

    @classmethod
    def _prioritize_cross_meeting_sources(
        cls,
        sources: list[dict[str, Any]],
        *,
        operation: str,
    ) -> list[dict[str, Any]]:
        """Prefer representative evidence before enforcing meeting diversity."""
        if not sources:
            return []
        priority = {
            "summary": 0,
            "slide_summary": 1,
            "key_point": 2,
            "decision": 3,
            "action_item": 3,
            "open_question": 3,
            "discussion_qa": 4,
            "transcript": 5,
            "technical_terms": 8,
        }
        if operation == "union":
            # Union questions may ask for methods/techniques. Executive summaries
            # usually provide the safest compact catalogue for each meeting.
            priority = dict(priority)
            priority["key_point"] = 1
            priority["slide_summary"] = 2

        indexed = list(enumerate(sources))
        indexed.sort(key=lambda pair: (
            priority.get(str(pair[1].get("source_type") or ""), 6),
            -float(pair[1].get("lexical_score") or 0.0),
            -float(pair[1].get("score") or 0.0),
            pair[0],
        ))
        return [item for _, item in indexed]

    @staticmethod
    def _preferred_cross_source(sources: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not sources:
            return None
        priority = {
            "summary": 0,
            "key_point": 1,
            "slide_summary": 2,
            "decision": 3,
            "action_item": 3,
            "open_question": 3,
            "discussion_qa": 4,
            "transcript": 5,
            "technical_terms": 8,
        }
        return min(
            sources,
            key=lambda source: (
                priority.get(str(source.get("source_type") or ""), 6),
                -float(source.get("lexical_score") or 0.0),
                -float(source.get("score") or 0.0),
            ),
        )

    @classmethod
    def _diversify_source_dicts(
        cls,
        sources: list[dict[str, Any]],
        *,
        max_sources: int,
    ) -> list[dict[str, Any]]:
        if not sources:
            return []
        by_meeting: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for source in sources:
            meeting_id = str(source.get("meeting_id") or source.get("meeting_title") or "")
            if meeting_id not in by_meeting:
                by_meeting[meeting_id] = []
                order.append(meeting_id)
            by_meeting[meeting_id].append(source)
        if len(by_meeting) <= 1:
            return sources[:max_sources]

        selected: list[dict[str, Any]] = []
        # First pass: one strongest source from every represented meeting.
        for meeting_id in order:
            bucket = by_meeting[meeting_id]
            if bucket and len(selected) < max_sources:
                selected.append(bucket[0])
        # Second pass: fill remaining capacity in original rank order.
        for source in sources:
            if len(selected) >= max_sources:
                break
            if source not in selected:
                selected.append(source)
        return selected

    @classmethod
    def _deduplicate_issue_sources(
        cls,
        sources: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge duplicate/near-duplicate unresolved-question evidence per meeting.

        Summaries often expose the same unresolved issue twice: once as an
        ``open_question`` and once as a ``discussion_qa`` entry. Cross-meeting
        synthesis should count that as one issue, not as two meeting instances.
        """
        if not sources:
            return []

        selected: list[dict[str, Any]] = []
        for source in sources:
            meeting_key = str(source.get("meeting_id") or source.get("meeting_title") or "")
            issue_text = cls._issue_text(source)
            duplicate_index: int | None = None
            for index, existing in enumerate(selected):
                existing_meeting = str(existing.get("meeting_id") or existing.get("meeting_title") or "")
                if existing_meeting != meeting_key:
                    continue
                if cls._issue_similarity(issue_text, cls._issue_text(existing)) >= 0.40:
                    duplicate_index = index
                    break
            if duplicate_index is None:
                selected.append(source)
                continue

            existing = selected[duplicate_index]
            if cls._issue_source_quality(source) > cls._issue_source_quality(existing):
                selected[duplicate_index] = source
        return selected

    @staticmethod
    def _source_is_unresolved_issue(source: dict[str, Any]) -> bool:
        source_type = str(source.get("source_type") or "")
        if source_type == "open_question":
            return True
        if source_type != "discussion_qa":
            return False
        excerpt = str(source.get("excerpt") or "").casefold()
        if "status:" not in excerpt:
            return True
        return "status: unresolved" in excerpt or "status: open" in excerpt

    @staticmethod
    def _issue_text(source: dict[str, Any]) -> str:
        text = re.sub(r"\s+", " ", str(source.get("excerpt") or "")).strip()
        if str(source.get("source_type") or "") == "discussion_qa":
            match = re.search(r"Question:\s*(.*?)(?:\s+Status:|\s+Answer:|$)", text, flags=re.IGNORECASE)
            if match:
                text = match.group(1).strip()
        return text

    @classmethod
    def _issue_similarity(cls, left: str, right: str) -> float:
        left_tokens = set(cls._content_tokens(left))
        right_tokens = set(cls._content_tokens(right))
        if not left_tokens or not right_tokens:
            return 0.0
        if left.casefold() in right.casefold() or right.casefold() in left.casefold():
            return 1.0
        intersection = len(left_tokens & right_tokens)
        containment = intersection / max(1, min(len(left_tokens), len(right_tokens)))
        jaccard = intersection / max(1, len(left_tokens | right_tokens))
        return max(containment, jaccard)

    @staticmethod
    def _issue_source_quality(source: dict[str, Any]) -> int:
        source_type = str(source.get("source_type") or "")
        excerpt = str(source.get("excerpt") or "").casefold()
        if source_type == "discussion_qa" and ("answer:" in excerpt or "status:" in excerpt):
            return 4
        if source_type == "open_question":
            return 3
        if source_type == "discussion_qa":
            return 2
        return 1

    @classmethod
    def _cross_meeting_shared_anchors(
        cls,
        sources: list[dict[str, Any]],
    ) -> list[str]:
        """Return conservative lexical anchors present in at least two meetings."""
        by_meeting: dict[str, set[str]] = {}
        for source in sources:
            meeting_key = str(source.get("meeting_id") or source.get("meeting_title") or "")
            if not meeting_key:
                continue
            tokens = set(cls._content_tokens(
                f"{source.get('source_label', '')} {source.get('excerpt', '')}"
            ))
            by_meeting.setdefault(meeting_key, set()).update(tokens)
        if len(by_meeting) < 2:
            return []
        counts: dict[str, int] = {}
        for tokens in by_meeting.values():
            for token in tokens:
                counts[token] = counts.get(token, 0) + 1
        generic = {
            "data", "used", "using", "results", "method", "methods", "approach",
            "pipeline", "analysis", "image", "images", "scientific", "discussion",
            "meeting", "summary", "slide", "question", "questions",
        }
        shared = [
            token for token, count in counts.items()
            if count >= 2 and token not in generic and len(token) >= 3
        ]
        shared.sort(key=lambda token: (-counts[token], -len(token), token))
        return shared[:12]

    @staticmethod
    def _cross_meeting_operation(query: str) -> str:
        """Classify the semantics of a multi-meeting request.

        `across` means a union by default. Only explicit words such as shared,
        common, both, or overlap request an intersection. Named comparisons are
        handled separately so the model does not accidentally turn a comparison
        into an overlap search.
        """
        q = re.sub(r"\s+", " ", query.casefold()).strip()
        if "compare" in q or re.search(r"\b(?:versus|vs\.?)\b", q):
            return "comparison"
        if any(marker in q for marker in (
            "which meeting", "which meetings", "where was", "where were",
        )):
            return "membership"
        if any(marker in q for marker in (
            "shared", "common", "in common", "both meetings", "both of the meetings",
            "overlap", "same method", "same methods", "same technique", "same techniques",
            "jointly discussed", "present in both",
        )):
            return "intersection"
        if any(marker in q for marker in (
            "across", "all meetings", "our meetings", "different meetings",
            "summarize all", "summary of all", "topics across", "methods across",
            "techniques across", "approaches across",
        )):
            return "union"
        return "membership"

    @staticmethod
    def _cross_meeting_operation_rule(operation: str) -> str:
        if operation == "union":
            return (
                "UNION semantics: collect the relevant items found in EACH meeting. "
                "Do not require an item to be shared by every meeting. Organize the answer "
                "by meeting when useful, then optionally summarize the union. Do not answer "
                "a UNION question by saying there is no common/overlapping method."
            )
        if operation == "intersection":
            return (
                "INTERSECTION semantics: report only themes/methods supported in at least two "
                "distinct meetings. If no shared item is supported, say that clearly."
            )
        if operation == "comparison":
            return (
                "COMPARISON semantics: first state the documented focus of each named/retrieved "
                "meeting separately, with that meeting's citation. Then compare similarities and "
                "differences. A similarity may be asserted only when evidence from both meetings "
                "supports it; differences do not require a shared topic. Label the synthesized comparison "
                "as an evidence-based MeetMind inference so it is not confused with a statement made inside either meeting."
            )
        return (
            "MEMBERSHIP semantics: identify only the meetings whose own evidence directly matches "
            "the requested topic. Do not add unrelated meetings for diversity."
        )

    @staticmethod
    def _resolved_meeting_instruction(resolved: list[dict[str, str]]) -> str:
        if len(resolved) < 2:
            return ""
        names = ", ".join(str(item.get("meeting_title") or "") for item in resolved)
        return (
            "Named-meeting resolver: the user explicitly referred to these meetings: "
            f"{names}. Use these exact titles in the comparison and do not reinterpret parts "
            "of the question as meeting names."
        )

    @staticmethod
    def _normalize_meeting_phrase(text: str) -> str:
        text = text.replace("’", "'").casefold()
        text = re.sub(r"\[\s*demo\s*\]", " demo ", text, flags=re.IGNORECASE)
        text = re.sub(r"'s\b", " s ", text)
        return re.sub(r"[^a-z0-9]+", " ", text).strip()

    @classmethod
    def _meeting_aliases(cls, title: str) -> list[str]:
        raw = str(title or "").strip()
        if not raw:
            return []
        is_demo = bool(re.search(r"\[\s*demo\s*\]", raw, flags=re.IGNORECASE))
        core = re.sub(r"\[\s*demo\s*\]", " ", raw, flags=re.IGNORECASE)
        core_norm = cls._normalize_meeting_phrase(core)
        tokens = core_norm.split()
        aliases: set[str] = {core_norm, f"{core_norm} meeting", f"{core_norm} talk"}

        generic = {
            "meeting", "talk", "presentation", "demo", "near", "field", "reconstruction",
            "update", "discussion", "session", "the", "a", "an",
        }
        meaningful = [token for token in tokens if token not in generic and not token.isdigit()]

        # Short person-like titles such as "shahin 5" are commonly referenced
        # as "Shahin's meeting" or "Shahin's talk".
        if tokens:
            first = tokens[0]
            if first not in generic and first.isalpha() and len(first) >= 3:
                aliases.update({
                    first,
                    f"{first} meeting",
                    f"{first} s meeting",
                    f"{first} talk",
                    f"{first} s talk",
                    f"{first} presentation",
                    f"{first} s presentation",
                })

        if is_demo:
            aliases.update({"demo meeting", "demo talk"})
            for token in meaningful:
                if len(token) >= 5:
                    aliases.update({
                        f"{token} demo",
                        f"{token} demo meeting",
                        f"demo {token}",
                        f"demo {token} meeting",
                        f"{token} meeting",
                    })
            if "holography" in tokens:
                aliases.update({
                    "holography demo", "holography demo meeting",
                    "demo holography", "demo holography meeting",
                    "holography meeting", "holography talk",
                })

        normalized = {cls._normalize_meeting_phrase(alias) for alias in aliases}
        return sorted((alias for alias in normalized if alias), key=lambda value: (-len(value.split()), -len(value), value))

    def _resolve_named_meetings(self, question: str) -> list[dict[str, str]]:
        """Resolve natural aliases in an explicit named comparison to meeting IDs."""
        if self._cross_meeting_operation(question) != "comparison":
            return []
        query_norm = self._normalize_meeting_phrase(question)
        listing = self.storage.list_meetings(limit=100)
        candidates: list[tuple[int, int, dict[str, str]]] = []
        for meeting in listing.get("items", []):
            if str(meeting.get("status") or "").casefold() != "completed":
                continue
            title = str(meeting.get("title") or "").strip()
            meeting_id = str(meeting.get("meeting_id") or meeting.get("id") or "").strip()
            best_alias = ""
            best_pos = 10**9
            for alias in self._meeting_aliases(title):
                match = re.search(rf"\b{re.escape(alias)}\b", query_norm)
                if not match:
                    continue
                if (len(alias.split()), len(alias)) > (len(best_alias.split()), len(best_alias)):
                    best_alias = alias
                    best_pos = match.start()
            if not best_alias or not meeting_id:
                continue
            score = len(best_alias.split()) * 100 + len(best_alias)
            candidates.append((best_pos, -score, {
                "meeting_id": meeting_id,
                "meeting_title": title,
                "matched_alias": best_alias,
            }))

        candidates.sort(key=lambda item: (item[0], item[1]))
        resolved: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for _, _, payload in candidates:
            if payload["meeting_id"] in seen_ids:
                continue
            seen_ids.add(payload["meeting_id"])
            resolved.append(payload)
        return resolved

    @staticmethod
    def _is_cross_meeting_method_catalog_query(question: str, operation: str) -> bool:
        """Return True for union-style catalogues of scientific methods/techniques.

        These questions need taxonomy rather than a prose overlap judgement. In particular,
        metrics (SSIM/PSNR/FRC) must not be presented as reconstruction methods, and supporting
        data-generation steps should be distinguished from image-processing operations.
        """
        if operation != "union":
            return False
        q = question.casefold()
        return any(term in q for term in (
            "method", "methods", "technique", "techniques", "approach", "approaches",
            "image-processing", "image processing", "reconstruction", "processing methods",
        ))

    def _cross_meeting_method_taxonomy_response(
        self,
        question: str,
        sources: list[dict[str, Any]],
        *,
        search_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a deterministic evidence-grounded method catalogue grouped by meeting."""
        del question  # semantics were already checked by the caller
        grouped: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for source in sources:
            key = str(source.get("meeting_id") or source.get("meeting_title") or "")
            if not key:
                continue
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(source)

        taxonomy: tuple[tuple[str, tuple[tuple[str, tuple[str, ...]], ...]], ...] = (
            ("Reconstruction / image formation", (
                ("Fresnel propagation", (r"\bfresnel\b",)),
                ("Phase retrieval", (r"\bphase retrieval\b",)),
                ("Tomographic reconstruction", (r"\btomographic reconstruction\b", r"\btomography reconstruction\b")),
                ("Ptychographic reconstruction", (r"\bptychograph(?:y|ic)\b",)),
            )),
            ("Image processing / segmentation", (
                ("Otsu segmentation", (r"\botsu\b",)),
                ("Connected-component labeling", (r"\bconnected[- ]components?\b", r"\bconnected[- ]component labeling\b")),
                ("Denoising", (r"\bdenois(?:e|ed|ing)\b",)),
                ("Image registration", (r"\bimage registration\b", r"\bregistration\b")),
                ("Filtering", (r"\bfiltering\b", r"\bfilter\b")),
            )),
            ("Synthetic-data / projection generation", (
                ("Data augmentation", (r"\bdata augmentation\b",)),
                ("Random component reassembly", (r"\brandom (?:component )?reassembly\b", r"\brandomly reassembl", r"\brandom assembly\b")),
                ("ASTRA Toolbox projection generation", (r"\bastra toolbox\b", r"\bastra\b")),
                ("Synthetic stereo X-ray projection generation", (r"\bsynthetic stereo x[- ]ray projections?\b", r"\bstereo x[- ]ray projections?\b")),
            )),
            ("Machine learning / modeling", (
                ("CNN-based modeling", (r"\bcnn(?:s)?\b", r"\bconvolutional neural network",)),
            )),
            ("Evaluation metrics", (
                ("SSIM", (r"\bssim\b",)),
                ("PSNR", (r"\bpsnr\b",)),
                ("FRC", (r"\bfrc\b",)),
                ("MAE", (r"\bmae\b",)),
                ("RMSE", (r"\brmse\b",)),
            )),
        )

        lines = [
            "The methods and supporting analysis tools discussed across the meetings are grouped below. "
            "Evaluation metrics are listed separately so they are not confused with reconstruction or image-processing methods."
        ]
        used_source_ids: list[str] = []
        represented_meetings: list[str] = []

        for key in order:
            meeting_sources = grouped[key]
            if not meeting_sources:
                continue
            title = str(meeting_sources[0].get("meeting_title") or "Untitled meeting")
            categories: list[tuple[str, list[tuple[str, str]]]] = []
            for category, entries in taxonomy:
                found: list[tuple[str, str]] = []
                for label, patterns in entries:
                    matched_source: dict[str, Any] | None = None
                    for source in meeting_sources:
                        haystack = f"{source.get('source_label', '')} {source.get('excerpt', '')}".casefold()
                        if any(re.search(pattern, haystack, flags=re.IGNORECASE) for pattern in patterns):
                            matched_source = source
                            break
                    if matched_source is not None:
                        source_id = str(matched_source.get("source_id") or "")
                        found.append((label, source_id))
                        if source_id and source_id not in used_source_ids:
                            used_source_ids.append(source_id)
                if found:
                    categories.append((category, found))
            if not categories:
                continue
            represented_meetings.append(title)
            lines.append(f"\n### {title}")
            for category, found in categories:
                rendered = []
                for label, source_id in found:
                    rendered.append(f"{label} [{source_id}]" if source_id else label)
                lines.append(f"- **{category}:** " + "; ".join(rendered))

        if not represented_meetings:
            return {
                "answer": "No supporting meeting evidence was found for image-processing or reconstruction methods.",
                "sources": [],
                "evidence_found": False,
                "meeting_evidence_used": False,
                "gate_reason": "no_method_taxonomy_evidence",
                "semantic_used": search_result.get("semantic_used", False),
                "embedding_model": search_result.get("embedding_model"),
                "route": "meeting_rag",
                "route_label": "Meeting archive",
                "cross_meeting": True,
                "cross_meeting_operation": "union",
                "meetings_used": [],
            }

        answer = self._canonicalize_answer_terms("\n".join(lines))
        cited = self._cited_sources(answer, sources)
        answer, cited = self._renumber_citations(answer, cited)
        return {
            "answer": answer,
            "sources": cited,
            "evidence_found": True,
            "meeting_evidence_used": bool(cited),
            "gate_reason": search_result.get("gate_reason"),
            "semantic_used": search_result.get("semantic_used", False),
            "embedding_model": search_result.get("embedding_model"),
            "route": "meeting_rag",
            "route_label": "Meeting archive",
            "cross_meeting": True,
            "cross_meeting_operation": "union",
            "meetings_used": self._meeting_names_from_source_dicts(cited),
        }

    @staticmethod
    def _canonicalize_answer_terms(answer: str) -> str:
        """Normalize a small set of high-value scientific spellings in generated prose."""
        if not answer:
            return answer
        replacements = (
            (r"(?<!\w)Ots[-–—]?(?=\s*(?:segmentation|threshold|method))", "Otsu"),
            (r"\bOtsu[-–—]\s*(?=and\b)", "Otsu "),
            (r"\bAstra Toolbox\b", "ASTRA Toolbox"),
            (r"\bSsim\b", "SSIM"),
            (r"\bPsnr\b", "PSNR"),
            (r"\bFrc\b", "FRC"),
        )
        cleaned = answer
        for pattern, replacement in replacements:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
        return cleaned

    @staticmethod
    def _label_comparison_inference(answer: str) -> str:
        """Make it explicit that cross-meeting comparison prose is a MeetMind synthesis."""
        if not answer:
            return answer
        if "meetmind inference" in answer.casefold():
            return answer
        patterns = (
            r"(?im)^\s*\*\*comparison\*\*\s*:?\s*",
            r"(?im)^\s*#{1,6}\s+comparison\s*:?[ \t]*",
            r"(?im)^\s*comparison\s*:\s*",
        )
        for pattern in patterns:
            updated, count = re.subn(
                pattern,
                "**Evidence-based comparison (MeetMind inference):** ",
                answer,
                count=1,
            )
            if count:
                return updated
        # If the model did not add a comparison heading, keep the answer untouched;
        # the prompt still tells it to label inferred synthesis and deterministic
        # fallbacks already explain their derived nature.
        return answer

    @classmethod
    def _strip_union_intersection_confusion(cls, answer: str, operation: str) -> str:
        if operation != "union" or not answer:
            return answer
        lower = answer.casefold()
        confusion_markers = (
            "no method is jointly discussed",
            "no methods are jointly discussed",
            "no strong supported overlap",
            "no shared method",
            "no shared methods",
            "no common method",
            "no common methods",
        )
        if any(marker in lower for marker in confusion_markers):
            # A UNION request asks what exists anywhere in the meetings. If the
            # model answers an INTERSECTION question instead, discard that answer
            # and let the grounded fallback rebuild it from per-meeting evidence.
            return ""
        return answer

    @classmethod
    def _cross_meeting_grounded_fallback(
        cls,
        question: str,
        sources: list[dict[str, Any]],
        *,
        operation: str,
    ) -> str:
        if not sources:
            return ""
        by_meeting: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for source in sources:
            key = str(source.get("meeting_id") or source.get("meeting_title") or "")
            if key not in by_meeting:
                by_meeting[key] = []
                order.append(key)
            by_meeting[key].append(source)

        if operation == "comparison":
            lines = ["The retrieved evidence supports this comparison:"]
        else:
            lines = ["Relevant evidence across the meetings:"]
        for key in order:
            source = cls._preferred_cross_source(by_meeting[key]) or by_meeting[key][0]
            title = str(source.get("meeting_title") or "Untitled meeting")
            excerpt = re.sub(r"\s+", " ", str(source.get("excerpt") or "")).strip()
            if len(excerpt) > 360:
                excerpt = excerpt[:357].rstrip() + "..."
            lines.append(f"- **{title}:** {excerpt} [{source.get('source_id')}]" )
        if operation == "comparison":
            lines.append(
                "The comparison above is derived from each meeting's own evidence; no additional "
                "shared theme is asserted unless it is supported in both meetings."
            )
        return "\n".join(lines)

    @classmethod
    def _ensure_cross_meeting_source_coverage(
        cls,
        answer: str,
        sources: list[dict[str, Any]],
        *,
        operation: str,
    ) -> str:
        """Guarantee at least one visible citation from every relevant meeting.

        UNION and COMPARISON answers necessarily synthesize more than one meeting.
        A small LLM may correctly mention both but cite only one. We preserve the
        generated prose and append a compact evidence line for each missing meeting.
        """
        if operation not in {"union", "comparison"} or not sources:
            return answer
        groups: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for source in sources:
            key = str(source.get("meeting_id") or source.get("meeting_title") or "")
            if not key:
                continue
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(source)
        if len(groups) <= 1:
            return answer

        cited_ids = set(cls._extract_citation_ids(answer))
        cited_meetings = {
            str(source.get("meeting_id") or source.get("meeting_title") or "")
            for source in sources
            if str(source.get("source_id") or "") in cited_ids
        }
        missing = [key for key in order if key not in cited_meetings]
        if not missing:
            return answer

        additions = ["### Evidence by meeting"]
        for key in missing:
            source = cls._preferred_cross_source(groups[key]) or groups[key][0]
            title = str(source.get("meeting_title") or "Untitled meeting")
            excerpt = re.sub(r"\s+", " ", str(source.get("excerpt") or "")).strip()
            if len(excerpt) > 260:
                excerpt = excerpt[:257].rstrip() + "..."
            additions.append(f"- **{title}:** {excerpt} [{source.get('source_id')}]" )
        prefix = answer.strip()
        return (prefix + "\n\n" if prefix else "") + "\n".join(additions)

    @classmethod
    def _comparison_needs_grounded_fallback(
        cls,
        answer: str,
        sources: list[dict[str, Any]],
    ) -> bool:
        if not answer.strip() or not sources:
            return True
        groups: dict[str, str] = {}
        for source in sources:
            key = str(source.get("meeting_id") or source.get("meeting_title") or "")
            if key:
                groups[key] = str(source.get("meeting_title") or key)
        if len(groups) < 2:
            return False
        mentioned = set(cls._mentioned_meeting_keys(answer, groups))
        if len(mentioned) < len(groups):
            return True
        vague = answer.casefold()
        return "another meeting" in vague or "the other meeting" in vague

    def _cross_meeting_unresolved_response(
        self,
        question: str,
        sources: list[dict[str, Any]],
        *,
        search_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Deterministic unresolved-question synthesis after per-meeting dedup."""
        issue_sources = [
            source for source in sources
            if str(source.get("source_type") or "") in {"open_question", "discussion_qa"}
            and self._source_is_unresolved_issue(source)
        ]
        issue_sources = self._deduplicate_issue_sources(issue_sources)
        if not issue_sources:
            return {
                "answer": self._no_evidence_answer(question),
                "sources": [],
                "evidence_found": False,
                "meeting_evidence_used": False,
                "gate_reason": "no_unresolved_issue_evidence",
                "semantic_used": search_result.get("semantic_used", False),
                "embedding_model": search_result.get("embedding_model"),
                "route": "meeting_rag",
                "route_label": "Meeting archive",
                "cross_meeting": True,
                "cross_meeting_operation": "union",
                "meetings_used": [],
            }

        lines = ["The unresolved questions across the meetings are:"]
        for source in issue_sources:
            issue = self._issue_text(source).strip().rstrip(" .?!")
            title = str(source.get("meeting_title") or "Untitled meeting")
            lines.append(f"- **{title}:** {issue}? [{source.get('source_id')}]" )
        answer = "\n".join(lines)
        cited = self._cited_sources(answer, issue_sources)
        answer, cited = self._renumber_citations(answer, cited)
        return {
            "answer": answer,
            "sources": cited,
            "evidence_found": True,
            "meeting_evidence_used": True,
            "gate_reason": search_result.get("gate_reason"),
            "semantic_used": search_result.get("semantic_used", False),
            "embedding_model": search_result.get("embedding_model"),
            "route": "meeting_rag",
            "route_label": "Meeting archive",
            "cross_meeting": True,
            "cross_meeting_operation": "union",
            "meetings_used": self._meeting_names_from_source_dicts(cited),
        }

    @staticmethod
    def _strip_contradictory_cross_meeting_footer(answer: str) -> str:
        """Remove a no-evidence footer when a grounded comparison already exists."""
        if not _CITATION_RE.search(answer):
            return answer
        patterns = (
            r"No supporting meeting evidence was found[^.\n]*(?:directly )?compar[^.\n]*\.?",
            r"No direct comparison[^.\n]*(?:was|is) (?:made|present|available|found)[^.\n]*\.?",
            r"The (?:retrieved )?evidence does not directly compare[^.\n]*\.?",
        )
        cleaned = answer
        for pattern in patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @classmethod
    def _repair_cross_meeting_citations(
        cls,
        answer: str,
        sources: list[dict[str, Any]],
    ) -> str:
        """Bind meeting-named claims to sources from that same meeting.

        Small local LLMs occasionally attach a syntactically valid citation to the
        wrong meeting after cross-meeting synthesis. This audit repairs that mapping
        from the source metadata before citations are exposed to the UI.
        """
        if not answer or not sources:
            return answer

        groups: dict[str, list[dict[str, Any]]] = {}
        titles: dict[str, str] = {}
        for source in sources:
            key = str(source.get("meeting_id") or source.get("meeting_title") or "")
            if not key:
                continue
            groups.setdefault(key, []).append(source)
            titles[key] = str(source.get("meeting_title") or key)

        if len(groups) < 2:
            return answer

        parts = re.split(r"(\n+)", answer)
        repaired: list[str] = []
        for part in parts:
            if not part or part.startswith("\n"):
                repaired.append(part)
                continue
            mentioned = cls._mentioned_meeting_keys(part, titles)
            if mentioned:
                existing_ids = cls._extract_citation_ids(part)
                existing_meeting_keys = {
                    str(source.get("meeting_id") or source.get("meeting_title") or "")
                    for source in sources
                    if str(source.get("source_id") or "") in existing_ids
                }
                # Preserve an already-correct citation binding. This matters for
                # deterministic fallback lines where the chosen Executive Summary
                # is intentionally the representative source for that meeting.
                if all(meeting_key in existing_meeting_keys for meeting_key in mentioned):
                    replacement_ids = []
                else:
                    replacement_ids = []
                    unsupported = False
                    for meeting_key in mentioned:
                        best = cls._best_source_for_claim(part, groups.get(meeting_key, []))
                        if best is None:
                            unsupported = True
                            break
                        source_id = str(best.get("source_id") or "")
                        if source_id and source_id not in replacement_ids:
                            replacement_ids.append(source_id)
                    if unsupported or not replacement_ids:
                        # Do not expose a meeting-specific claim with a citation from
                        # another meeting. Dropping the unsupported line is safer.
                        continue
                    part = cls._replace_citations_in_unit(part, replacement_ids)

            if cls._looks_like_shared_claim(part):
                cited = [
                    source for source in sources
                    if str(source.get("source_id") or "") in cls._extract_citation_ids(part)
                ]
                meeting_count = len({
                    str(source.get("meeting_id") or source.get("meeting_title") or "")
                    for source in cited
                })
                if meeting_count >= 2 and not cls._shared_claim_supported(part, cited):
                    # Conservative grounding: remove invented overlap rather than
                    # presenting it as a fact supported by unrelated citations.
                    continue
            repaired.append(part)
        return "".join(repaired).strip()

    @classmethod
    def _ground_uncited_cross_meeting_lines(
        cls,
        answer: str,
        sources: list[dict[str, Any]],
    ) -> str:
        """Ensure substantive cross-meeting lines carry meeting evidence citations.

        This is a fail-safe for small local models that occasionally follow the
        requested synthesis but omit citation markers. Short headings and purely
        connective lines are preserved; unsupported factual list items are dropped.
        """
        if not answer or not sources:
            return answer
        output: list[str] = []
        for raw_line in answer.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                output.append(raw_line)
                continue
            if _CITATION_RE.search(raw_line):
                output.append(raw_line)
                continue
            plain = re.sub(r"^[#>*+\-\d.)\s]+", "", stripped).strip()
            # Headings / lead-ins are not factual evidence claims by themselves.
            if (
                len(cls._content_tokens(plain)) <= 2
                or (plain.endswith(":") and len(plain) < 120)
                or plain.casefold().startswith(("the following", "comparison:", "differences:", "shared themes:"))
            ):
                output.append(raw_line)
                continue

            best, overlap_count = cls._best_source_for_claim_with_overlap(raw_line, sources)
            if best is not None and overlap_count >= 2:
                output.append(cls._replace_citations_in_unit(raw_line, [str(best.get("source_id") or "")]))
                continue

            # A single distinctive scientific/proper token can be enough for a
            # compact list item (e.g. "Otsu segmentation").
            claim_tokens = set(cls._content_tokens(raw_line))
            if best is not None and any(len(token) >= 7 for token in claim_tokens):
                best_tokens = set(cls._content_tokens(
                    f"{best.get('source_label', '')} {best.get('excerpt', '')}"
                ))
                if any(token in best_tokens for token in claim_tokens if len(token) >= 7):
                    output.append(cls._replace_citations_in_unit(raw_line, [str(best.get("source_id") or "")]))
                    continue

            # Keep non-factual connective conclusions, but do not expose an
            # uncited meeting-specific assertion as grounded knowledge.
            if stripped.casefold().startswith(("overall", "in summary", "taken together")):
                output.append(raw_line)
        return "\n".join(output).strip()

    @classmethod
    def _best_source_for_claim_with_overlap(
        cls,
        claim: str,
        sources: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, int]:
        claim_tokens = set(cls._content_tokens(claim))
        if not claim_tokens or not sources:
            return None, 0
        preference = {
            "summary": 0.18,
            "slide_summary": 0.15,
            "key_point": 0.13,
            "decision": 0.12,
            "action_item": 0.12,
            "open_question": 0.11,
            "discussion_qa": 0.10,
            "transcript": 0.05,
            "technical_terms": -0.04,
        }
        best: dict[str, Any] | None = None
        best_overlap = 0
        best_score = -1.0
        for source in sources:
            source_tokens = set(cls._content_tokens(
                f"{source.get('meeting_title', '')} {source.get('source_label', '')} {source.get('excerpt', '')}"
            ))
            overlap = len(claim_tokens & source_tokens)
            ratio = overlap / max(1, len(claim_tokens))
            score = ratio + preference.get(str(source.get("source_type") or ""), 0.0)
            if score > best_score:
                best = source
                best_overlap = overlap
                best_score = score
        return best, best_overlap

    @classmethod
    def _mentioned_meeting_keys(
        cls,
        text: str,
        titles: dict[str, str],
    ) -> list[str]:
        normalized = re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
        mentioned: list[str] = []
        for key, title in titles.items():
            clean_title = re.sub(r"\[demo\]", "", title, flags=re.IGNORECASE)
            title_norm = re.sub(r"[^a-z0-9]+", " ", clean_title.casefold()).strip()
            title_tokens = [
                token for token in cls._content_tokens(clean_title)
                if token not in {"demo", "update", "discussion", "reconstruction"}
            ]
            aliases = [title_norm]
            if title_tokens:
                aliases.extend(title_tokens)
                if len(title_tokens) >= 2:
                    aliases.append(" ".join(title_tokens[:2]))
            if any(alias and re.search(rf"\b{re.escape(alias)}\b", normalized) for alias in aliases):
                mentioned.append(key)
        return mentioned

    @classmethod
    def _best_source_for_claim(
        cls,
        claim: str,
        sources: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not sources:
            return None
        claim_tokens = set(cls._content_tokens(claim))
        preference = {
            "summary": 0.18,
            "slide_summary": 0.15,
            "key_point": 0.13,
            "decision": 0.12,
            "action_item": 0.12,
            "open_question": 0.11,
            "discussion_qa": 0.10,
            "transcript": 0.05,
            "technical_terms": -0.04,
        }
        ranked: list[tuple[float, dict[str, Any]]] = []
        for source in sources:
            source_tokens = set(cls._content_tokens(
                f"{source.get('source_label', '')} {source.get('excerpt', '')}"
            ))
            overlap = len(claim_tokens & source_tokens) / max(1, len(claim_tokens))
            score = overlap + preference.get(str(source.get("source_type") or ""), 0.0)
            ranked.append((score, source))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[0][1] if ranked else None

    @staticmethod
    def _replace_citations_in_unit(text: str, source_ids: list[str]) -> str:
        clean = _CITATION_RE.sub("", text)
        clean = re.sub(r"[ \t]{2,}", " ", clean).rstrip()
        citation_text = "".join(f"[{source_id}]" for source_id in source_ids)
        match = re.search(r"([.!?])(\s*)$", clean)
        if match:
            return clean[:match.start(1)].rstrip() + f" {citation_text}" + match.group(1) + match.group(2)
        return clean + f" {citation_text}"

    @staticmethod
    def _looks_like_shared_claim(text: str) -> bool:
        q = text.casefold()
        markers = (
            "both meetings", "shared theme", "shared themes", "common to both",
            "in common", "overlap", "similarly, both", "both discussed",
        )
        return any(marker in q for marker in markers)

    @classmethod
    def _shared_claim_supported(
        cls,
        claim: str,
        cited_sources: list[dict[str, Any]],
    ) -> bool:
        by_meeting: dict[str, set[str]] = {}
        for source in cited_sources:
            key = str(source.get("meeting_id") or source.get("meeting_title") or "")
            if not key:
                continue
            by_meeting.setdefault(key, set()).update(
                cls._content_tokens(f"{source.get('source_label', '')} {source.get('excerpt', '')}")
            )
        if len(by_meeting) < 2:
            return False
        common = set.intersection(*by_meeting.values()) if by_meeting else set()
        claim_tokens = set(cls._content_tokens(claim))
        generic = {
            "both", "shared", "common", "overlap", "similar", "similarly",
            "meeting", "meetings", "discussed", "focused",
        }
        meaningful_claim = claim_tokens - generic
        return bool(common & meaningful_claim)

    @staticmethod
    def _is_closing_source(source: dict[str, Any]) -> bool:
        if str(source.get("source_type") or "") not in {"slide_summary", "summary"}:
            return False
        text = f"{source.get('source_label', '')} {source.get('excerpt', '')}".casefold()
        markers = (
            "thank you", "thanks for your attention", "presentation concluded",
            "closing slide", "end of the presentation", "q&a boundary",
            "subsequent scientific discussion",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _asks_about_closing_or_qna(question: str) -> bool:
        q = question.casefold()
        markers = (
            "thank you", "closing slide", "last slide", "final slide", "end of the talk",
            "end of the presentation", "after the presentation", "after the talk", "q&a",
            "q and a", "questions after", "discussion after",
        )
        return any(marker in q for marker in markers)

    @staticmethod
    def _format_evidence_context(sources: list[dict[str, Any]]) -> str:
        if not sources:
            return ""
        groups: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for source in sources:
            key = str(source.get("meeting_id") or source.get("meeting_title") or "meeting")
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(source)

        blocks: list[str] = []
        for group_index, key in enumerate(order, start=1):
            bucket = groups[key]
            first = bucket[0]
            blocks.append(
                "\n".join(
                    [
                        f"=== MEETING GROUP {group_index} ===",
                        f"Meeting: {first.get('meeting_title') or 'Untitled meeting'}",
                        f"Meeting ID: {first.get('meeting_id') or 'unknown'}",
                        f"Date: {first.get('meeting_date') or 'unknown'}",
                    ]
                )
            )
            for source in bucket:
                blocks.append(
                    "\n".join(
                        [
                            f"[{source['source_id']}] Source: {source['source_label']}",
                            f"Evidence: {source['excerpt']}",
                        ]
                    )
                )
        return "\n\n".join(blocks)

    @staticmethod
    def _format_history(history: list[dict[str, str]]) -> str:
        return "\n".join(
            f"{str(item.get('role', 'user')).upper()}: {str(item.get('content', '')).strip()}"
            for item in history
            if str(item.get("content", "")).strip()
        )

    @classmethod
    def _hybrid_evidence_is_useful(
        cls,
        query: str,
        search_result: dict[str, Any],
    ) -> bool:
        if not search_result.get("evidence_found"):
            return False
        results = list(search_result.get("results") or [])
        if not results:
            return False

        # Hybrid mode should only claim that the archive is relevant when the
        # current question has a concrete lexical anchor in retrieved evidence.
        # This deliberately ignores unrelated prior-turn text.
        query_tokens = cls._content_tokens(query)
        query_set = set(query_tokens)
        content_phrase = " ".join(query_tokens)
        for item in results[:4]:
            lexical = float(item.get("lexical_score") or 0.0)
            if lexical >= 0.15:
                return True
            hay = re.sub(
                r"[^a-z0-9]+",
                " ",
                f"{item.get('meeting_title', '')} {item.get('source_label', '')} {item.get('excerpt', '')}".casefold(),
            ).strip()
            if content_phrase and len(query_tokens) >= 2 and content_phrase in hay:
                return True
            hay_tokens = set(cls._tokens(hay))
            matched = query_set & hay_tokens
            if len(matched) >= 2:
                return True
            if any(len(token) >= 7 and token in hay_tokens for token in query_set):
                return True
        return False

    def _cited_sources(
        self,
        answer: str,
        sources: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        cited_ids = self._extract_citation_ids(answer)
        return [
            source
            for source in sources
            if source.get("source_id") in cited_ids
        ][: self.max_sources]

    def _load_meeting_document(self, meeting_id: str) -> dict[str, Any] | None:
        meeting = self.storage.get_meeting_details(meeting_id)
        if meeting is None:
            return None
        return meeting

    def _build_chunks(self, meeting: dict[str, Any]) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        meeting_title = str(meeting.get("title") or "Untitled meeting")
        transcript = str(meeting.get("final_transcript") or "").strip()
        if transcript:
            for index, text in enumerate(self._split_words(transcript)):
                chunks.append({
                    "source_type": "transcript",
                    "source_key": str(index),
                    "source_label": f"Transcript · part {index + 1}",
                    "text": text,
                    "metadata": {"meeting_title": meeting_title},
                })

        summary = meeting.get("summary") or {}
        executive = str(summary.get("summary") or "").strip()
        if executive:
            chunks.append({
                "source_type": "summary",
                "source_key": "executive",
                "source_label": "Executive Summary",
                "text": executive,
                "metadata": {"meeting_title": meeting_title},
            })

        for index, item in enumerate(summary.get("slide_summaries") or []):
            text = str(item.get("summary") or "").strip()
            if not text:
                continue
            number = item.get("slide_number")
            title = str(item.get("title") or f"Slide {number}")
            chunks.append({
                "source_type": "slide_summary",
                "source_key": str(number or index),
                "source_label": f"Slide {number} · {title}" if number else title,
                "slide_number": int(number) if number is not None else None,
                "text": text,
                "metadata": {"meeting_title": meeting_title, "key_terms": item.get("key_terms") or []},
            })

        simple_lists = [
            ("key_point", "Key Point", summary.get("key_points") or []),
            ("decision", "Decision", summary.get("decisions") or []),
            ("open_question", "Open Question", summary.get("open_questions") or []),
        ]
        for source_type, label, values in simple_lists:
            for index, value in enumerate(values):
                text = str(value).strip()
                if text:
                    chunks.append({
                        "source_type": source_type,
                        "source_key": str(index),
                        "source_label": label,
                        "text": text,
                        "metadata": {"meeting_title": meeting_title},
                    })

        for index, item in enumerate(summary.get("action_items") or []):
            task = str(item.get("task") or "").strip()
            if not task:
                continue
            extra = []
            if item.get("owner"):
                extra.append(f"Owner: {item['owner']}")
            if item.get("deadline"):
                extra.append(f"Deadline: {item['deadline']}")
            chunks.append({
                "source_type": "action_item",
                "source_key": str(index),
                "source_label": "Action Item",
                "text": task + ("\n" + "\n".join(extra) if extra else ""),
                "metadata": {"meeting_title": meeting_title},
            })

        for index, item in enumerate(summary.get("discussion_questions") or []):
            question = str(item.get("question") or "").strip()
            answer = str(item.get("answer") or "").strip()
            if not question:
                continue
            status = str(item.get("status") or "unresolved")
            text = f"Question: {question}\nStatus: {status}"
            if answer:
                text += f"\nAnswer: {answer}"
            chunks.append({
                "source_type": "discussion_qa",
                "source_key": str(index),
                "source_label": "Discussion Q&A",
                "text": text,
                "metadata": {"meeting_title": meeting_title, "status": status},
            })

        terms = [str(item).strip() for item in summary.get("technical_terms") or [] if str(item).strip()]
        if terms:
            chunks.append({
                "source_type": "technical_terms",
                "source_key": "terms",
                "source_label": "Technical Terms",
                "text": "Technical terms discussed: " + ", ".join(terms),
                "metadata": {"meeting_title": meeting_title},
            })
        return chunks

    def _split_words(self, text: str) -> Iterable[str]:
        words = text.split()
        if len(words) <= self.chunk_words:
            yield " ".join(words)
            return
        step = max(1, self.chunk_words - self.chunk_overlap)
        start = 0
        while start < len(words):
            chunk = words[start : start + self.chunk_words]
            if chunk:
                yield " ".join(chunk)
            if start + self.chunk_words >= len(words):
                break
            start += step

    @staticmethod
    def _fingerprint(meeting: dict[str, Any], chunks: list[dict[str, Any]]) -> str:
        payload = {
            "meeting_id": meeting.get("meeting_id"),
            "title": meeting.get("title"),
            "end_time": meeting.get("end_time"),
            "chunks": [
                [item.get("source_type"), item.get("source_label"), item.get("text")]
                for item in chunks
            ],
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        # Keep payloads modest for a local model and long meeting collections.
        for start in range(0, len(texts), 32):
            batch = texts[start : start + 32]
            timeout = httpx.Timeout(self.timeout_seconds, connect=min(10.0, self.timeout_seconds))
            async with httpx.AsyncClient(timeout=timeout, transport=self._http_transport) as client:
                response = await client.post(
                    f"{self.ollama_api_base}/embed",
                    json={"model": self.embedding_model, "input": batch, "truncate": True},
                )
                response.raise_for_status()
                payload = response.json()
            batch_vectors = payload.get("embeddings") or []
            if len(batch_vectors) != len(batch):
                raise RuntimeError("Ollama embedding response length did not match the input batch")
            vectors.extend([[float(value) for value in vector] for vector in batch_vectors])
        return vectors

    async def _chat(self, prompt: str) -> str:
        if not self._model_installed(self.llm_model, await self._list_models()):
            raise RuntimeError(
                f"Ollama chat model '{self.llm_model}' is not installed. Run: ollama pull {self.llm_model}"
            )
        timeout = httpx.Timeout(self.timeout_seconds, connect=min(10.0, self.timeout_seconds))
        payload = {
            "model": self.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You answer scientific questions using only retrieved meeting evidence. "
                        "Never invent unsupported facts."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "10m"),
            "options": {"temperature": 0, "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "32768"))},
        }
        async with httpx.AsyncClient(timeout=timeout, transport=self._http_transport) as client:
            response = await client.post(f"{self.ollama_api_base}/chat", json=payload)
            response.raise_for_status()
            body = response.json()
        answer = str(body.get("message", {}).get("content", "")).strip()
        if not answer:
            raise RuntimeError("Ollama returned an empty RAG answer")
        return answer

    async def _chat_general(self, prompt: str) -> str:
        if not self._model_installed(self.llm_model, await self._list_models()):
            raise RuntimeError(
                f"Ollama chat model '{self.llm_model}' is not installed. Run: ollama pull {self.llm_model}"
            )
        timeout = httpx.Timeout(self.timeout_seconds, connect=min(10.0, self.timeout_seconds))
        payload = {
            "model": self.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a local scientific assistant. Distinguish general knowledge "
                        "from user-provided meeting evidence whenever both are present."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "10m"),
            "options": {"temperature": 0, "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "32768"))},
        }
        async with httpx.AsyncClient(timeout=timeout, transport=self._http_transport) as client:
            response = await client.post(f"{self.ollama_api_base}/chat", json=payload)
            response.raise_for_status()
            body = response.json()
        answer = str(body.get("message", {}).get("content", "")).strip()
        if not answer:
            raise RuntimeError("Ollama returned an empty chat answer")
        return answer

    async def _list_models(self) -> list[str]:
        timeout = httpx.Timeout(10.0, connect=3.0)
        async with httpx.AsyncClient(timeout=timeout, transport=self._http_transport) as client:
            response = await client.get(f"{self.ollama_api_base}/tags")
            response.raise_for_status()
            payload = response.json()
        return sorted({
            str(item.get("name") or item.get("model") or "").strip()
            for item in payload.get("models", [])
            if str(item.get("name") or item.get("model") or "").strip()
        })

    @staticmethod
    def _model_installed(requested: str, installed: list[str]) -> bool:
        requested_base = requested.removesuffix(":latest")
        return any(name.removesuffix(":latest") == requested_base for name in installed)

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [token.casefold() for token in _TOKEN_RE.findall(text) if len(token) > 1]

    @classmethod
    def _content_tokens(cls, text: str) -> list[str]:
        return [token for token in cls._tokens(text) if token not in _QUERY_STOPWORDS]

    def _lexical_score(
        self,
        query: str,
        text: str,
        label: str,
        meeting_title: str = "",
    ) -> float:
        query_tokens = self._content_tokens(query)
        if not query_tokens:
            return 0.0
        content_hay_text = f"{label} {text}"
        content_tokens = set(self._tokens(content_hay_text))
        title_tokens = set(self._tokens(meeting_title))
        unique_query = set(query_tokens)
        matched_content = sum(1 for token in unique_query if token in content_tokens)
        matched_title_only = sum(
            1 for token in unique_query if token in title_tokens and token not in content_tokens
        )
        # A meeting-title match is useful for scoping (e.g. "Shahin's talk"),
        # but should not outrank content evidence merely because every chunk
        # shares the same title.
        score = (matched_content + 0.30 * matched_title_only) / len(unique_query)
        clean_query = query.casefold().strip()
        hay = content_hay_text.casefold()
        if len(clean_query) >= 5 and clean_query in hay:
            score += 0.35
        # Exact multi-word content phrases are especially useful for scientific
        # software names and proper nouns.
        content_phrase = " ".join(query_tokens)
        if len(query_tokens) >= 2 and content_phrase in re.sub(r"[^a-z0-9]+", " ", hay):
            score += 0.18
        return min(score, 1.0)

    @staticmethod
    def _query_intent(query: str) -> str:
        q = query.casefold()
        if any(term in q for term in ("unresolved", "open question", "still open", "remain unanswered")):
            return "open_question"
        if any(term in q for term in ("action item", "action items", "task", "tasks", "todo", "to do")):
            return "action_item"
        if any(term in q for term in ("decision", "decisions", "decided", "agreed")):
            return "decision"
        if any(term in q for term in (
            "main goal", "goal", "purpose", "aim", "objective", "talk about",
            "presentation about", "meeting about", "main topic", "topic of", "overview",
        )):
            return "goal"
        if any(term in q for term in ("how was", "how were", "how did", "generated", "created", "pipeline", "method")):
            return "method"
        if any(term in q for term in ("question", "answer", "discussed why", "why does", "why did")):
            return "discussion"
        return "general"

    @staticmethod
    def _intent_source_adjustment(intent: str, source_type: str) -> float:
        weights = {
            "goal": {
                "summary": 0.14, "slide_summary": 0.11, "key_point": 0.08,
                "transcript": 0.02, "discussion_qa": -0.08, "open_question": -0.10,
            },
            "method": {
                "slide_summary": 0.13, "key_point": 0.10, "summary": 0.08,
                "transcript": 0.05, "technical_terms": -0.03,
                "discussion_qa": -0.04, "open_question": -0.08,
            },
            "open_question": {
                "open_question": 0.20, "discussion_qa": 0.14, "summary": 0.03,
                "slide_summary": -0.02, "technical_terms": -0.05,
            },
            "decision": {
                "decision": 0.22, "summary": 0.05, "transcript": 0.02,
                "open_question": -0.06,
            },
            "action_item": {
                "action_item": 0.22, "summary": 0.04, "transcript": 0.02,
                "open_question": -0.06,
            },
            "discussion": {
                "discussion_qa": 0.14, "transcript": 0.06, "summary": 0.04,
                "open_question": 0.03,
            },
        }
        return float(weights.get(intent, {}).get(source_type, 0.0))

    def _route_question(
        self,
        question: str,
        history: list[dict[str, str]],
    ) -> str:
        q = question.casefold().strip()
        if self._is_weather_question(q):
            return "weather"
        if self._is_weather_location_followup(question, history):
            return "weather"
        if self._is_date_time_question(q):
            return "date_time"

        if self._is_cross_meeting_query(question):
            return "meeting_rag"

        archive_markers = (
            "meeting", "meetings", "meeting archive", "presentation", "presentations",
            "transcript", "slide", "slides", "summary", "summaries", "action item",
            "action items", "decision", "decisions", "open question", "open questions",
            "unresolved", "did we discuss", "have we discussed", "we discussed",
            "our discussion", "in our meeting", "in the meeting", "from the meeting",
            "across meetings", "across all meetings", "which meeting", "which meetings",
            "this talk", "the talk", "speaker's talk", "speaker’s talk",
        )
        if any(marker in q for marker in archive_markers):
            return "meeting_rag"

        # A possessive/name + talk/presentation phrasing is an explicit archive
        # question even when the user types the person's name in lowercase.
        if re.search(
            r"\b[a-z][a-z0-9'-]{1,40}(?:'s|’s)\s+(?:talk|presentation|meeting|discussion)\b",
            q,
            flags=re.IGNORECASE,
        ):
            return "meeting_rag"

        # Questions about a named person are kept archive-grounded by default.
        # This avoids a local LLM inventing biographical facts for people who are
        # not represented in the user's own meeting corpus.
        if q.startswith(("do you know ", "who is ", "who's ")) and self._required_entities(question):
            return "meeting_rag"

        # A self-contained scientific request should not become archive-only just
        # because the previous assistant answer contained meeting citations. Formula,
        # equation, definition and explanation requests default to general/hybrid mode
        # unless the user explicitly scopes them to a meeting above.
        if self._is_self_contained_knowledge_request(question):
            return "knowledge"

        # Short conversational follow-ups inherit an archive context when the
        # preceding assistant answer contained meeting citations.
        if len(question.split()) <= 6:
            recent_assistant = next((
                str(item.get("content") or "")
                for item in reversed(history)
                if str(item.get("role") or "").casefold() == "assistant"
            ), "")
            if "general context:" in recent_assistant.casefold():
                return "knowledge"
            if "[S" in recent_assistant:
                return "meeting_rag"

        # Broad explain/define prompts are eligible for hybrid mode. The ask()
        # method probes the archive and falls back to general knowledge if no
        # relevant evidence is found.
        return "knowledge"

    @classmethod
    def _is_self_contained_knowledge_request(cls, question: str) -> bool:
        if cls._is_contextual_followup(question):
            return False
        q = re.sub(r"\s+", " ", question.casefold()).strip(" ?!.,")
        starts = (
            "tell me about ", "explain ", "define ", "what is ", "what are ",
            "give me the ", "show me the ", "derive ",
        )
        scientific_markers = (
            " formula", "formula ", " equation", "equation ", " definition",
            "definition ", " derivation", "derive ", " theorem", "transform",
            "segmentation", "algorithm", "method", "loss function",
        )
        return q.startswith(starts) or any(marker in f" {q} " for marker in scientific_markers)

    @staticmethod
    def _is_weather_question(q: str) -> bool:
        q = q.replace("’", "'")
        archive_context = ("meeting", "meetings", "discuss", "presentation", "transcript")
        if any(term in q for term in archive_context):
            return False
        patterns = (
            "weather", "forecast", "temperature today", "temperature for today",
            "today's temperature", "todays temperature", "temp today", "temp for today",
            "outside temperature", "rain today", "raining today", "snow today",
            "wind today", "umbrella today",
        )
        return any(pattern in q for pattern in patterns)

    async def _weather_answer(
        self,
        question: str,
        *,
        latitude: float | None,
        longitude: float | None,
        timezone_name: str | None,
        allow_plain_location: bool = False,
    ) -> dict[str, Any]:
        location_label = "your current location"
        lat = latitude
        lon = longitude
        timezone_value = timezone_name or "auto"

        if lat is None or lon is None:
            hint = self._extract_weather_location(question, allow_plain=allow_plain_location)
            if not hint:
                return {
                    "answer": (
                        "I can fetch live weather, but I need a location. Please specify a city "
                        "(for example, `weather in Hamburg`) or allow browser location access."
                    ),
                    "needs_location": True,
                }
            place = await self._geocode_location(hint)
            if place is None:
                return {
                    "answer": f"I couldn't resolve the location **{hint}**. Please try a city name or postal code.",
                    "needs_location": True,
                }
            lat = float(place["latitude"])
            lon = float(place["longitude"])
            timezone_value = str(place.get("timezone") or "auto")
            country = str(place.get("country") or "").strip()
            location_label = str(place.get("name") or hint)
            if country and country.casefold() not in location_label.casefold():
                location_label = f"{location_label}, {country}"

        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "timezone": timezone_value,
            "forecast_days": 1,
        }
        async with httpx.AsyncClient(timeout=20.0, transport=self._http_transport) as client:
            response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
            response.raise_for_status()
            payload = response.json()

        current = payload.get("current") or {}
        daily = payload.get("daily") or {}
        temp = current.get("temperature_2m")
        apparent = current.get("apparent_temperature")
        code = current.get("weather_code")
        wind = current.get("wind_speed_10m")
        high = self._first(daily.get("temperature_2m_max"))
        low = self._first(daily.get("temperature_2m_min"))
        precip = self._first(daily.get("precipitation_probability_max"))
        condition = self._weather_code_label(code)

        parts = []
        if temp is not None:
            parts.append(f"**{float(temp):.1f}°C** now")
        if apparent is not None:
            parts.append(f"feels like {float(apparent):.1f}°C")
        if condition:
            parts.append(condition)
        first_sentence = ", ".join(parts) if parts else "Live weather data is available"
        details = []
        if high is not None and low is not None:
            details.append(f"today's high is **{float(high):.1f}°C** and low is **{float(low):.1f}°C**")
        if precip is not None:
            details.append(f"maximum precipitation probability is **{float(precip):.0f}%**")
        if wind is not None:
            details.append(f"wind is {float(wind):.1f} km/h")
        second = "; ".join(details)
        answer = f"For **{location_label}**, it's {first_sentence}."
        if second:
            second_sentence = second[:1].upper() + second[1:]
            answer += f" {second_sentence}."
        return {"answer": answer, "needs_location": False}

    async def _geocode_location(self, name: str) -> dict[str, Any] | None:
        params = {"name": name, "count": 1, "language": "en", "format": "json"}
        async with httpx.AsyncClient(timeout=15.0, transport=self._http_transport) as client:
            response = await client.get("https://geocoding-api.open-meteo.com/v1/search", params=params)
            response.raise_for_status()
            results = (response.json() or {}).get("results") or []
        return dict(results[0]) if results else None

    @staticmethod
    def _extract_weather_location(question: str, *, allow_plain: bool = False) -> str | None:
        clean = re.sub(r"[?!.,]+$", "", question).strip()
        if not clean:
            return None

        # Prefer explicit location prepositions.  "for today" is a time phrase,
        # not a location, so generic weather/time words are filtered below.
        patterns = (
            r"\b(?:weather|forecast|temperature|temp)\s+(?:in|at)\s+(.+?)(?:\s+(?:today|tonight|tomorrow|now))?$",
            r"\b(?:weather|forecast|temperature|temp)\s+for\s+(.+?)(?:\s+(?:today|tonight|tomorrow|now))?$",
            r"\b(?:weather|forecast)\s+(.+?)(?:\s+(?:today|tonight|tomorrow|now))?$",
        )
        candidates: list[str] = []
        for pattern in patterns:
            match = re.search(pattern, clean, flags=re.IGNORECASE)
            if match:
                candidates.append(re.sub(r"\s+", " ", match.group(1)).strip())

        if allow_plain and len(clean.split()) <= 6:
            plain = re.sub(r"^(?:in|at|for|near)\s+", "", clean, flags=re.IGNORECASE).strip()
            plain = re.sub(r"^(?:city|location)\s+(?:is\s+)?", "", plain, flags=re.IGNORECASE).strip()
            candidates.append(plain)

        generic = {
            "today", "tonight", "tomorrow", "now", "current", "currently", "outside",
            "weather", "forecast", "temperature", "temp", "temperatures", "degree", "degrees",
            "for", "in", "at", "please", "tell", "me", "the", "what", "is", "whats", "what's",
        }
        for value in candidates:
            normalized = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ0-9 .'-]+", " ", value)
            normalized = re.sub(r"\s+", " ", normalized).strip(" -'")
            if not normalized:
                continue
            tokens = [token.casefold() for token in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", normalized)]
            if not tokens or all(token in generic for token in tokens):
                continue
            # Phrases such as "temperature for" / "temperature for today"
            # are request wording, not a place name.
            informative = [token for token in tokens if token not in generic]
            if not informative:
                continue
            if len(informative) == 1 and informative[0] in {"temperature", "tempruter", "weather", "forecast"}:
                continue
            return normalized
        return None

    @classmethod
    def _is_weather_location_followup(
        cls,
        question: str,
        history: list[dict[str, str]],
    ) -> bool:
        clean = re.sub(r"[?!.,]+$", "", question).strip()
        if not clean or len(clean.split()) > 6:
            return False
        recent_assistant = next((
            str(item.get("content") or "")
            for item in reversed(history)
            if str(item.get("role") or "").casefold() == "assistant"
        ), "")
        previous = recent_assistant.casefold()
        pending_weather = any(marker in previous for marker in (
            "need a location", "specify a city", "city name or postal code",
            "couldn't resolve the location", "weather needs a location",
        ))
        if not pending_weather:
            return False
        return cls._extract_weather_location(clean, allow_plain=True) is not None

    @staticmethod
    def _first(value: Any) -> Any:
        if isinstance(value, list) and value:
            return value[0]
        return None

    @staticmethod
    def _weather_code_label(code: Any) -> str:
        try:
            value = int(code)
        except (TypeError, ValueError):
            return ""
        if value == 0:
            return "clear sky"
        if value in {1, 2, 3}:
            return {1: "mainly clear", 2: "partly cloudy", 3: "overcast"}[value]
        if value in {45, 48}:
            return "foggy"
        if value in {51, 53, 55, 56, 57}:
            return "drizzle"
        if value in {61, 63, 65, 66, 67, 80, 81, 82}:
            return "rain"
        if value in {71, 73, 75, 77, 85, 86}:
            return "snow"
        if value in {95, 96, 99}:
            return "thunderstorms"
        return "mixed conditions"

    def _renumber_citations(
        self,
        answer: str,
        sources: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        if not sources:
            return answer, []
        source_by_id = {str(item.get("source_id")): item for item in sources}
        ordered_old_ids = [sid for sid in self._extract_citation_ids(answer) if sid in source_by_id]
        if not ordered_old_ids:
            return answer, []
        mapping = {old: f"S{index}" for index, old in enumerate(ordered_old_ids, start=1)}

        def replace(match: re.Match[str]) -> str:
            start_id = int(match.group(1)[1:])
            end_raw = match.group(2)
            if end_raw:
                end_id = int(end_raw.lstrip("Ss"))
                low, high = sorted((start_id, end_id))
                old_ids = [f"S{value}" for value in range(low, high + 1)]
            else:
                old_ids = [f"S{start_id}"]
            new_ids = [mapping[item] for item in old_ids if item in mapping]
            return "".join(f"[{item}]" for item in new_ids)

        normalized_answer = _CITATION_RE.sub(replace, answer)
        normalized_sources: list[dict[str, Any]] = []
        for old_id in ordered_old_ids:
            copied = dict(source_by_id[old_id])
            copied["source_id"] = mapping[old_id]
            normalized_sources.append(copied)
        return normalized_answer, normalized_sources

    @staticmethod
    def _is_date_time_question(q: str) -> bool:
        q = q.replace("’", "'")
        archive_context = ("meeting", "meetings", "discuss", "discussed", "presentation", "transcript")
        if any(term in q for term in archive_context):
            return False
        patterns = (
            "today's date", "todays date", "what date is it", "what is the date",
            "current date", "date today", "what day is it", "what day is today",
            "what time is it", "what's the time", "whats the time", "current time",
            "time now", "date and time", "current date and time",
        )
        return any(pattern in q for pattern in patterns)

    def _date_time_answer(self, question: str) -> str:
        now = self._now_provider()
        if now.tzinfo is None:
            now = now.astimezone()
        q = question.casefold()
        date_text = now.strftime("%B %d, %Y").replace(" 0", " ")
        time_text = now.strftime("%I:%M %p").lstrip("0")
        zone = now.tzname() or "local time"
        asks_time = any(term in q for term in ("time", "date and time"))
        asks_date = any(term in q for term in ("date", "day", "today"))
        if asks_time and asks_date:
            return f"Today is {date_text}, and the current local time is {time_text} ({zone})."
        if asks_time:
            return f"The current local time is {time_text} ({zone})."
        return f"Today is {date_text}."

    @classmethod
    def _required_entities(cls, query: str) -> list[str]:
        entities: list[str] = []
        normalized = re.sub(r"[’]", "'", query)
        # Multi-word proper nouns such as Vahid Rahmani or ASTRA Toolbox.
        for match in re.finditer(r"\b(?:[A-Z][A-Za-z0-9'-]*\s+){1,3}[A-Z][A-Za-z0-9'-]*\b", normalized):
            value = re.sub(r"\s+", " ", match.group(0)).strip()
            first = value.split()[0].casefold()
            if first not in _QUESTION_STARTERS and value.casefold() not in {item.casefold() for item in entities}:
                entities.append(value)
        # Possessive/single proper names such as Shahin's.
        for match in re.finditer(r"\b([A-Z][a-z][A-Za-z0-9'-]{2,})(?:'s|’s)\b", normalized):
            value = match.group(1)
            if value.casefold() not in _QUESTION_STARTERS and value.casefold() not in {item.casefold() for item in entities}:
                entities.append(value)
        # Scientific acronyms are often decisive retrieval anchors.
        for match in re.finditer(r"\b[A-Z][A-Z0-9]{2,}\b", normalized):
            value = match.group(0)
            if value not in {"WHO"} and value.casefold() not in {item.casefold() for item in entities}:
                entities.append(value)
        return entities

    @staticmethod
    def _hit_search_text(hit: RetrievalHit) -> str:
        return f"{hit.meeting_title} {hit.source_label} {hit.text}".casefold()

    def _select_retrieval_hits(
        self,
        candidates: list[RetrievalHit],
        *,
        requested_k: int,
        cross_meeting: bool,
        cross_overview: bool,
        semantic_used: bool,
        query: str,
    ) -> list[RetrievalHit]:
        if not candidates:
            return []

        selected: list[RetrievalHit] = []
        per_meeting: dict[str, int] = {}
        per_meeting_cap = 3 if cross_meeting else 4

        if cross_meeting:
            best_by_meeting: dict[str, RetrievalHit] = {}
            if cross_overview:
                # Cross-meeting synthesis uses an intent-specific evidence type:
                # summaries for overview/comparison, open-question/Q&A entries for
                # unresolved issues, action items for tasks, and so on.
                intent = self._query_intent(query)
                seed_types = self._cross_meeting_seed_types(intent)
                for hit in candidates:
                    if hit.source_type not in seed_types:
                        continue
                    current = best_by_meeting.get(hit.meeting_id)
                    if current is None or self._cross_seed_hit_key(hit, intent) < self._cross_seed_hit_key(current, intent):
                        best_by_meeting[hit.meeting_id] = hit
            else:
                for hit in candidates:
                    if hit.meeting_id in best_by_meeting:
                        continue
                    # A topic-specific query such as "Which meetings discussed Otsu?"
                    # must match the actual topic in that meeting. Generic scaffolding
                    # words (meeting/discussed/across) are stopwords and cannot make a
                    # meeting eligible by themselves.
                    if self._cross_meeting_topic_match(query, hit):
                        best_by_meeting[hit.meeting_id] = hit
            seeds = sorted(best_by_meeting.values(), key=lambda item: item.score, reverse=True)
            for hit in seeds:
                if len(selected) >= requested_k:
                    break
                if self._is_near_duplicate(hit, selected):
                    continue
                selected.append(hit)
                per_meeting[hit.meeting_id] = 1

        allowed_meetings = set(per_meeting) if cross_meeting and per_meeting else None
        for hit in candidates:
            if len(selected) >= requested_k:
                break
            if hit in selected:
                continue
            if allowed_meetings is not None and hit.meeting_id not in allowed_meetings:
                continue
            count = per_meeting.get(hit.meeting_id, 0)
            if count >= per_meeting_cap:
                continue
            if self._is_near_duplicate(hit, selected):
                continue
            selected.append(hit)
            per_meeting[hit.meeting_id] = count + 1
        return selected

    @staticmethod
    def _cross_seed_hit_key(hit: RetrievalHit, intent: str) -> tuple[int, float, float]:
        if intent == "open_question":
            priority = {"discussion_qa": 0, "open_question": 1}
        elif intent == "action_item":
            priority = {"action_item": 0}
        elif intent == "decision":
            priority = {"decision": 0}
        else:
            # For overview/comparison/union synthesis, an Executive Summary is
            # the safest meeting representative. Lexical/semantic score breaks
            # ties within the same source type rather than overriding that rule.
            priority = {
                "summary": 0,
                "key_point": 1,
                "slide_summary": 2,
                "transcript": 3,
                "technical_terms": 6,
            }
        return (
            priority.get(hit.source_type, 5),
            -float(hit.lexical_score or 0.0),
            -float(hit.score or 0.0),
        )

    @classmethod
    def _cross_meeting_topic_match(cls, query: str, hit: RetrievalHit) -> bool:
        anchors = cls._content_tokens(query)
        if not anchors:
            return False
        hay = re.sub(
            r"[^a-z0-9]+",
            " ",
            f"{hit.source_label} {hit.text}".casefold(),
        ).strip()
        hay_tokens = set(cls._tokens(hay))
        unique = list(dict.fromkeys(anchors))
        matched = [token for token in unique if token in hay_tokens]
        if len(unique) == 1:
            return bool(matched)
        # Multi-token scientific terms should have at least two concrete token
        # matches. This prevents a generic word such as "phase" from making a
        # meeting eligible for a "phase retrieval" query.
        if len(matched) >= 2:
            return True
        phrase = " ".join(unique)
        return bool(phrase and phrase in hay)

    @staticmethod
    def _is_cross_meeting_query(query: str) -> bool:
        q = re.sub(r"\s+", " ", query.casefold()).strip()
        patterns = (
            "across meetings", "across all meetings", "all meetings", "our meetings",
            "which meeting", "which meetings", "between meetings", "different meetings",
            "both meetings", "compare meetings", "compare the meetings", "compare our meetings",
            "compare discussions", "compare the discussions", "common across", "overlap between",
            "summarize all meetings", "summary of all meetings", "topics across meetings",
        )
        if any(pattern in q for pattern in patterns):
            return True
        # Natural named comparisons such as:
        # "Compare Shahin's meeting with the holography demo meeting."
        return bool(
            re.search(r"\bcompare\b.*\bmeeting\b.*\b(?:with|to|and|vs\.?|versus)\b.*\bmeeting\b", q)
            or re.search(r"\bcompare\b.*\b(?:with|to|vs\.?|versus)\b.*\bmeeting\b", q)
        )

    @classmethod
    def _is_cross_meeting_overview_query(cls, query: str) -> bool:
        q = re.sub(r"\s+", " ", query.casefold()).strip()
        if not cls._is_cross_meeting_query(q):
            return False
        overview_patterns = (
            "compare meetings", "compare the meetings", "compare our meetings",
            "compare the topics", "summarize all meetings", "summary of all meetings",
            "topics across meetings", "topics across all meetings",
            "what are my meetings about", "overview of all meetings",
        )
        return (
            any(pattern in q for pattern in overview_patterns)
            or bool(re.search(r"\bcompare\b.*\bmeeting\b.*\b(?:with|to|and|vs\.?|versus)\b.*\bmeeting\b", q))
            or not cls._content_tokens(q)
        )

    @classmethod
    def _is_cross_meeting_synthesis_query(cls, query: str) -> bool:
        if not cls._is_cross_meeting_query(query):
            return False
        if cls._is_cross_meeting_overview_query(query):
            return True
        intent = cls._query_intent(query)
        if intent in {"open_question", "action_item", "decision"}:
            return True
        q = re.sub(r"\s+", " ", query.casefold()).strip()
        synthesis_markers = (
            "methods across", "method across", "methods were discussed across",
            "reconstruction methods", "image-processing", "image processing",
            "techniques across", "approaches across", "software across",
            "summarize the unresolved", "unresolved questions across",
        )
        return any(marker in q for marker in synthesis_markers)

    @staticmethod
    def _cross_meeting_seed_types(intent: str) -> set[str]:
        if intent == "open_question":
            return {"open_question", "discussion_qa"}
        if intent == "action_item":
            return {"action_item"}
        if intent == "decision":
            return {"decision"}
        if intent == "goal":
            return {"summary", "slide_summary", "key_point"}
        if intent == "method":
            return {"summary", "slide_summary", "key_point", "transcript"}
        return {"summary", "key_point", "slide_summary"}

    def _evidence_gate(
        self,
        query: str,
        hits: list[RetrievalHit],
        semantic_used: bool,
    ) -> tuple[bool, str]:
        if not hits:
            return False, "no_candidates"

        entities = self._required_entities(query)
        if entities:
            corpus = "\n".join(self._hit_search_text(hit) for hit in hits)
            matched_entities = [entity for entity in entities if entity.casefold() in corpus]
            if not matched_entities:
                return False, "named_entity_not_found"

        best = hits[0]
        if best.score < self.min_evidence_score:
            return False, "below_minimum_relevance"
        if (
            semantic_used
            and best.lexical_score <= 0
            and best.semantic_score is not None
            and best.semantic_score < self.min_semantic_score
        ):
            return False, "semantic_similarity_too_low"
        return True, "relevant_evidence_found"

    @classmethod
    def _is_near_duplicate(cls, hit: RetrievalHit, selected: list[RetrievalHit]) -> bool:
        left = set(cls._content_tokens(hit.text))
        if not left:
            return False
        for previous in selected:
            if previous.meeting_id != hit.meeting_id:
                continue
            right = set(cls._content_tokens(previous.text))
            if not right:
                continue
            union = left | right
            if union and len(left & right) / len(union) >= 0.74:
                return True
        return False

    @staticmethod
    def _no_evidence_answer(question: str) -> str:
        entities = RAGService._required_entities(question)
        if entities:
            target = ", ".join(entities)
            return f"I couldn't find any information about {target} in the indexed meetings."
        return "I couldn't find enough supporting evidence in the indexed meetings to answer that question."

    @staticmethod
    def _answer_indicates_no_evidence(answer: str) -> bool:
        lower = answer.casefold()
        markers = (
            "no information in the retrieved evidence",
            "no supporting meeting evidence",
            "could not find enough evidence",
            "couldn't find enough evidence",
            "could not find any information",
            "couldn't find any information",
            "the evidence does not contain",
            "the retrieved evidence does not contain",
            "not enough information in the retrieved",
            "cannot be determined from the retrieved",
            "can't be determined from the retrieved",
            "not mentioned in the retrieved",
            "not present in the retrieved",
        )
        return any(marker in lower for marker in markers)

    @staticmethod
    def _strip_citations(answer: str) -> str:
        text = re.sub(r"\[S\d+(?:\s*[-–]\s*S?\d+)?\]", "", answer, flags=re.IGNORECASE)
        return re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"[ \t]{2,}", " ", text)).strip()

    @staticmethod
    def _extract_citation_ids(answer: str) -> list[str]:
        found: list[str] = []
        for match in _CITATION_RE.finditer(answer):
            start_id = int(match.group(1)[1:])
            end_raw = match.group(2)
            if end_raw:
                end_id = int(end_raw.lstrip("Ss"))
                low, high = sorted((start_id, end_id))
                ids = [f"S{value}" for value in range(low, high + 1)]
            else:
                ids = [f"S{start_id}"]
            for source_id in ids:
                if source_id not in found:
                    found.append(source_id)
        return found

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if not left or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm <= 0 or right_norm <= 0:
            return 0.0
        return dot / (left_norm * right_norm)

    @staticmethod
    def _source_bonus(source_type: str) -> float:
        return {
            "summary": 0.055,
            "slide_summary": 0.045,
            "decision": 0.06,
            "action_item": 0.06,
            "open_question": 0.055,
            "discussion_qa": 0.05,
            "key_point": 0.045,
            "technical_terms": -0.035,
            "transcript": 0.0,
        }.get(source_type, 0.0)

    @classmethod
    def _build_retrieval_query(cls, question: str, history: list[dict[str, str]]) -> str:
        # Only genuinely referential follow-ups inherit the prior user turn.
        # A short but self-contained new topic ("Tell me about Otsu segmentation")
        # must not be contaminated by a previous weather/general question.
        if len(question.split()) >= 9 or not cls._is_contextual_followup(question):
            return question
        prior_users = [
            str(item.get("content") or "").strip()
            for item in history
            if str(item.get("role") or "").lower() == "user" and str(item.get("content") or "").strip()
        ]
        if prior_users:
            return f"{prior_users[-1]} {question}".strip()
        return question

    @staticmethod
    def _is_contextual_followup(question: str) -> bool:
        q = re.sub(r"\s+", " ", question.casefold()).strip(" ?!.,")
        if not q:
            return False
        if q.startswith(("what about ", "how about ", "and ", "but ", "why ", "how so", "what else")):
            return True
        tokens = set(re.findall(r"[a-z0-9']+", q))
        referential = {"it", "its", "this", "that", "these", "those", "they", "them", "former", "latter"}
        ordinal = {"first", "second", "third", "previous", "next", "other", "another"}
        return bool(tokens & referential) or bool(tokens & ordinal)

    @staticmethod
    def _scientific_reference(question: str) -> str | None:
        q = question.casefold()
        if "otsu" in q:
            return (
                "For Otsu thresholding, the standard criterion chooses a threshold that MAXIMIZES "
                "between-class variance; equivalently it MINIMIZES weighted within-class variance. "
                "Do not say that Otsu minimizes inter-class/between-class variance. The method works "
                "directly from the intensity histogram and does not require fitting a two-Gaussian "
                "mixture model. If a formula is requested, use "
                "sigma_B^2(t)=omega_0(t) omega_1(t) [mu_0(t)-mu_1(t)]^2 and "
                "t*=argmax_t sigma_B^2(t)."
            )
        return None

    @classmethod
    def _canonical_scientific_answer(cls, question: str) -> str | None:
        q = question.casefold()
        if "otsu" not in q:
            return None
        asks_formula = any(term in q for term in ("formula", "equation", "mathematical", "show the math"))
        if asks_formula:
            return r"""Otsu's method chooses the threshold that maximizes the **between-class variance**:

$$
\sigma_B^2(t)=\omega_0(t)\,\omega_1(t)\left[\mu_0(t)-\mu_1(t)\right]^2
$$

The optimal threshold is

$$
t^*=\operatorname*{arg\,max}_{t}\;\sigma_B^2(t).
$$

Here, $\omega_0(t)$ and $\omega_1(t)$ are the class probabilities and $\mu_0(t)$ and $\mu_1(t)$ are the class mean intensities. Maximizing between-class variance is equivalent to minimizing the weighted within-class variance."""
        if any(term in q for term in ("otsu segmentation", "otsu threshold", "otsu method", "about otsu", "what is otsu")):
            return (
                "Otsu's method is a global histogram-based thresholding technique that automatically "
                "separates grayscale intensities into classes. It evaluates candidate thresholds and "
                "chooses the threshold that **maximizes between-class variance**; equivalently, it "
                "minimizes the weighted within-class variance. It does not require fitting a Gaussian-"
                "mixture model, although it works best when the classes are reasonably separable in the histogram."
            )
        return None

    @staticmethod
    def _equation_policy(question: str) -> str:
        q = question.casefold()
        explicit_math = (
            "equation", "formula", "derive", "derivation", "mathematical definition",
            "write the math", "show the math", "transform", "integral", "fourier",
            "laplace", "gradient", "loss function",
        )
        if any(term in q for term in explicit_math):
            return (
                "A canonical defining equation may be included when it helps. Use only a standard, "
                "well-established form and render it as display LaTeX."
            )
        return (
            "Prefer prose. Do not add an equation unless it is indispensable to answer the question; "
            "never manufacture a formula merely to make the answer look technical."
        )
