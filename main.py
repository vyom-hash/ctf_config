"""
Gunicorn / Uvicorn entrypoint.

Usage (development)
───────────────────
  uvicorn main:app --reload --port 8000

Usage (production — see gunicorn.conf.py)
──────────────────────────────────────────
  gunicorn -c gunicorn.conf.py main:app
"""
from app.main import app  # noqa: F401 — re-exported for Uvicorn/Gunicorn
