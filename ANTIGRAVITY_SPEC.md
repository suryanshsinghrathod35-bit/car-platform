# Indian Car Platform: Phase 1 spec (paste this into Antigravity)

## Goal
Phase 1 = skeleton only: DB schema, 10 seeded car models, read API, one write endpoint. No scraping, no LLM calls, no frontend yet.

## Ground rules (do not break these)
1. Facts layer vs opinion layer. This phase only touches facts.
2. Any price MUST have `source_url` and `last_verified`. Enforced in BOTH the Pydantic schema and a DB CHECK constraint (`price_requires_provenance`). Never remove either.
3. Seed data holds only slow-changing identity facts (brand, model, body type, segment). Never invent prices, specs, or safety ratings.
4. Run `python -m pytest -q` after every change. All tests must pass before you say you're done.
5. Do not add features outside this spec. If something seems missing, list it under "Suggestions" instead of building it.

## Stack
Python 3.12, FastAPI, SQLAlchemy 2.x, SQLite for dev (DATABASE_URL env var switches to Postgres later), pytest.

## Run
    pip install -r requirements.txt
    python -m app.seed
    uvicorn app.main:app --reload     # docs at /docs
    python -m pytest -q

## Done when
- All tests in tests/test_phase1.py pass
- /docs shows: GET /health, /brands, /models, /models/{brand}/{model}; POST /models/{brand}/{model}/variants
- You report which tests you ran and their output, verbatim
