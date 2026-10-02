import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

DEFAULT_DB_PATH = BACKEND_DIR / "data" / "app.db"
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")
ATTACHMENTS_DIR = Path(os.environ.get("ATTACHMENTS_DIR", BACKEND_DIR / "data" / "attachments"))

SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
if len(SESSION_SECRET) < 16:
    raise RuntimeError(
        "SESSION_SECRET is missing or too short. Copy backend/.env.example to backend/.env and set it."
    )

ALLOWED_ORIGINS = frozenset(
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173"
    ).split(",")
    if origin.strip()
)
