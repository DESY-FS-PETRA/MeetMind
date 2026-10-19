# Phase 6.3 — Live Utilities & Scientific Chat Rendering

Phase 6.3 builds on Phase 6.2 and improves the Chat tab in five focused areas.

## 1. Scientific Markdown + LaTeX rendering

Assistant messages are no longer inserted as plain text. The frontend now safely renders a small Markdown subset:

- headings
- paragraphs
- bold / italic text
- bullet and numbered lists
- inline code and fenced code blocks
- Markdown tables
- meeting citations such as `[S1]`

MathJax 4 renders TeX/LaTeX in dynamic Chat messages. Both inline and display delimiters are supported:

```text
$E = mc^2$
```

```text
$$
F(\omega)=\int_{-\infty}^{\infty} f(t)e^{-i\omega t}\,dt
$$
```

The general, hybrid, and meeting-RAG prompts tell Ollama to put mathematical expressions inside math delimiters rather than returning bare commands such as `\frac` or `\int`.

MathJax is loaded from jsDelivr. If the CDN is unavailable, Chat remains usable and the original LaTeX text remains visible.

## 2. Live weather route

Weather questions no longer go to Ollama. They are routed to a dedicated live-weather handler using Open-Meteo.

Examples:

```text
weather today
what is the weather in Hamburg today?
tell me weather temperature for today
```

When no city is supplied, the browser requests geolocation permission only for the weather question. Coordinates are sent to the local FastAPI backend, which requests current/daily weather from Open-Meteo. Coordinates are not written to the meeting database.

If browser location is denied, Chat asks for a city rather than hallucinating weather.

If a city is explicitly supplied, the backend resolves it with Open-Meteo's geocoding endpoint before requesting the forecast.

Returned weather includes, when available:

- current temperature
- apparent temperature
- current condition
- today's high and low
- maximum precipitation probability
- current wind speed

## 3. Citation renumbering

After unused retrieved sources are removed, the answer and source cards are renumbered contiguously.

Before:

```text
... [S1][S2][S4]
Sources: S1, S2, S4
```

After:

```text
... [S1][S2][S3]
Sources: S1, S2, S3
```

The numbering order follows first use in the generated answer.

## 4. Better evidence weighting

`Technical Terms` chunks are now treated as supporting metadata rather than strong explanatory evidence. Slide summaries, key points, executive summaries, Q&A, and transcript evidence rank above a bare terminology list when they contain comparable query evidence.

This particularly improves general+meeting questions such as:

```text
Tell me about Otsu segmentation.
```

## 5. Concise general answers

The general Ollama prompt now defaults to a compact answer (usually 2–4 short paragraphs or up to 8 bullets). Longer explanations are produced when the user explicitly asks for detail or derivation.

## API changes

`POST /rag/ask` accepts three optional fields:

```json
{
  "question": "weather today",
  "history": [],
  "top_k": 8,
  "latitude": 53.55,
  "longitude": 10.0,
  "timezone": "Europe/Berlin"
}
```

Weather responses use:

```json
{
  "route": "weather",
  "route_label": "Live weather",
  "live_data_source": "Open-Meteo",
  "needs_location": false,
  "sources": []
}
```

## Browser version

```text
APP.JS 2026-08-14.22 LOADED
```

Both `app.js` and `style.css` cache-busting versions were updated.

## Tests

Phase 6.3 adds regression coverage for:

- weather with browser coordinates
- weather with a city name + geocoding
- missing weather location behavior
- citation renumbering after source filtering
- concise Markdown/LaTeX prompt instructions
- lower ranking for Technical Terms evidence

Expected full test result:

```text
Ran 101 tests
OK
```
