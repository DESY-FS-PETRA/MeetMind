# Distribution validation

Checked on 2026-10-19 using Python 3.12 in an isolated Linux virtual environment.

| Check | Result |
| --- | --- |
| Install `backend/requirements.txt` | Passed |
| `python -m unittest discover -s tests -v` from `backend/` | **143 tests passed in 6.700 s** |
| `python -m compileall -q backend` | Passed |
| `node --check frontend/app.js` | Passed |
| Synthetic meeting seed and removal, isolated SQLite database | Passed |
| API requests to `/`, `/meetings`, `/openapi.json` | HTTP 200 with Whisper constructors mocked |

The full API lifespan, real Whisper inference, GPU execution, live microphone capture, real Ollama/OpenAI generation, and browser interaction were not exercised. The API smoke check used FastAPI TestClient without a lifespan context and substituted Whisper model constructors to avoid downloading model weights. It validates import, routing, and basic database access only.

Some tests intentionally simulate unavailable model services and print error messages; the suite completed with `OK`.

`backend/requirements-tested-py312.txt` records the installed dependency versions for this check. It is an environment snapshot, not a claim of cross-platform compatibility. Python 3.11 is configured in CI but has not yet been checked by a hosted run.

## Distribution preparation

- Excluded the original `.env`, SQLite database, uploaded recording, and Python bytecode caches.
- Retained `.env.example`, with CPU/int8 recognition settings for an accessible starting configuration.
- Moved historical phase notes into `docs/development/`.
- Added a root README, `.gitignore`, and GitHub Actions workflow.
- Kept application source behavior unchanged.

A heuristic scan of release text found no common OpenAI/Hugging Face token patterns or private-key headers. This is not a comprehensive secrets audit. The original upload remains separate and may contain private configuration/data; publish the cleaned distribution rather than the uploaded archive.
