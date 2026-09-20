# Epiphany

Ask questions about your spreadsheets in plain English. Epiphany queries your data, charts what matters, forecasts trends, and lets you save dashboards across sessions.

## Features

- **Upload** CSV / Excel (`.csv`, `.xlsx`, `.xls`), including multi-sheet workbooks
- **Ask** analytical questions — answers are grounded in SQL against your files
- **Charts** when they help (bar, line, area, scatter); dashboards capped at 4 views
- **Forecast** time series with clear confidence / method notes
- **Sessions** per user — switch workspaces without losing chat or canvas
- **Saved dashboards** shared across all of your sessions

## Quick start

### Docker (recommended)

```bash
# 1. API key for the backend
cp backend/.env.example backend/.env
# Edit backend/.env — set LLM_API_KEY

# 2. Build & run
docker compose up --build
```

- App: http://localhost:3000  
- API docs: http://localhost:8000/docs  

Data (SQLite, uploads, checkpoints) persists in the `epiphany-data` volume. Stop with `Ctrl+C` or `docker compose down`.

### Local (without Docker)

#### Prerequisites

- Conda env **`THEnv`** (backend)
- Node.js 18+
- An OpenAI-compatible API key (e.g. [OpenRouter](https://openrouter.ai) or [Groq](https://console.groq.com))

#### Backend

```bash
conda activate THEnv
cd backend
pip install -r requirements.txt
cp .env.example .env
# Set LLM_API_KEY (and optionally LLM_MODELS) in .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

#### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Open **http://localhost:3000**

## Configuration

Copy `backend/.env.example` → `backend/.env`. Models are not hardcoded:

| Variable | Purpose |
|---|---|
| `LLM_API_KEY` | Primary provider API key (OpenRouter) |
| `LLM_BASE_URL` | Primary OpenAI-compatible base URL (default: OpenRouter) |
| `LLM_MODELS` | Primary model IDs, tried in order on errors |
| `LLM_FALLBACK_API_KEY` | Optional Groq key when primary rate-limits |
| `LLM_FALLBACK_BASE_URL` | Fallback base URL (default: Groq) |
| `LLM_FALLBACK_MODELS` | Fallback models (e.g. `openai/gpt-oss-120b`) |
| `CORS_ORIGINS` | Allowed frontend origins |

Frontend: `NEXT_PUBLIC_API_URL` in `.env.local` (default `http://localhost:8000`).

## Try it

1. Create or open a **session**
2. Upload a CSV/Excel file
3. Ask e.g. *“What’s total revenue by region?”* or *“Build a dashboard”*
4. **Save dashboard** to keep charts across sessions

Sample CSVs live under `backend/data/sample_data/`.

## Architecture

| Layer | Role |
|---|---|
| **Frontend** | Next.js + Tailwind — chat, uploads, live canvas, sessions |
| **API** | FastAPI — upload, SSE chat, boards, session persistence |
| **Agent** | LangGraph + three tools: `query_data`, `forecast`, `render_chart` |
| **Data** | DuckDB per session; SQLite for users, sessions, boards, checkpoints |
| **LLM** | Any OpenAI-compatible endpoint (OpenRouter by default, Groq fallback) |

```
frontend/          Epiphany UI (+ Dockerfile)
backend/           FastAPI + agent (+ Dockerfile)
docker-compose.yml One-command stack
Docs/              Assignment brief + build plan
WRITEUP.md         Approach notes
```

## API (essentials)

| Method | Path | Notes |
|---|---|---|
| `POST` | `/users/{user_id}` | Ensure user |
| `GET` | `/users/{user_id}/sessions` | List sessions |
| `POST` | `/sessions` | Create session (`user_id`) |
| `POST` | `/sessions/{id}/upload` | Upload files |
| `POST` | `/sessions/{id}/chat` | Agent SSE stream |
| `GET` | `/users/{user_id}/boards` | Saved dashboards (user-scoped) |
| `POST` | `/sessions/{id}/boards` | Save dashboard |

Interactive docs: http://127.0.0.1:8000/docs
