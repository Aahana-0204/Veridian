# Veridian — Production-Grade RAG Platform

A full-stack Retrieval-Augmented Generation (RAG) application built with FastAPI, React, PostgreSQL + pgvector, and LangChain.

## Prerequisites

| Tool | Version |
|------|---------|
| Docker | 24+ |
| Docker Compose | v2.20+ |
| Node.js _(local dev only)_ | 20+ |
| Python _(local dev only)_ | 3.12+ |

## Quick Start

### 1. Clone and configure environment

```bash
git clone https://github.com/Aahana-0204/Veridian.git
cd Veridian
cp .env.example .env
# Edit .env — at minimum set a strong SECRET_KEY
```

### 2. Start all services

```bash
docker compose up --build
```

This starts four services:
| Service | URL | Description |
|---------|-----|-------------|
| **frontend** | http://localhost:5173 | React + Vite dev server |
| **backend** | http://localhost:8000 | FastAPI (hot reload) |
| **postgres** | localhost:5432 | PostgreSQL 16 + pgvector |
| **redis** | localhost:6379 | Redis 7 |

### 3. Verify the stack

Open **http://localhost:5173** — you should see the Veridian health dashboard showing:
- **API Status:** `ok` (green)
- **Database:** `connected` (green)
- **Version:** `v0.1.0`

You can also hit the API directly:
```bash
curl http://localhost:8000/health
# {"status":"ok","database":"connected","version":"0.1.0"}
```

And view the interactive API docs:
```bash
open http://localhost:8000/docs
```

## Project Structure

```
Veridian/
├── backend/          # FastAPI application
│   ├── app/
│   │   ├── core/     # Config, logging, database
│   │   ├── routers/  # API route handlers
│   │   └── schemas/  # Pydantic request/response models
│   └── tests/
├── frontend/         # React + TypeScript + Vite
│   └── src/
│       ├── api/      # API client functions
│       ├── components/
│       ├── hooks/
│       ├── pages/
│       └── store/    # Zustand stores
├── infra/            # Dockerfiles, nginx, DB init
├── migrations/       # Alembic migration scripts
├── docker-compose.yml
├── .env.example
└── alembic.ini
```

## Development

### Backend (without Docker)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Ensure postgres is running, then:
uvicorn app.main:app --reload
```

### Frontend (without Docker)

```bash
cd frontend
npm install
npm run dev
```

### Running Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Create a new migration
alembic revision --autogenerate -m "description"
```

### Linting

```bash
# Backend
cd backend && ruff check . && black --check .

# Frontend
cd frontend && npm run lint && npm run format:check
```

### Pre-commit hooks

```bash
pip install pre-commit
pre-commit install
```

## Tech Stack

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async), Alembic
- **Frontend:** React 18, TypeScript (strict), Vite, TailwindCSS, TanStack Query, Zustand
- **Database:** PostgreSQL 16 + pgvector
- **Cache / Rate-limit:** Redis 7
- **Orchestration:** LangChain _(Part 3+)_
- **Auth:** JWT + refresh tokens, argon2 _(Part 2)_
- **CI:** GitHub Actions
