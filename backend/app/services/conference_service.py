from __future__ import annotations

import csv
import io
import re
import asyncio
from collections import Counter
from datetime import datetime, timezone, timedelta
from html import unescape
from urllib.parse import urljoin
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import delete, select

from app.database.models import ConferenceModel, ConferenceTalkModel
from app.storage.meeting_storage import MeetingStorage


_STOPWORDS = {
    "the","and","for","with","from","into","using","use","via","towards","toward","based",
    "study","studies","new","high","xray","x-ray","x","of","in","on","at","to","a","an","by",
    "or","as","is","are","this","that","their","our","your","through","between","over","under",
}


class ConferenceService:
    def __init__(self, storage: MeetingStorage) -> None:
        self.storage = storage

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        conference = ConferenceModel(
            id=str(uuid4()),
            name=str(payload.get("name") or "Conference").strip(),
            location=str(payload.get("location") or "").strip(),
            start_date=payload.get("start_date") or None,
            end_date=payload.get("end_date") or None,
            program_url=payload.get("program_url") or None,
            description=str(payload.get("description") or "").strip(),
            global_terms=self._clean_terms(payload.get("global_terms") or []),
            created_at=datetime.now(timezone.utc),
        )
        with self.storage.database.session_factory.begin() as session:
            session.add(conference)
        return self.get(conference.id) or {}

    def list(self) -> list[dict[str, Any]]:
        with self.storage.database.session_factory() as session:
            rows = session.scalars(select(ConferenceModel).order_by(ConferenceModel.created_at.desc())).all()
            result = []
            for row in rows:
                talks = session.scalars(select(ConferenceTalkModel).where(ConferenceTalkModel.conference_id == row.id)).all()
                result.append(self._conference_dict(row, talks))
            return result

    def get(self, conference_id: str) -> dict[str, Any] | None:
        with self.storage.database.session_factory() as session:
            conference = session.get(ConferenceModel, conference_id)
            if conference is None:
                return None
            talks = session.scalars(
                select(ConferenceTalkModel)
                .where(ConferenceTalkModel.conference_id == conference_id)
                .order_by(ConferenceTalkModel.start_at, ConferenceTalkModel.session_name, ConferenceTalkModel.title)
            ).all()
            return self._conference_dict(conference, talks)

    def delete(self, conference_id: str) -> bool:
        with self.storage.database.session_factory.begin() as session:
            row = session.get(ConferenceModel, conference_id)
            if row is None:
                return False
            session.delete(row)
        return True

    def bulk_import(self, conference_id: str, talks: list[dict[str, Any]], *, replace: bool = False) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self.storage.database.session_factory.begin() as session:
            conference = session.get(ConferenceModel, conference_id)
            if conference is None:
                raise FileNotFoundError("Conference not found")
            if replace:
                session.execute(delete(ConferenceTalkModel).where(ConferenceTalkModel.conference_id == conference_id))
            imported = 0
            for index, raw in enumerate(talks, start=1):
                title = str(raw.get("title") or "").strip()
                if not title:
                    continue
                external_id = str(raw.get("external_id") or "").strip() or self._stable_external_id(raw, index)
                existing = session.scalar(select(ConferenceTalkModel).where(
                    ConferenceTalkModel.conference_id == conference_id,
                    ConferenceTalkModel.external_id == external_id,
                ))
                auto_terms = self.context_terms_for_talk(raw, conference_terms=conference.global_terms)
                values = dict(
                    title=title,
                    speaker=str(raw.get("speaker") or "").strip(),
                    institution=str(raw.get("institution") or "").strip(),
                    session_name=str(raw.get("session_name") or "").strip(),
                    track=str(raw.get("track") or "").strip(),
                    room=str(raw.get("room") or "").strip(),
                    day_label=str(raw.get("day_label") or "").strip(),
                    start_at=raw.get("start_at") or None,
                    end_at=raw.get("end_at") or None,
                    abstract=str(raw.get("abstract") or "").strip(),
                    keywords=self._clean_terms(raw.get("keywords") or []),
                    context_terms=self._clean_terms((raw.get("context_terms") or []) + auto_terms),
                    notes=(existing.notes if existing is not None and "notes" not in raw else str(raw.get("notes") or "").strip()),
                    interesting=(existing.interesting if existing is not None and "interesting" not in raw else bool(raw.get("interesting", False))),
                    updated_at=now,
                )
                if existing is None:
                    session.add(ConferenceTalkModel(
                        id=str(uuid4()), conference_id=conference_id, external_id=external_id,
                        meeting_id=None, created_at=now, **values,
                    ))
                else:
                    for key, value in values.items():
                        setattr(existing, key, value)
                imported += 1
        result = self.get(conference_id) or {}
        result["imported"] = imported
        return result

    async def import_program_url(self, conference_id: str, url: str) -> dict[str, Any]:
        # Keep the same HTTP client alive for both the schedule page and the
        # per-talk detail/abstract requests.  Some conference sites (including
        # APTOR) expose abstracts only after the user clicks a presentation.
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "MeetMind/1.2 Conference Importer"},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text
            conference = self.get(conference_id) or {}
            talks = self._parse_program_html(
                html, conference_start_date=conference.get("start_date")
            )
            if not talks:
                raise ValueError(
                    "No talks could be detected on the program page. "
                    "This page may require a site-specific parser or JSON import."
                )
            await self._enrich_talks_from_detail_pages(client, url, html, talks)

        result = self.bulk_import(conference_id, talks, replace=False)
        with self.storage.database.session_factory.begin() as session:
            conf = session.get(ConferenceModel, conference_id)
            if conf is not None:
                conf.program_url = url
        result["source_url"] = url
        result["parser"] = "dom-tolerant-program-v2"
        return result

    async def _enrich_talks_from_detail_pages(self, client: httpx.AsyncClient, program_url: str, program_html: str, talks: list[dict[str, Any]]) -> None:
        """Fetch clickable talk pages and attach abstract/keywords as ASR context metadata."""
        links = self._talk_detail_links(program_url, program_html, talks)
        semaphore = asyncio.Semaphore(8)
        async def enrich(talk: dict[str, Any]) -> None:
            url = links.get(str(talk.get("external_id") or "").upper())
            if not url:
                return
            try:
                async with semaphore:
                    response = await client.get(url)
                    response.raise_for_status()
                abstract, keywords = self._parse_talk_detail_html(response.text)
            except Exception:
                return
            if abstract:
                talk["abstract"] = abstract
            if keywords:
                talk["keywords"] = self._clean_terms(list(talk.get("keywords") or []) + keywords)
            talk["context_terms"] = self.context_terms_for_talk(talk)
        await asyncio.gather(*(enrich(t) for t in talks))

    def _talk_detail_links(self, program_url: str, html: str, talks: list[dict[str, Any]]) -> dict[str, str]:
        codes = {str(t.get("external_id") or "").upper() for t in talks if t.get("external_id")}
        result: dict[str, str] = {}
        anchor_re = re.compile(r"<a\b[^>]*href\s*=\s*[\"'](?P<href>[^\"'#]+)[\"'][^>]*>(?P<body>.*?)</a>", re.I | re.S)
        for m in anchor_re.finditer(html):
            body = unescape(re.sub(r"<[^>]+>", " ", m.group("body")))
            upper = re.sub(r"\s+", " ", body).upper()
            for code in codes:
                if re.search(rf"(?<![A-Z0-9]){re.escape(code)}(?![A-Z0-9])", upper):
                    result.setdefault(code, urljoin(program_url, unescape(m.group("href"))))
        for code in codes - result.keys():
            pos = html.upper().find(code)
            if pos < 0:
                continue
            a, b = max(0, pos-700), min(len(html), pos+700)
            candidates=[]
            for hm in re.finditer(r"href\s*=\s*[\"']([^\"'#]+)[\"']", html[a:b], re.I):
                candidates.append((abs((a+hm.start())-pos), hm.group(1)))
            if candidates:
                href=min(candidates)[1]
                if not re.search(r"\.(?:css|js|png|jpg|jpeg|svg|ico)(?:\?|$)", href, re.I):
                    result[code]=urljoin(program_url, unescape(href))
        return result

    def _parse_talk_detail_html(self, html: str) -> tuple[str, list[str]]:
        cleaned=re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", html)
        cleaned=re.sub(r"(?i)<br\s*/?>", "\n", cleaned)
        cleaned=re.sub(r"(?i)</(?:p|div|section|article|li|h[1-6]|tr)>", "\n", cleaned)
        visible=unescape(re.sub(r"<[^>]+>", " ", cleaned)).replace("\xa0", " ")
        lines=[re.sub(r"\s+", " ", x).strip() for x in visible.splitlines()]
        lines=[x for x in lines if x]
        abstract=""; keywords=[]
        stop=re.compile(r"(?i)^(keywords?|palavras[- ]chave|authors?|autores?|presenter|apresentador|institution|affiliation|room|sala|track|session|references?|acknowledg)")
        alabel=re.compile(r"(?i)^(abstract|resumo)\s*:?\s*(.*)$")
        klabel=re.compile(r"(?i)^(keywords?|palavras[- ]chave)\s*:?\s*(.*)$")
        for i,line in enumerate(lines):
            km=klabel.match(line)
            if km and km.group(2).strip(): keywords.extend(re.split(r"\s*[;,•]\s*", km.group(2).strip()))
            am=alabel.match(line)
            if not am: continue
            pieces=[am.group(2).strip()] if am.group(2).strip() else []
            for nxt in lines[i+1:]:
                if stop.match(nxt): break
                pieces.append(nxt)
                if sum(map(len,pieces)) > 12000: break
            candidate=" ".join(pieces).strip()
            if len(candidate)>=80:
                abstract=candidate[:16000]; break
        if not abstract:
            meta=re.search(r"(?is)<meta[^>]+(?:name|property)=[\"'](?:description|og:description)[\"'][^>]+content=[\"'](.*?)[\"']", html)
            if meta:
                candidate=re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", meta.group(1)))).strip()
                if len(candidate)>=120: abstract=candidate[:16000]
        return abstract, self._clean_terms([k for k in keywords if k])

    def update_talk(self, talk_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        with self.storage.database.session_factory.begin() as session:
            talk = session.get(ConferenceTalkModel, talk_id)
            if talk is None:
                return None
            for key in ("notes", "interesting"):
                if payload.get(key) is not None:
                    setattr(talk, key, payload[key])
            for key in ("keywords", "context_terms"):
                if payload.get(key) is not None:
                    setattr(talk, key, self._clean_terms(payload[key]))
            talk.updated_at = datetime.now(timezone.utc)
        return self.get_talk(talk_id)

    def get_talk(self, talk_id: str) -> dict[str, Any] | None:
        with self.storage.database.session_factory() as session:
            talk = session.get(ConferenceTalkModel, talk_id)
            return self._talk_dict(talk) if talk is not None else None

    def link_meeting(self, talk_id: str, meeting_id: str) -> None:
        with self.storage.database.session_factory.begin() as session:
            talk = session.get(ConferenceTalkModel, talk_id)
            if talk is None:
                raise FileNotFoundError("Conference talk not found")
            talk.meeting_id = meeting_id
            talk.updated_at = datetime.now(timezone.utc)

    def scoped_meeting_ids(self, conference_id: str, *, scope: str, day_label: str | None = None,
                           session_name: str | None = None, talk_ids: list[str] | None = None) -> list[str]:
        statement = select(ConferenceTalkModel).where(ConferenceTalkModel.conference_id == conference_id)
        if scope == "day" and day_label:
            statement = statement.where(ConferenceTalkModel.day_label == day_label)
        elif scope == "session" and session_name:
            statement = statement.where(ConferenceTalkModel.session_name == session_name)
        elif scope == "selected" and talk_ids:
            statement = statement.where(ConferenceTalkModel.id.in_(talk_ids))
        with self.storage.database.session_factory() as session:
            talks = session.scalars(statement).all()
            return [t.meeting_id for t in talks if t.meeting_id]

    def context_terms_for_talk(self, talk: dict[str, Any], *, conference_terms: list[str] | None = None) -> list[str]:
        manual = list(talk.get("keywords") or []) + list(talk.get("context_terms") or []) + list(conference_terms or [])
        corpus = " ".join(str(talk.get(k) or "") for k in ("title","abstract","session_name","track","speaker","institution"))
        # Preserve scientific phrases, acronyms, alphanumeric names and hyphenated terms.
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9+._/-]{2,}", corpus)
        counts = Counter(t for t in tokens if t.casefold() not in _STOPWORDS)
        ranked = [term for term, _ in counts.most_common(36)]
        # Add common multiword scientific phrases from title/abstract.
        words = re.findall(r"[A-Za-z][A-Za-z0-9+._/-]{2,}", corpus)
        for size in (3, 2):
            for i in range(max(0, len(words)-size+1)):
                phrase = " ".join(words[i:i+size])
                if any(w.casefold() in _STOPWORDS for w in words[i:i+size]):
                    continue
                if any(ch.isupper() for ch in phrase) or any("-" in w for w in words[i:i+size]):
                    ranked.append(phrase)
        return self._clean_terms(manual + ranked)[:48]

    def _conference_dict(self, row: ConferenceModel, talks: list[ConferenceTalkModel]) -> dict[str, Any]:
        days: list[str] = []
        sessions: list[str] = []
        for t in talks:
            if t.day_label and t.day_label not in days: days.append(t.day_label)
            if t.session_name and t.session_name not in sessions: sessions.append(t.session_name)
        return {
            "id": row.id, "name": row.name, "location": row.location,
            "start_date": row.start_date, "end_date": row.end_date,
            "program_url": row.program_url, "description": row.description,
            "global_terms": list(row.global_terms or []), "created_at": row.created_at.isoformat(),
            "talk_count": len(talks), "recorded_talk_count": sum(1 for t in talks if t.meeting_id),
            "interesting_count": sum(1 for t in talks if t.interesting),
            "days": days, "sessions": sessions,
            "talks": [self._talk_dict(t) for t in talks],
        }

    @staticmethod
    def _talk_dict(t: ConferenceTalkModel) -> dict[str, Any]:
        return {
            "id": t.id, "conference_id": t.conference_id, "external_id": t.external_id,
            "title": t.title, "speaker": t.speaker, "institution": t.institution,
            "session_name": t.session_name, "track": t.track, "room": t.room,
            "day_label": t.day_label, "start_at": t.start_at, "end_at": t.end_at,
            "abstract": t.abstract, "keywords": list(t.keywords or []),
            "context_terms": list(t.context_terms or []), "notes": t.notes,
            "interesting": bool(t.interesting), "meeting_id": t.meeting_id,
            "created_at": t.created_at.isoformat(), "updated_at": t.updated_at.isoformat(),
        }

    @staticmethod
    def _clean_terms(items: list[Any]) -> list[str]:
        out, seen = [], set()
        for item in items:
            term = re.sub(r"\s+", " ", str(item or "").strip()).strip(" ,;:")
            key = term.casefold()
            if not term or len(term) > 100 or key in seen:
                continue
            seen.add(key); out.append(term)
        return out

    @staticmethod
    def _stable_external_id(raw: dict[str, Any], index: int) -> str:
        seed = f"{raw.get('day_label','')}|{raw.get('start_at','')}|{raw.get('title','')}|{index}"
        return re.sub(r"[^a-z0-9]+", "-", seed.casefold()).strip("-")[:110] or f"talk-{index}"

    def _parse_program_html(self, html: str, *, conference_start_date: str | None = None) -> list[dict[str, Any]]:
        """Parse a conference program page into structured oral talks.

        The parser is intentionally dependency-free and has two layers:
        1) a DOM-tolerant text-node parser that works when a site splits times, codes,
           titles and speakers across separate table/span elements (e.g. APTOR), and
        2) a conservative line-based fallback for simpler program pages.

        Poster entries are not imported as timed talks unless an explicit per-poster
        time is present. Session-only plenaries with a single code but no repeated talk
        time inherit their session start/end time.
        """
        from html.parser import HTMLParser

        class _VisibleText(HTMLParser):
            _BLOCK = {
                "br", "p", "div", "li", "tr", "td", "th", "section", "article",
                "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "table",
                "tbody", "thead", "tfoot", "ul", "ol", "button",
            }

            def __init__(self) -> None:
                super().__init__(convert_charrefs=True)
                self.parts: list[str] = []
                self._skip = 0

            def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
                tag = tag.casefold()
                if tag in {"script", "style", "noscript", "svg"}:
                    self._skip += 1
                elif not self._skip and tag in self._BLOCK:
                    self.parts.append("\n")

            def handle_endtag(self, tag: str) -> None:
                tag = tag.casefold()
                if tag in {"script", "style", "noscript", "svg"} and self._skip:
                    self._skip -= 1
                elif not self._skip and tag in self._BLOCK:
                    self.parts.append("\n")

            def handle_data(self, data: str) -> None:
                if not self._skip and data:
                    self.parts.append(data)

        parser = _VisibleText()
        try:
            parser.feed(html)
            visible = unescape(" ".join(parser.parts))
        except Exception:
            visible = unescape(re.sub(r"(?is)<[^>]+>", " ", html))

        # Keep explicit line boundaries for session discovery, but also build a
        # whitespace-normalized stream so talk fields may span arbitrary HTML nodes.
        visible = visible.replace("\xa0", " ").replace("\u2013", "-").replace("\u2014", "-")
        lines = [re.sub(r"\s+", " ", x).strip() for x in visible.splitlines()]
        lines = [x for x in lines if x]
        stream = re.sub(r"\s+", " ", " \n ".join(lines)).strip()

        time_pat = r"(?:[01]?\d|2[0-3]):[0-5]\d"
        time_range_re = re.compile(rf"\b(?P<start>{time_pat})\s*-\s*(?P<end>{time_pat})\b")
        talk_re = re.compile(
            rf"(?P<start>{time_pat})\s*-\s*(?P<end>{time_pat})\s+"
            r"(?P<code>[A-Z0-9]{4,8})\s*-\s*"
            r"(?P<body>.*?)"
            rf"(?=(?:{time_pat}\s*-\s*{time_pat}\s+[A-Z0-9]{{4,8}}\s*-)|"
            r"(?:\s+ROOM\s*:)|(?:\s+Track\s*:)|"
            rf"(?:{time_pat}\s*-\s*{time_pat}\s+{time_pat}\s*-\s*{time_pat})|$)",
            re.IGNORECASE,
        )
        room_header_re = re.compile(
            rf"ROOM\s*:\s*(?P<room>.*?)\s+(?P<start>{time_pat})\s*-\s*(?P<end>{time_pat})\s+"
            rf"(?P<session>.*?)(?=(?:\s+{time_pat}\s*-\s*{time_pat}\s+Chair\s*:)|(?:\s+Chair\s*:)|(?:\s+ROOM\s*:)|$)",
            re.IGNORECASE,
        )

        def _clock(s: str) -> str:
            h, m = s.split(":", 1)
            return f"{int(h):02d}:{m}"

        def _minute(s: str) -> int:
            h, m = s.split(":", 1)
            return int(h) * 60 + int(m)

        def _date_label(day_index: int) -> str:
            if conference_start_date:
                try:
                    d = datetime.fromisoformat(str(conference_start_date)[:10]).date() + timedelta(days=day_index - 1)
                    return d.strftime("%a %d %b")
                except Exception:
                    pass
            return f"Day {day_index}"

        def _clean_session(value: str) -> str:
            value = re.sub(r"\[?Button\s*:\s*[^\]]+\]?", " ", value, flags=re.I)
            value = re.sub(r"\s+", " ", value).strip(" -")
            return value[:300]

        # Discover room/session headers and preserve their position in the stream.
        sessions: list[dict[str, Any]] = []
        for m in room_header_re.finditer(stream):
            session_name = _clean_session(m.group("session"))
            # APTOR commonly repeats the session time just before Chair; remove any
            # duplicate trailing range that survived a slightly different markup.
            session_name = re.sub(rf"\s*{time_pat}\s*-\s*{time_pat}\s*$", "", session_name).strip()
            sessions.append({
                "pos": m.start(),
                "room": re.sub(r"\s+", " ", m.group("room")).strip(" -")[:200],
                "session_name": session_name,
                "start": _clock(m.group("start")),
                "end": _clock(m.group("end")),
            })

        def _session_for(pos: int) -> dict[str, Any]:
            chosen: dict[str, Any] = {}
            for item in sessions:
                if item["pos"] <= pos:
                    chosen = item
                else:
                    break
            return chosen

        # Heuristic splitter for APTOR's "title speaker - institution" text. Even if
        # the speaker split is uncertain, the full title/body still contributes to
        # the scientific context pack.
        person_particles = {"de", "da", "do", "dos", "das", "van", "von", "der", "den", "del", "di", "la", "le"}
        technical_name_boundaries = {
            "imaging", "tomography", "microtomography", "nanotomography", "holotomography",
            "ptychography", "microscopy", "diffraction", "analysis", "framework", "materials",
            "material", "systems", "system", "dynamics", "reconstruction", "spectromicroscopy",
            "mapping", "beamline", "nanoprobe", "micro-ct", "ct", "stxm", "x-ray", "xray",
        }

        def _looks_name_token(tok: str) -> bool:
            clean = tok.strip(".,;:()[]{}")
            if not clean:
                return False
            if clean.casefold() in person_particles:
                return True
            if any(ch.isdigit() for ch in clean):
                return False
            # Technical hyphenated tokens (X-ray, phase-contrast, etc.) should not be
            # swallowed into the speaker name; human hyphenated surnames usually have
            # both sides capitalized.
            if "-" in clean:
                parts = [p for p in clean.split("-") if p]
                return bool(parts) and all(p[:1].isupper() for p in parts)
            return clean[:1].isupper()

        def _split_body(body: str) -> tuple[str, str, str]:
            body = re.sub(r"\s+", " ", body).strip(" -*•")
            body = re.sub(r"\s+Track\s*:\s*.*$", "", body, flags=re.I).strip()
            institution = ""
            head = body
            if " - " in body:
                head, institution = body.rsplit(" - ", 1)
                head, institution = head.strip(), institution.strip()
            invited = re.search(r"(?i)(.*?\(Invited Lecture\))\s*(.+)$", head)
            if invited:
                return invited.group(1).strip(), invited.group(2).strip(), institution
            tokens = head.split()

            # The schedule text has no explicit separator between title and speaker.
            # Prefer the *shortest plausible human-name suffix* (normally 2--4
            # tokens) instead of greedily consuming every capitalized title word.
            # This is important for titles ending in capitalized scientific words,
            # e.g. "... X-ray Holographic Data Vahid Rahmani".
            for size in range(2, min(5, len(tokens) - 1) + 1):
                candidate = tokens[-size:]
                title_tokens = tokens[:-size]
                if len(" ".join(title_tokens).strip()) < 12:
                    continue
                if not all(_looks_name_token(tok) for tok in candidate):
                    continue
                # A scientific/domain word is much more likely to belong to the
                # title than to the beginning of a person's name.
                first = candidate[0].strip(".,;:()[]{}").casefold()
                if first in technical_name_boundaries:
                    continue
                # Name particles are allowed internally but a two-token suffix is
                # preferred whenever it is already plausible.
                speaker = " ".join(candidate).strip()
                title = " ".join(title_tokens).strip()
                return title, speaker, institution
            return head, "", institution

        talks: list[dict[str, Any]] = []
        last_start: int | None = None
        day_index = 1
        seen_codes: set[str] = set()

        for m in talk_re.finditer(stream):
            start = _clock(m.group("start")); end = _clock(m.group("end"))
            start_min = _minute(start)
            if last_start is not None and start_min < last_start - 180:
                day_index += 1
            last_start = start_min
            code = m.group("code").upper()
            body = m.group("body")
            session = _session_for(m.start())
            if re.search(r"(?i)poster session", session.get("session_name", "")):
                continue
            title, speaker, institution = _split_body(body)
            if not title or len(title) < 10:
                continue
            talks.append({
                "external_id": code,
                "title": title[:2000],
                "speaker": speaker[:300],
                "institution": institution[:500],
                "session_name": session.get("session_name", ""),
                "track": "",
                "room": session.get("room", ""),
                "day_label": _date_label(day_index),
                "start_at": start,
                "end_at": end,
                "abstract": "",
                "keywords": [],
                "context_terms": [],
                "_source_pos": m.start(),
            })
            seen_codes.add(code)

        # APTOR occasionally omits a repeated per-talk time for a one-talk plenary.
        # Import those by inheriting the enclosing non-poster session time.
        code_only_re = re.compile(r"\b(?P<code>[A-Z0-9]{4,8})\s*-\s*(?P<body>.*?)(?=(?:\s+ROOM\s*:)|(?:\s+Track\s*:)|$)")
        for m in code_only_re.finditer(stream):
            code = m.group("code").upper()
            if code in seen_codes:
                continue
            session = _session_for(m.start())
            if not session or re.search(r"(?i)poster session", session.get("session_name", "")):
                continue
            # Only infer time for short/plenary-style sessions; avoids treating a block
            # of untimed poster abstracts as simultaneous talks.
            if _minute(session["end"]) - _minute(session["start"]) > 45:
                continue
            title, speaker, institution = _split_body(m.group("body"))
            if not title or len(title) < 10:
                continue
            # Determine its day from the nearest preceding timed talk in the source stream.
            preceding = [t for t in talks if int(t.get("_source_pos", -1)) <= m.start()]
            inferred_day = preceding[-1]["day_label"] if preceding else _date_label(1)
            talks.append({
                "external_id": code, "title": title[:2000], "speaker": speaker[:300],
                "institution": institution[:500], "session_name": session.get("session_name", ""),
                "track": "", "room": session.get("room", ""), "day_label": inferred_day,
                "start_at": session["start"], "end_at": session["end"], "abstract": "",
                "keywords": [], "context_terms": [], "_source_pos": m.start(),
            })
            seen_codes.add(code)

        # Generic fallback for simpler pages if the tolerant stream parser found none.
        if not talks:
            room = ""; session_name = ""; day_index = 1; last_start = None
            code_re = re.compile(r"\b([A-Z0-9]{3,8})\s*-\s*(.+)")
            for line in lines:
                rm = re.search(rf"(?i)ROOM\s*:\s*(.*?)\s+({time_pat})\s*-\s*({time_pat})\s+(.*)", line)
                if rm:
                    room = rm.group(1).strip(" -")
                    session_name = re.sub(r"(?i)\bChair\s*:.*$", "", rm.group(4)).strip(" -")
                    session_name = re.sub(rf"\s*{time_pat}\s*-\s*{time_pat}\s*$", "", session_name).strip()
                    continue
                tm = time_range_re.search(line)
                if not tm:
                    continue
                start = _clock(tm.group("start")); end = _clock(tm.group("end"))
                start_min = _minute(start)
                if last_start is not None and start_min < last_start - 180:
                    day_index += 1
                last_start = start_min
                rest = line[tm.end():].strip(" -*•")
                cm = code_re.match(rest)
                if not cm:
                    continue
                code, body = cm.group(1).upper(), cm.group(2)
                title, speaker, institution = _split_body(body)
                talks.append({
                    "external_id": code, "title": title[:2000], "speaker": speaker[:300],
                    "institution": institution[:500], "session_name": session_name, "track": "",
                    "room": room, "day_label": _date_label(day_index), "start_at": start,
                    "end_at": end, "abstract": "", "keywords": [], "context_terms": [],
                })

        # Stable de-duplication and chronological ordering while preserving day order.
        unique: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for t in talks:
            key = (t.get("external_id"), t.get("day_label"), t.get("start_at"))
            if key in seen:
                continue
            seen.add(key)
            t.pop("_source_pos", None)
            unique.append(t)
        return unique

