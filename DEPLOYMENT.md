# Deployment Guide — Free-Tier Production

This guide deploys Veridian entirely on free-tier services. Every service used here has a free plan that requires no credit card.

| Service | Role | Free Tier |
|---------|------|-----------|
| Supabase | PostgreSQL 16 + pgvector | 500 MB DB, 2 projects |
| Upstash Redis | Rate-limiting + token revocation | 10,000 commands/day |
| Render | FastAPI backend | 750 hrs/month, 512 MB RAM |
| Vercel | React frontend | Unlimited static deploys |
| GitHub | Source + CI | Unlimited public repos |

> **Cold start warning:** Render free tier spins down after 15 minutes of inactivity. The first request after sleep takes 10-30 seconds. See the "Free-Tier Limits" section.

---

## Step 1 — Supabase (PostgreSQL + pgvector)

1. Go to [supabase.com](https://supabase.com) → **New project**
2. Choose a region close to your users
3. Set a strong database password (save it — you will need it)
4. Once the project is ready, go to **Project Settings → Database**
5. Copy the **Connection string** (URI format). It looks like:
   ```
   postgres://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
   ```
6. Change the driver prefix for asyncpg:
   ```
   postgresql+asyncpg://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
   ```
7. Enable pgvector:
   - Go to **SQL Editor** → **New query**
   - Run: `CREATE EXTENSION IF NOT EXISTS vector;`
   - Run: `CREATE EXTENSION IF NOT EXISTS pg_trgm;` (used by keyword search)
8. Run Alembic migrations from your local machine:
   ```bash
   # Set the Supabase URL as your ALEMBIC_DATABASE_URL (sync driver)
   # Use the Session mode URL (port 5432), not the Transaction mode URL (port 6543)
   export DATABASE_URL="postgresql+asyncpg://postgres.[ref]:[pw]@db.[ref].supabase.co:5432/postgres"
   cd backend
   alembic upgrade head
   ```

---

## Step 2 — Upstash Redis

1. Go to [upstash.com](https://upstash.com) → **Create Database**
2. Name: `veridian-redis`, Region: match your Render region
3. Copy the **Redis URL** (format: `rediss://default:[password]@[host]:[port]`)
4. Save this as `REDIS_URL` in your environment

---

## Step 3 — Render (Backend)

1. Go to [render.com](https://render.com) → **New → Web Service**
2. Connect your GitHub repo (`Aahana-0204/Veridian`)
3. Configure:
   - **Name:** `veridian-backend`
   - **Root directory:** `backend`
   - **Runtime:** Docker
   - **Dockerfile path:** `Dockerfile.prod`
   - **Instance type:** Free
4. Add the following environment variables (Settings → Environment):

```
SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_hex(32))">
DATABASE_URL=<Supabase asyncpg URL from Step 1>
REDIS_URL=<Upstash Redis URL from Step 2>
ENVIRONMENT=production
CORS_ORIGINS=https://your-app.vercel.app
LLM_PROVIDER=groq
LLM_MODEL=llama-3.1-8b-instant
GROQ_API_KEY=<from console.groq.com>
EMBEDDING_PROVIDER=sentence-transformers
EMBEDDING_DIMENSIONS=384
SENTENCE_TRANSFORMER_MODEL=all-MiniLM-L6-v2
UPLOAD_DIR=/tmp/veridian_uploads
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
```

> **Note on LLM for Render:** The Render free tier has 512 MB RAM — not enough for Ollama (local models require 2+ GB). Use `LLM_PROVIDER=groq` for cloud deployments. Ollama is the default for local Docker Compose only.

5. Click **Create Web Service**. First deploy takes 5-10 minutes (sentence-transformers model downloads on first document upload).

6. Note your backend URL: `https://veridian-backend.onrender.com`

---

## Step 4 — Vercel (Frontend)

1. Go to [vercel.com](https://vercel.com) → **New Project**
2. Import your GitHub repo (`Aahana-0204/Veridian`)
3. Configure:
   - **Framework preset:** Vite
   - **Root directory:** `frontend`
   - **Build command:** `npm run build`
   - **Output directory:** `dist`
4. Add environment variable:
   ```
   VITE_API_URL=https://veridian-backend.onrender.com
   ```
5. Click **Deploy**. Your app is live at `https://your-project.vercel.app`

6. Go back to Render → update `CORS_ORIGINS` to your Vercel URL, then redeploy.

---

## Pre-Launch Checklist

Before going live, confirm every variable is set in Render and Vercel:

### Render (Backend) — Required

- [ ] `SECRET_KEY` — random hex, min 32 chars
- [ ] `DATABASE_URL` — Supabase asyncpg URL
- [ ] `REDIS_URL` — Upstash Redis URL
- [ ] `ENVIRONMENT=production`
- [ ] `CORS_ORIGINS` — your Vercel frontend URL (no trailing slash)
- [ ] `LLM_PROVIDER=groq`
- [ ] `GROQ_API_KEY` — from console.groq.com (free)
- [ ] `EMBEDDING_PROVIDER=sentence-transformers`
- [ ] `EMBEDDING_DIMENSIONS=384`
- [ ] `UPLOAD_DIR=/tmp/veridian_uploads`

### Render (Backend) — Optional but recommended

- [ ] `LOG_LEVEL=INFO`
- [ ] `ACCESS_TOKEN_EXPIRE_MINUTES=15`
- [ ] `REFRESH_TOKEN_EXPIRE_DAYS=7`
- [ ] `MAX_UPLOAD_SIZE_MB=20` (keep low on free tier)
- [ ] `TOP_K=5`
- [ ] `HYBRID_SEARCH_ENABLED=true`

### Vercel (Frontend) — Required

- [ ] `VITE_API_URL` — your Render backend URL (e.g. `https://veridian-backend.onrender.com`)

---

## Rolling Back

### Backend rollback (Render)
1. Go to Render → **Deploys** tab
2. Click any previous deploy → **Rollback to this deploy**
3. Alembic migrations must be reversed first if the schema changed:
   ```bash
   alembic downgrade -1   # run locally against production DB
   ```

### Frontend rollback (Vercel)
1. Go to Vercel → **Deployments**
2. Click any previous deployment → **Promote to Production**

### Database rollback
Supabase has **Point-in-Time Recovery** on paid plans. On free tier:
- Take a manual pg_dump before each migration: `pg_dump [url] > backup.sql`
- Restore: `psql [url] < backup.sql`

---

## Monitoring (Free Tier)

### What to watch

| Signal | What it means | Where to check |
|--------|--------------|----------------|
| HTTP 5xx rate | Application errors | Render → Logs |
| `/health` response | DB + Redis connectivity | Set up UptimeRobot (free) |
| Retrieval latency > 2 s | Supabase pgvector slow | Check EXPLAIN ANALYZE on chunks table |
| Embedding failures | sentence-transformers model not loaded | Render logs on first upload |
| Groq 429 errors | Free-tier rate limit hit | Render logs; switch to llama-3.1-8b-instant |

### Free monitoring tools

- **UptimeRobot** (free) — ping `/health` every 5 minutes, email alert if down. Also prevents Render cold starts if you set the check interval to ≤14 min.
- **Render Logs** — real-time log streaming at `render.com → your service → Logs`
- **Sentry free tier** — add `sentry-sdk[fastapi]` to capture unhandled exceptions with full stack traces

### Alerting on Render logs
Render does not have built-in alerting on log patterns for free tier. Options:
1. Use UptimeRobot to monitor the `/health` endpoint
2. Forward logs to Logtail free tier (25 GB/month)

---

## Free-Tier Limits — Know Before Your Demo

These are not bugs. They are expected behaviors of the free tier infrastructure.

### Render backend cold start
- **Behavior:** After 15 minutes of inactivity, Render spins down the container. The first request takes 10-30 seconds (container restart + sentence-transformers model load).
- **Mitigation:** Use UptimeRobot to ping `/health` every 14 minutes. This keeps the service warm at the cost of ~2,000 pings/month (well within UptimeRobot free tier of 50 monitors × 5-min interval).
- **During demo:** Warm up the backend by opening `/health` ~2 minutes before the demo starts.

### Supabase free tier
- **Storage limit:** 500 MB total (database + files). With sentence-transformers (384 dims), each chunk uses ~1.5 KB for the vector. 500 MB supports ~300,000 chunks (~1,000 medium documents).
- **Connection limit:** 60 concurrent connections. The backend uses SQLAlchemy's connection pool (default: 5 connections). Safe for demo load.
- **Compute:** Shared CPU. Complex hybrid search queries may take 500 ms-2 s on the free tier vs 50-100 ms on paid.

### Upstash Redis
- **Command limit:** 10,000 commands/day on free tier. Each auth login uses ~3 commands (rate limit check + refresh token store). Each authenticated request uses ~1 command. 10,000 commands/day = ~3,300 logins/day — more than sufficient for demo use.
- **Data size:** 256 MB max. Refresh tokens are small (~200 bytes each); 256 MB supports ~1 M active sessions.

### Groq free tier (if used as LLM provider)
- **Rate limit:** 30 requests/minute, 6,000 requests/day per API key.
- **Mitigation:** For demos, this is effectively unlimited. If you hit limits, implement a short retry with exponential back-off (already built into the LLM call path via LangChain retry config).
- **Latency:** Groq LPU inference is typically 200-500 ms for RAG-length prompts — faster than Ollama on CPU.

### Vercel frontend
- **No cold starts** — static assets are cached globally at the CDN edge.
- **Build minutes:** 100 GB-hours/month on free tier. Each build takes ~30 seconds. Limit: ~200 builds/month — effectively unlimited for a single project.

---

## Local Production Test

Before deploying, test the production Docker build locally:

```bash
# Build and run production stack
docker compose -f docker-compose.prod.yml up --build -d

# Pull model (one-time)
docker compose -f docker-compose.prod.yml exec ollama ollama pull llama3.2:3b

# Run migrations
docker compose -f docker-compose.prod.yml run --rm migrate

# Test health
curl http://localhost:8000/health

# Open frontend
open http://localhost:80
```