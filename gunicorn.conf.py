"""
Gunicorn configuration for a 5 000-concurrent-user CTF platform.

Worker sizing rule: (2 × num_cores) + 1
─────────────────────────────────────────
  4-core  → 9 workers   (each running an asyncio event loop)
  8-core  → 17 workers
  16-core → 33 workers

With async workers (UvicornWorker) each process handles thousands of
concurrent connections through a single event loop — no threading overhead.

Start command
─────────────
  gunicorn -c gunicorn.conf.py main:app
"""
import multiprocessing

# ── Worker class ──────────────────────────────────────────────────────────────
worker_class = "uvicorn.workers.UvicornWorker"

# ── Worker count  ─────────────────────────────────────────────────────────────
workers = (2 * multiprocessing.cpu_count()) + 1

# ── Binding ───────────────────────────────────────────────────────────────────
bind = "0.0.0.0:8000"

# ── Timeouts ─────────────────────────────────────────────────────────────────
# Keep-alive for long-running async requests
timeout = 120
keepalive = 5
graceful_timeout = 30

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog = "-"          # stdout
errorlog = "-"           # stderr
loglevel = "warning"     # "info" in development; "warning" in production
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(D)sµs'

# ── Process management ────────────────────────────────────────────────────────
# Reload workers after serving this many requests — prevents memory leaks
max_requests = 2000
max_requests_jitter = 400   # randomised to avoid thundering herd

# Preload the app before forking workers (saves memory via copy-on-write)
preload_app = True

# ── Connection limits ─────────────────────────────────────────────────────────
# Each worker can queue this many pending connections in the OS backlog
backlog = 2048

# ── Worker connections (per UvicornWorker event loop) ────────────────────────
# Uvicorn itself manages the concurrency within each worker process.
# The effective concurrency = workers × (DB pool + Redis pool connections).
# With pool_size=20 + max_overflow=10 per process and 9 workers that is
# up to 270 Postgres connections — well within a typical Postgres limit of 500.
