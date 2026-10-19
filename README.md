# MeetMind

**A local-first AI assistant for scientific meetings: transcription, slide-aware context, structured summaries, and evidence-based search across meetings.**

Developed by **Vahid Rahmani**, MeetMind combines a FastAPI backend with a browser interface. It helps turn live discussions and recorded meetings into a searchable working memory, with particular attention to scientific terminology, numerical statements, and the distinction between presentation content and spoken evidence.

## Capabilities

- **Live transcription:** stream browser audio over WebSockets and transcribe it with faster-whisper.
- **Recorded meetings:** process uploaded recordings with progress events and stored transcripts.
- **Scientific vocabulary:** bounded terminology hints, conservative corrections, and low-confidence word review.
- **Slide-aware meetings:** extract text from PPTX/PDF presentations, select slide context, and associate transcript evidence with slides.
- **Structured summaries:** generate key points, decisions, action items, open questions, technical terms, and slide summaries using Ollama or an optional OpenAI provider.
- **Persistent history:** store meeting records, transcripts, and summaries with SQLAlchemy and SQLite.
- **Cross-meeting retrieval:** index meeting content, retrieve relevant evidence, and answer questions with source references.
- **Conference workspace:** manage talk programs, import program information, enrich abstracts, and query conference content.

This checkout does not implement speaker diarization. Generated text and source references should be reviewed before being used as an official meeting record.

## Architecture

| Component | Implementation |
| --- | --- |
| Browser UI | Plain HTML, CSS, and JavaScript; no frontend build step |
| HTTP and streaming API | FastAPI and WebSockets |
| Speech recognition | faster-whisper / CTranslate2 |
| Browser audio decoding | FFmpeg subprocess |
| Summaries and answers | Ollama by default; optional OpenAI API |
| Semantic embeddings | Ollama, with `embeddinggemma` configured by default |
| Persistence | SQLAlchemy with a local SQLite database |
| Presentation text | python-pptx and pypdf |

The browser connects to the API at `127.0.0.1:8000`. Audio enters the transcription pipeline; transcript events update the UI and meeting storage. Summarization and retrieval operate on stored content, with slide context and scientific vocabulary used where applicable.

## Quick start

Python **3.11** is a practical starting point. Install FFmpeg and make sure `ffmpeg -version` works. Install and start Ollama if you want the default local language-model workflow.

From the project root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
cd backend
cp .env.example .env
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` from the project root and use `Copy-Item .env.example .env` inside `backend`.

The distributed example configuration uses CPU transcription:

```dotenv
WHISPER_MODEL=small.en
WHISPER_LANGUAGE=en
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
```

For a compatible NVIDIA/CTranslate2 environment, set `WHISPER_DEVICE=cuda` and `WHISPER_COMPUTE_TYPE=float16`. GPU library installation depends on the installed faster-whisper/CTranslate2 versions and is not provisioned by this repository.

Prepare the default local models:

```bash
ollama pull qwen3:4b-instruct
ollama pull embeddinggemma
```

The first model supports summaries and answers; the second supports semantic retrieval. Model downloads require internet access. The first backend startup also downloads the selected Whisper model if it is not cached.

Start the API **from `backend/`**:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal, start the frontend from the project root:

```bash
python -m http.server 3000 --bind 127.0.0.1 --directory frontend
```

Open **http://localhost:3000**. API documentation is available at **http://127.0.0.1:8000/docs**. Allow microphone access when recording live audio. The server loads the Whisper model during application import, so startup can take time.

## Try a synthetic meeting

A clearly labeled, fictional scientific meeting is provided as a seed script. It does not contain an actual meeting recording.

From `backend/`, with your virtual environment active:

```bash
python seed_cross_meeting_demo.py --no-index
```

Refresh meeting history in the UI to inspect the example. To create/index the demo with Ollama available, run the script without `--no-index`. To remove it:

```bash
python seed_cross_meeting_demo.py --remove --no-index
```

`conference_program_template.json` is a separate example of the conference program import format.

## Configuration

Copy `backend/.env.example` to `backend/.env` and adjust it locally. Keep the backend working directory consistent: relative database, presentation, and vocabulary paths are resolved from there.

| Setting | Purpose |
| --- | --- |
| `LLM_PROVIDER` | `ollama` by default; `openai` is optional |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | Local language-model service and model |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Optional hosted inference credentials and model |
| `DATABASE_URL` | Defaults in the example to `sqlite:///data/meeting_ai.db` |
| `WHISPER_*` | Recognition model, language, device, precision, and decoding options |
| `VOCABULARY_*` | Scientific terminology and correction limits |
| `PRESENTATION_*`, `SLIDE_*` | Presentation limits and slide context |
| `RAG_*` | Embedding model, chunking, retrieval, and evidence thresholds |

The example starts with the English-only `small.en` model. Other languages require an appropriate multilingual model and language configuration; their quality has not been validated here.

## Tests

From `backend/`:

```bash
python -m unittest discover -s tests -v
```

From the project root:

```bash
node --check frontend/app.js
```

**Distribution check: 143 tests passed** on Python 3.12. Exact installed versions are recorded in `backend/requirements-tested-py312.txt`.

The backend suite covers storage, transcript assembly and cleanup, vocabulary safety, presentation context, summaries, numeric validation, recorded processing, conference parsing, retrieval, and query routing. Many model/service interactions use test doubles; passing the suite does not validate real speech-recognition accuracy or real model output quality.

Root-level `backend/test_*.py` scripts are optional manual integration diagnostics and may require running services, local files, or GPU access. They are separate from the automated discovery command above. A GitHub Actions workflow is included; a hosted pass should only be claimed after it runs.

See [validation](docs/validation.md) for checks performed on this distribution.

## Data and deployment boundaries

- Uploaded recordings, presentations, meeting history, and `.env` files are excluded from this distribution and ignored by Git.
- The UI loads MathJax from a public CDN for mathematical rendering.
- With Ollama, model inference can run locally after model downloads. Selecting OpenAI sends relevant content to that provider. Program imports and selected utility queries may also access external services.
- The API has no application authentication or user-access isolation. The supplied commands bind to the local computer; a shared deployment needs authentication, authorization, HTTPS, and data-retention controls.
- The frontend API/WebSocket addresses are currently fixed in `frontend/app.js`, and CORS permits localhost on port 3000. Remote deployment requires configuration changes.
- Slide processing extracts text; it does not establish understanding of figures, equations embedded as images, or scanned PDF pages.
- Source references, confidence flags, and numerical validation help review results but do not guarantee factual accuracy.

## Project layout

| Path | Purpose |
| --- | --- |
| `backend/app/audio/`, `transcription/` | Audio ingestion, recognition, and transcript cleanup |
| `backend/app/ai/` | Model providers, prompts, and structured/numeric validation |
| `backend/app/presentation/`, `vocabulary/` | Slide extraction and terminology context |
| `backend/app/rag/` | Retrieval, evidence handling, and query routing |
| `backend/app/database/`, `storage/` | Database models and meeting persistence |
| `backend/app/services/` | Recorded meeting, summary, and conference workflows |
| `backend/tests/` | Automated regression tests |
| `frontend/` | Browser application |
| `docs/development/` | Historical phase notes and older setup instructions |

Historical development notes describe intermediate versions and may contain outdated paths, settings, and test counts. Use this README for the current distribution workflow.

## License

No project license was included in the supplied source. Select a license and confirm rights to the code and distributed resources before releasing it for reuse. Dependency licenses apply separately.
