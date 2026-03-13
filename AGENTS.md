# AGENTS.md

## Purpose
- This file is the working guide for agentic coding assistants in this repository.
- Follow these rules when implementing changes, running checks, and proposing refactors.
- Prefer small, safe edits that match the existing architecture and coding style.

## Repository Snapshot
- Primary runtime entrypoint: `main.py`.
- Router modules: `handlers/profile.py`, `handlers/payments.py`, `handlers/tarot.py`, `handlers/admin.py`.
- Core modules: `database/` (ORM package), `ai_client.py`, `logic.py`, `keyboards.py`, `payments.py`, `my_yoomoney.py`.
- Data module: `tarot_data.py` (deck constants).
- Optional/legacy helper script: `dd/123.py`.
- Token validation script: `test_token.py`.
- Migration helper: `scripts/migrate_sqlite_to_postgres.py`.
- SQLite DB files in repo root are legacy/runtime artifacts (do not commit updates).
- No `pyproject.toml`, `requirements.txt`, `pytest.ini`, `tox.ini`, or `Makefile` were found.

## Cursor / Copilot Rules
- No `.cursorrules` file found.
- No `.cursor/rules/` directory with rule files found.
- No `.github/copilot-instructions.md` found.
- If any of these files are later added, merge their guidance into this document.

## Environment Assumptions
- Language: Python (async-heavy bot code).
- Runtime style: long-running Telegram bot process with scheduler jobs.
- Expected Python version: 3.10+ (code uses union operator `|` in type annotations).
- Preferred DB backend: PostgreSQL via `asyncpg`.

## Setup Commands
- Create virtual environment:
  - Windows (PowerShell): `python -m venv .venv`
  - POSIX: `python -m venv .venv`
- Activate environment:
  - Windows (PowerShell): `.\.venv\Scripts\Activate.ps1`
  - POSIX: `source .venv/bin/activate`
- Install dependencies (no lockfile currently present):
  - `pip install aiogram apscheduler asyncpg aiosqlite openai aiocryptopay yoomoney sqlalchemy requests`

## Run Commands
- Run the bot locally: `python main.py`
- Run YoMoney token smoke check: `python test_token.py`
- Run OAuth helper script (interactive): `python dd/123.py`

## Build / Lint / Test Commands
- There is no formal build pipeline in this repo.
- Use syntax compilation as a build-equivalent safety check:
  - `python -m compileall .`

- There is no committed linter config.
- Recommended lint command (if `ruff` is installed):
  - `python -m ruff check .`
- Recommended format command (if `ruff` is installed):
  - `python -m ruff format .`

- There is no committed automated test suite yet.
- Recommended default once tests are added under `tests/`:
  - Run all tests: `python -m pytest -q`
  - Run a single test file: `python -m pytest tests/test_file.py -q`
  - Run a single test case: `python -m pytest tests/test_file.py::test_name -q`
  - Run a single test method: `python -m pytest tests/test_file.py::TestClass::test_name -q`

- Current practical smoke tests in this repository:
  - `python test_token.py`
  - Start bot and verify `/start`, reading flow, subscription checks, and payment callbacks manually.

## Code Style: Imports
- Use absolute imports within repo modules (current pattern): `import config`, `import database`, etc.
- Import order:
  1) Python standard library
  2) Third-party libraries
  3) Local application modules
- Keep one import per line unless imports are tightly related.
- Do not use wildcard imports.
- Remove unused imports when touching a file.

## Code Style: Formatting
- Follow PEP 8 defaults.
- Prefer line length around 88-100 chars; avoid deeply wrapped expressions.
- Keep functions focused; split very long handlers when adding major logic.
- Prefer explicit temporary variable names over dense one-liners.
- Keep message templates readable with grouped multiline strings.

## Code Style: Typing
- Add type hints to new functions and modified public functions.
- For async handlers, annotate framework types explicitly (`types.Message`, `types.CallbackQuery`).
- Use `dict[str, Any]`/`list[dict[str, Any]]` style for Python 3.10+.
- Prefer `TypedDict` or dataclass models for structured dictionaries introduced by new code.
- Keep return types explicit for utility and database-layer functions.

## Naming Conventions
- Functions/variables: `snake_case`.
- Classes: `PascalCase`.
- Constants: `UPPER_SNAKE_CASE`.
- Callback data keys should stay concise and consistent (`prefix_action_value`).
- Keep handler names action-oriented (e.g., `check_subscription_handler`).

## Async and Concurrency Rules
- Runtime bot code should stay async end-to-end.
- Do not add blocking network calls in async handlers.
- Use non-blocking clients/libraries in bot execution paths.
- If unavoidable blocking I/O is introduced, isolate it behind async wrappers/executors.
- Preserve scheduler behavior and avoid long blocking jobs in cron callbacks.

## aiogram-Specific Guidelines
- Register handlers with clear filters and avoid overlapping ambiguous callbacks.
- Always `await callback.answer()` for callback queries unless there is a strong reason not to.
- Keep parse mode consistent when sending HTML-formatted responses.
- Reuse keyboard factories from `keyboards.py`; do not inline large keyboards repeatedly.
- When adding states, extend `TarotStates` and keep transitions explicit.

## Database Guidelines
- Current primary persistence path is `database/` with SQLAlchemy ORM async engine.
- Use parameterized SQL (`:name` bind params), never string interpolation for values.
- If dynamic column names are needed, validate against an allowlist before query composition.
- Preserve backward compatibility in migrations (non-destructive `ALTER TABLE` guards).
- Return plain dictionaries from DB layer for consistency with existing code.

## Error Handling and Logging
- Avoid bare `except:` in new or modified code.
- Catch specific exception types where practical.
- Log actionable context with `logging.error(...)` or `logging.exception(...)`.
- Do not leak secrets/tokens in logs, messages, stack traces, or error payloads.
- User-facing errors should be short, safe, and non-technical.

## Security and Secrets
- `config.py` currently contains hardcoded secrets; treat this as sensitive material.
- Never print or expose token values in commits, logs, tests, or PR descriptions.
- Prefer environment-variable based loading for new secret values.
- Do not commit new `.db`, token dumps, or credential text files.

## Domain-Specific Rules
- Bot responses are HTML-formatted for Telegram; keep output HTML-safe.
- Keep Russian-language UX text consistent with existing product voice.
- Preserve pricing/subscription semantics when editing payment flows.
- Keep referral reward logic idempotent and guarded against duplicate payouts.

## Change Management for Agents
- Make minimal, targeted edits.
- If touching critical flows (payments/subscriptions/admin), add validation notes in your final message.
- Prefer updating existing modules over introducing new abstraction layers for small fixes.
- When adding dependencies, document install/run impact in this file and in task notes.

## Validation Checklist Before Finishing
- Code compiles: `python -m compileall .`
- Lint passes if available: `python -m ruff check .`
- Bot starts without import/runtime errors: `python main.py`
- Relevant smoke path tested for changed area (command, callback, DB mutation, or payment step).

## If You Add Real Tests Later
- Place tests under `tests/`.
- Name files `test_*.py` and tests `test_*`.
- Keep unit tests deterministic and avoid external network calls.
- Mock API providers (`openai`, CryptoBot, YoMoney) for unit-level coverage.
- Update this file with exact test commands once test infra is committed.
