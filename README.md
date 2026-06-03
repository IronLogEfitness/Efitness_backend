# IronLog API

Backend for the IronLog fitness tracker — FastAPI + MongoDB (Motor), with a
Gemini-powered AI coach.

## Tech stack

- **FastAPI** — web framework
- **MongoDB** + **Motor** — async database access
- **python-jose** + **passlib** — JWT auth & password hashing
- **google-genai** (Gemini 2.5 Flash) — AI coaching chat
- **pydantic-settings** — typed configuration

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
├── sessions/            # CRUD /sessions
├── progress/            # stats & charts          (read-only aggregation)
└── chat/                # AI coach (Gemini)       (stateless)
```

Per feature:

| File              | Responsibility                                              |
| ----------------- | ----------------------------------------------------------- |
| `router.py`       | HTTP layer only: paths, status codes, `response_model`.     |
| `service.py`      | Business logic and database access. No FastAPI imports.     |
| `schemas.py`      | Pydantic request/response models (the API contract).        |
| `models.py`       | Shape of the stored MongoDB document (where one exists).    |

`muscles`, `progress`, and `chat` have no `models.py` — they derive everything
from the `exercises` / `sessions` collections or are stateless.

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
| `MONGO_URI`                   | yes       | `mongodb://localhost:27017` | MongoDB connection string |
| `DB_NAME`                     | yes       | `ironlog`                   | Database name |
| `SECRET_KEY`                  | yes       | insecure placeholder        | JWT signing secret — use a long random value, not reused from anywhere else |
| `ALGORITHM`                   | no        | `HS256`                     | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no        | `10080` (7 days)            | Access-token lifetime |
| `GEMINI_API_KEY`              | for chat  | empty                       | Google AI Studio key for the AI coach |
| `CORS_ORIGINS`                | no        | `["*"]`                     | JSON array of allowed origins |

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
| POST   | `/chat`                    | AI coach — answers using your recent training data |

## AI coach (Gemini)

`POST /chat` summarises the authenticated user's last 30 days of sessions and
sends them to **Gemini 2.5 Flash** as context, so replies reference the user's
real numbers. The summary is always scoped to the logged-in user (derived from
the JWT, never the request body) — the model never sees another user's data.

To enable it:

1. Create a free API key at <https://aistudio.google.com/apikey>
2. Put it in `.env` as `GEMINI_API_KEY=...`
3. Restart the server

Without a key, `/chat` returns `500 {"detail": "GEMINI_API_KEY not configured"}`;
every other endpoint works without it.
