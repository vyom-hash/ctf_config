# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — dependency builder
#   Compiles asyncpg (C extension) and installs all wheels into /install.
#   Keeping this separate means the final image never needs gcc/build-tools.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libc6-dev \
        python3-dev \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --prefix=/install -r requirements.txt


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — runtime image
#   Only the pre-built wheels + app source.  No compiler tools.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="CTF Config Service"
LABEL org.opencontainers.image.description="Production-ready CTF training platform API"

# Runtime library for asyncpg / psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ── Non-root user ─────────────────────────────────────────────────────────────
RUN groupadd -r ctfapp && useradd -r -g ctfapp -u 1000 ctfapp

WORKDIR /app

# Copy pre-installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY --chown=ctfapp:ctfapp . .

USER ctfapp

EXPOSE 8000

# ── Default command: Gunicorn + UvicornWorker ─────────────────────────────────
# Workers = (2 × cpu_count) + 1, configured in gunicorn.conf.py
CMD ["gunicorn", "-c", "gunicorn.conf.py", "main:app"]
