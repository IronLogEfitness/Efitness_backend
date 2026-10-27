# IronLog API

Backend for the IronLog fitness tracker — FastAPI + MongoDB (Motor), with a
Gemini-powered **agentic** AI coach that can log, plan, and reschedule training on
the user's behalf (with human-in-the-loop confirmation).

[![Build and deploy to Azure](https://github.com/IronLogEfitness/Efitness_backend/actions/workflows/deploy.yml/badge.svg)](https://github.com/IronLogEfitness/Efitness_backend/actions/workflows/deploy.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

- 📱 **Mobile app:** [IronLogEfitness/Efitness_frontend](https://github.com/IronLogEfitness/Efitness_frontend) (Expo + React Native)
- 📖 **Live API docs (Swagger):** <https://efitness-backend-2530307.azurewebsites.net/docs>

## Tech stack

- **FastAPI** — web framework
- **MongoDB** + **Motor** — async database access
- **python-jose** + **passlib** — JWT auth & password hashing
- **google-genai** (Gemini 2.5 Flash) — AI coaching chat + **function calling**
- **pydantic-settings** — typed configuration
- **pytest** — deterministic unit tests (dev only, see `requirements-dev.txt`)

## Architecture

The code is organised **by feature**: each domain owns its router (controller),
service (business logic + data access), schemas (API models) and, where it has a
collection, its persistence model. Cross-cutting concerns live in `core/` and
`helpers/`.

```
main.py                  # entry point  →  uvicorn main:app
app/
├── __init__.py          # create_app() — builds the app and wires routers
├── config.py            # settings (pydantic-settings)
├── core/                # shared infrastructure
│   ├── database.py      #   Mongo connection lifecycle + get_db dependency
│   └── security.py      #   password hashing + JWT
├── helpers/             # shared, domain-agnostic helpers
│   ├── exceptions.py    #   AppError hierarchy + JSON handler
│   ├── objectid.py      #   ObjectId parsing/validation
│   ├── filters.py       #   query-param dependencies (pagination)
│   └── dates.py         #   now_utc()
├── auth/                # register / login / me   (+ dependencies.py: get_current_user)
├── muscles/             # GET /muscles            (read-only aggregation)
├── exercises/           # CRUD /exercises
├── workouts/            # CRUD /workouts          (day-level training sessions)
├── sessions/            # CRUD /sessions          (per-exercise set logs)
├── progress/            # stats & charts          (read-only aggregation)
├── chat/                # AI coach (Gemini)       (agent loop + /chat/confirm)
├── coach/               # agentic layer: tools, propose/confirm, /coach namespace
├── goals/               # CRUD /goals + deterministic trajectory
└── conversations/       # persistent chat memory, import & published references
```

Per feature:

| File              | Responsibility                                              |
| ----------------- | ----------------------------------------------------------- |
| `router.py`       | HTTP layer only: paths, status codes, `response_model`.     |
| `service.py`      | Business logic and database access. No FastAPI imports.     |
| `schemas.py`      | Pydantic request/response models (the API contract).        |
| `models.py`       | Shape of the stored MongoDB document (where one exists).    |

`muscles` and `progress` have no `models.py` — they derive everything from the
`exercises` / `sessions` collections. `chat` has none either: it orchestrates a
turn but stores nothing itself — persistence lives in `conversations`, which owns
the `conversations` and `messages` collections. The `coach` feature is split into
more focused files than the standard four (see
[Agentic AI coach](#agentic-ai-coach-function-calling) below) and owns the
`coach_actions` and `coach_cache` collections; `goals` owns `goals`.

### Request flow

```
HTTP → router (validates input, injects db + current_user)
     → service (business logic, talks to Mongo, raises AppError on failure)
     → router returns the result, serialised by response_model
```

Domain errors (`NotFoundError`, `BadRequestError`, ...) are raised in services
and turned into `{"detail": ...}` JSON by the handler registered in
`create_app()`, so the service layer never depends on FastAPI.

## Setup

```bash
python -m venv venv
venv\Scripts\activate            # Windows  (source venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
```

Then create a `.env` file in the project root — see **Configuration**.

## Configuration

Settings are read from environment variables / a `.env` file in the project root
(defined in `app/config.py`). `.env` is gitignored — **never commit it**.

| Variable                      | Required  | Default                     | Description |
| ----------------------------- | --------- | --------------------------- | ----------- |
| `ENV`                         | prod      | `production`                | Deployment environment. Any value other than `dev`/`development`/`local`/`test` is treated as production, which enforces the startup security checks below. Set `ENV=dev` locally to run with the placeholder secret. |
| `MONGO_URI`                   | yes       | `mongodb://localhost:27017` | MongoDB connection string |
| `DB_NAME`                     | yes       | `ironlog`                   | Database name |
| `SECRET_KEY`                  | yes       | insecure placeholder        | JWT signing secret — use a long random value, not reused from anywhere else. **In production the app refuses to boot while this is left at the default placeholder** (signing JWTs with a known value is a full auth bypass). |
| `ALGORITHM`                   | no        | `HS256`                     | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no        | `10080` (7 days)            | Access-token lifetime |
| `GEMINI_API_KEY`              | for chat  | empty                       | Google AI Studio key for the AI coach |
| `CORS_ORIGINS`                | prod      | `["*"]`                     | JSON array of allowed origins. `["*"]` is a dev default; in production set an explicit allowlist, e.g. `CORS_ORIGINS=["https://app.example.com"]`. The API uses Bearer tokens (no cookies), so CORS credentials mode is off. |

A minimal `.env`:

```
MONGO_URI=mongodb://localhost:27017
DB_NAME=ironlog
SECRET_KEY=replace-with-a-random-value
GEMINI_API_KEY=
```

Generate a strong `SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

> **Note:** `.env` changes are only applied when the server (re)starts —
> `--reload` watches `.py` files, not `.env`. Restart after editing it.

**Production checklist:** leave `ENV` unset (or set it to `production`), set a
strong random `SECRET_KEY`, and set `CORS_ORIGINS` to your app's real origin(s).
With `ENV` in production mode the app will refuse to start if `SECRET_KEY` is
still the placeholder, and will log a warning if `CORS_ORIGINS` is left at `["*"]`.

## Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

- Interactive docs (Swagger): http://127.0.0.1:8000/docs
- Health check:               http://127.0.0.1:8000/

## API

Every endpoint except `/`, `/auth/register`, and `/auth/login` requires an
`Authorization: Bearer <token>` header (the token is returned by register/login).

| Method | Path                       | Description |
| ------ | -------------------------- | ----------- |
| GET    | `/`                        | Health check |
| POST   | `/auth/register`           | Create account, returns a JWT |
| POST   | `/auth/login`              | Log in, returns a JWT |
| GET    | `/auth/me`                 | Current user's profile |
| PUT    | `/auth/me`                 | Update name / password |
| GET    | `/muscles`                 | Muscle groups with per-muscle exercise counts |
| GET    | `/exercises`               | List exercises (`?muscle=` filter) |
| POST   | `/exercises`               | Create an exercise |
| GET    | `/exercises/{id}`          | Exercise detail (with personal best, last session) |
| DELETE | `/exercises/{id}`          | Delete exercise (cascade-deletes its sessions) |
| GET    | `/sessions`                | List sessions (`?exercise_id=`, `?limit=`, `?skip=`) |
| POST   | `/sessions`                | Log a training session |
| GET    | `/sessions/{id}`           | Session detail |
| PUT    | `/sessions/{id}`           | Update sets / notes |
| DELETE | `/sessions/{id}`           | Delete a session |
| GET    | `/progress/overview`       | Overall stats + per-muscle breakdown |
| GET    | `/progress/exercise/{id}`  | Weight progression for one exercise (`?days=`) |
| POST   | `/chat`                    | AI coach — agentic turn; may return `proposed_actions` |
| POST   | `/chat/confirm`            | Apply the proposed actions the user accepted (idempotent) |
| POST   | `/conversations/import`    | Import a Gemini conversation (`messages` or pasted `raw_text`) |
| GET    | `/conversations`           | List conversations (`?source=`, `?is_published=`, `?limit=`, `?skip=`) |
| GET    | `/conversations/{id}`      | Conversation detail + messages |
| PUT    | `/conversations/{id}`      | Rename / publish / label a conversation |
| PATCH  | `/workouts/{id}`           | Partial update — notably reschedule (`{"date": "YYYY-MM-DD"}`) |
| GET    | `/coach/briefing`          | One-line pre-workout briefing for today (cached per day) |
| GET    | `/coach/recap`             | Weekly "wrapped" recap (`?week=YYYY-Www`, cached per week) |
| GET    | `/coach/progression`       | Next-session targets for a workout (`?workout_ref=`) |
| GET    | `/coach/balance`           | Push/pull/legs volume audit with imbalances |
| GET    | `/goals`                   | List goals (`?status=`) |
| POST   | `/goals`                   | Create a goal |
| GET    | `/goals/{id}`              | Goal detail |
| GET    | `/goals/{id}/trajectory`   | Deterministic on/off-track projection |
| PUT    | `/goals/{id}`              | Update / close a goal |
| DELETE | `/goals/{id}`              | Delete a goal |

## AI coach (Gemini)

`POST /chat` sends context to **Gemini 2.5 Flash** so replies reference the
user's real numbers. All reads are scoped to the logged-in user (derived from
the JWT, never the request body) — the model never sees another user's data.

Each turn assembles, in clearly separated blocks:

1. the user's **last 30 days of sessions**,
2. any **published reference material** matching `reference_labels` (see below),
3. the conversation's **rolling summary** of older turns, and
4. the **recent raw messages**, then the new message.

To enable it:

1. Create a free API key at <https://aistudio.google.com/apikey>
2. Put it in `.env` as `GEMINI_API_KEY=...`
3. Restart the server

Without a key, `/chat` returns `500 {"detail": "GEMINI_API_KEY not configured"}`;
every other endpoint works without it.

### Persistent memory

Conversations and messages are stored in MongoDB (`conversations` / `messages`).
A turn:

- omits `conversation_id` to **start** a thread, or passes the one returned by a
  previous call to **continue** it — the `conversation_id` is always in the
  response;
- saves both the user message and the assistant reply immediately after the API
  call, with a **token count per message** (assistant counts come from Gemini's
  usage metadata; others use a ~4-chars/token estimate, computed once at write
  time so reads never recount);
- once the active window (summary + unsummarised turns) passes
  `CHAT_SUMMARY_TOKEN_THRESHOLD`, folds the older turns into a stored **summary**
  and keeps the last `CHAT_HISTORY_LIMIT` raw — a sliding window. Raw messages
  are never deleted, only excluded from what's loaded.

> **Server owns history.** The old client-supplied `history` field on `/chat` is
> **deprecated** — it is accepted but ignored. Pass `conversation_id` instead.

### Importing Gemini conversations

`POST /conversations/import` stores an existing Gemini conversation as a new
record flagged `source: "gemini_import"`. Send **exactly one** of:

- `messages`: `[{ "role": "user|model|assistant", "content": "..." }]`, or
- `raw_text`: the conversation copy-pasted as text. It's parsed by, in order:
  role-marker lines (`User:` / `Gemini:` / …); else turns separated by a line of
  only `---` (alternating, your prompt first); else a `400` (it won't guess).

There is no machine export from gemini.google.com — open a conversation (or its
`/share/...` link), copy it, and paste into `raw_text`.

### Published reference material

Mark any conversation as reusable background with
`PUT /conversations/{id}` (`{"is_published": true, "label": "..."}`). When a
`/chat` request includes `reference_labels`, the user's **own** published
conversations with a matching label are injected as a separate reference block
(per-user only — never shared across users; label match for now, vector search
later).

### Config knobs

| Variable                       | Default | Description |
| ------------------------------ | ------- | ----------- |
| `CHAT_HISTORY_LIMIT`           | `10`    | Raw messages kept after summarising |
| `CHAT_SUMMARY_TOKEN_THRESHOLD` | `4000`  | Active-window token budget before older turns are summarised |

## Agentic AI coach (function calling)

Beyond answering questions, the coach can **act** on the app through Gemini
function calling — log sets from natural language, plan a week, reschedule a day,
set goals, and more. It runs under a strict **human-in-the-loop** rule: the model's
write tools are **never auto-executed**.

**The flow:**

1. `POST /chat` runs an agent loop (hard-capped at `COACH_MAX_TOOL_ITERATIONS`).
   **Read** tools (progress, workouts, exercises, balance, goals) auto-execute so
   the model grounds its advice in real data. **Write** tools come back in the
   response as `proposed_actions` — each an `{ action_id, type, summary, args,
   status }` — and nothing is written yet.
2. The app shows the proposals and lets the user accept/reject them.
3. `POST /chat/confirm { conversation_id, accepted_ids[], rejected_ids?[] }`
   executes the accepted actions through the **same** services the manual UI uses
   (so chat-logged records are identical), in a dependency-safe order, and
   **idempotently** — re-submitting the same `accepted_ids` never double-writes.

**Never fabricate IDs.** Write-tool args use human references — an exercise *name*,
a *date* or `today`, a workout *title* — resolved to real IDs only at confirm time
(fuzzy name match within a muscle; `today`/`YYYY-MM-DD` → that day's workout,
created if needed). Ambiguous references come back as `needs_clarification` and the
coach asks one short question instead of guessing.

**Deterministic-first (free-tier friendly).** PR detection, progression maths,
muscle-balance ratios, weekly-recap aggregation, and goal trajectory all run in
plain code — Gemini is called only for open-ended reasoning (NL parsing, planning)
and optional phrasing. Recap and briefing are cached per `(user, week/date)` in
`coach_cache`, and these are triggered on app-open (a `GET`), never a background
cron, so quota is only spent when a user is active.

### Coach config knobs

| Variable                     | Default | Description |
| ---------------------------- | ------- | ----------- |
| `COACH_MAX_TOOL_ITERATIONS`  | `5`     | Hard cap on read→call rounds per chat turn |
| `COACH_CONFIRM_USE_LLM`      | `false` | Phrase the confirmation sentence with Gemini (else templated) |
| `COACH_BRIEFING_USE_LLM`     | `false` | Phrase the pre-workout briefing with Gemini (else templated) |
| `COACH_RECAP_USE_LLM`        | `true`  | Write the weekly recap with Gemini (1 cached call/week) |

## Tests

Three layers, all runnable locally with no real database or Gemini key:

- **Pure logic** — PR detection, progression, balance, ID resolution, goal
  trajectory, write-tool validation, and the streak computation: pure functions
  over plain data.
- **Aggregation parity / data layer** — the progress aggregations and list
  endpoints run against an in-memory Mongo (`mongomock-motor`, configured
  `tz_aware=True` to match production), asserting the rewritten pipelines return
  the same results as before.
- **API level** — the critical flows (register/login, create-exercise →
  log-session → PR detection, confirm idempotency) driven through the real ASGI
  app with `httpx`.

```bash
pip install -r requirements-dev.txt   # runtime deps + pytest + tooling
pytest
```

CI (`.github/workflows/deploy.yml`) gates the build on a **lint + type-check** job
(ruff + mypy, configured in `pyproject.toml`) and the test suite, and only
builds/deploys the Docker image if both pass. Test-only dependencies live in
`requirements-dev.txt`, so they are **not** baked into the production image (which
installs `requirements.txt` only).

## Future work

### Refresh tokens & revocation

Auth is currently a single 7-day **access token** (a `SECRET_KEY`-signed JWT) with
no server-side revocation: a leaked token stays valid until it expires, and there
is no "log out everywhere". A planned design:

- **Short-lived access token (~15 min) + long-lived refresh token (~30 days).**
  The refresh token is an opaque random string; only its hash is stored, in a
  `refresh_tokens` collection keyed by `(user_id, token_hash)` with `expires_at`
  and a `jti`. A new `POST /auth/refresh` swaps a valid refresh token for a fresh
  access token.
- **Rotation on use.** Each refresh issues a new refresh token and invalidates the
  old one; presenting an already-rotated token signals theft and revokes that
  user's whole chain.
- **Revocation.** Logout deletes the stored refresh token; "sign out everywhere"
  deletes all of a user's. For immediate *access*-token revocation, add a per-user
  `token_version` claim checked on each request (bump it to invalidate every
  outstanding access token) or a short-TTL `jti` denylist.
- **Storage & cleanup.** A TTL index on `refresh_tokens.expires_at` auto-prunes
  expired rows; everything stays scoped to `user_id`.

This keeps stateless-access-token performance for normal requests while adding a
revocation path and bounding the blast radius of a leaked token.

## License

[MIT](LICENSE). The mobile app lives in
[IronLogEfitness/Efitness_frontend](https://github.com/IronLogEfitness/Efitness_frontend).
