Phase 1 skeleton. See ANTIGRAVITY_SPEC.md. Tests: `python -m pytest -q`

> **Note**: SQLite `create_all` does not add new constraints to existing tables. Delete `cars.db` and run `python -m app.seed` after pulling this change to recreate the database with all constraints.

All timestamps are stored as naive UTC. Scripts must use datetime.now(timezone.utc), never datetime.now().
