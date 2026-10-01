# Venkat_Subramanian_Demo — local internal-tools prototype

KYC review queue (React + Vite + TypeScript frontend, FastAPI + Pydantic + synchronous SQLAlchemy + SQLite backend).
Local demo only, fictional data. Full setup and run instructions are being written; see below for the KYC checkpoint.

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env   # then set SESSION_SECRET
.venv/bin/python -m app.seed --reset
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
.venv/bin/python -m pytest -q

cd frontend && npm ci && npm run dev   # http://127.0.0.1:5173
```
