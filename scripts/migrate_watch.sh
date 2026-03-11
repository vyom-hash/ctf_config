#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# migrate_watch.sh — watch app/models/ and, on each change:
#                      1. alembic revision --autogenerate -m "auto_<ts>_<model>"
#                      2. alembic upgrade head
#
# Usage
# ─────
#   # Docker mode (default) — postgres must be running via docker compose up db
#   ./scripts/migrate_watch.sh
#
#   # Local mode — alembic runs in the active virtualenv
#   #              DATABASE_URL must resolve to localhost (Docker port-bound)
#   ./scripts/migrate_watch.sh --local
#
#   # Explicit Docker mode
#   ./scripts/migrate_watch.sh --docker
#
# Requirements
# ────────────
#   Docker mode : docker compose up db  (db service healthy)
#                 inotify-tools optional (falls back to 2-second polling)
#   Local mode  : activated virtualenv + DATABASE_URL in env or .env file
#
# Install inotify-tools (recommended, event-driven instead of polling):
#   sudo apt install inotify-tools
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────
WATCH_DIR="app/models"       # watch SQLAlchemy model files for schema changes
DEBOUNCE_SECONDS=2           # wait after last save before triggering

# ── Parse args ────────────────────────────────────────────────────────────────
MODE="docker"
for arg in "$@"; do
  case "$arg" in
    --local)  MODE="local"  ;;
    --docker) MODE="docker" ;;
    *)
      echo "Unknown argument: $arg"
      echo "Usage: $0 [--docker|--local]"
      exit 1
      ;;
  esac
done

# ── Resolve repo root (script may be called from anywhere) ───────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# ── Logging helpers ───────────────────────────────────────────────────────────
_ts()   { date '+%H:%M:%S'; }
_info() { echo "[$(_ts)] [migrate-watch]  $*"; }
_ok()   { echo "[$(_ts)] [migrate-watch]  ✓ $*"; }
_err()  { echo "[$(_ts)] [migrate-watch]  ✗ $*" >&2; }
_sep()  { echo "─────────────────────────────────────────────────────────────"; }

# ── Load .env (local mode or when DATABASE_URL is unset) ─────────────────────
_load_env() {
  if [[ -z "${DATABASE_URL:-}" && -f .env ]]; then
    set -o allexport
    # shellcheck disable=SC1091
    source .env
    set +o allexport
  fi
}

# ── Build a human-readable revision message ───────────────────────────────────
# e.g. changed file "app/models/deployment.py" → "auto_143022_deployment"
_revision_message() {
  local changed_file="${1:-}"
  local ts
  ts=$(date '+%H%M%S')
  local base
  base=$(basename "${changed_file%.py}")
  echo "auto_${ts}_${base}"
}

# ── Run autogenerate + upgrade ────────────────────────────────────────────────
run_revision_and_migrate() {
  local changed_file="${1:-}"
  local msg
  msg=$(_revision_message "$changed_file")

  _sep
  [[ -n "$changed_file" ]] && _info "Schema change detected: $changed_file"
  _info "Step 1/2 — generating revision:  $msg  (mode=$MODE)"

  if [[ "$MODE" == "docker" ]]; then
    # Mount local app/ (read-only) and migrations/ (read-write) so the
    # container sees the latest model code and writes the revision file back
    # to the local filesystem.
    docker compose run --rm \
      -v "${REPO_ROOT}/app:/app/app:ro" \
      -v "${REPO_ROOT}/migrations:/app/migrations" \
      migrate \
      alembic revision --autogenerate -m "$msg"
  else
    _load_env
    alembic revision --autogenerate -m "$msg"
  fi

  local rev_exit=$?
  if [[ $rev_exit -ne 0 ]]; then
    _err "alembic revision failed (exit $rev_exit) — skipping upgrade."
    _sep
    return $rev_exit
  fi
  _ok "Revision file created."

  _info "Step 2/2 — applying:  alembic upgrade head"

  if [[ "$MODE" == "docker" ]]; then
    # Mount local migrations/ so the newly generated revision is visible.
    docker compose run --rm \
      -v "${REPO_ROOT}/migrations:/app/migrations" \
      migrate \
      alembic upgrade head
  else
    _load_env
    alembic upgrade head
  fi

  local up_exit=$?
  if [[ $up_exit -eq 0 ]]; then
    _ok "Migration applied successfully."
  else
    _err "alembic upgrade head failed (exit $up_exit)."
  fi
  _sep
  return $up_exit
}

# ── Run upgrade-only (no autogenerate) ───────────────────────────────────────
run_upgrade_only() {
  _sep
  _info "Startup check — applying any pending migrations  (mode=$MODE)"
  if [[ "$MODE" == "docker" ]]; then
    docker compose run --rm \
      -v "${REPO_ROOT}/migrations:/app/migrations" \
      migrate \
      alembic upgrade head
  else
    _load_env
    alembic upgrade head
  fi
  local exit_code=$?
  if [[ $exit_code -eq 0 ]]; then
    _ok "Database is up to date."
  else
    _err "Startup upgrade failed (exit $exit_code)."
  fi
  _sep
  return $exit_code
}

# ── Startup: apply any already-pending migrations ────────────────────────────
_info "Starting in $MODE mode."
_info "Watching: $REPO_ROOT/$WATCH_DIR"
_info "Press Ctrl-C to stop."
echo ""
run_upgrade_only || true

# ── Watch loop ────────────────────────────────────────────────────────────────
if command -v inotifywait &>/dev/null; then
  # ── inotify path (event-driven, no busy-loop) ────────────────────────────
  _info "Using inotifywait (event-driven)."
  while true; do
    changed=$(
      inotifywait -q -e close_write,moved_to,create \
        --format '%f' \
        --include '.*\.py$' \
        "$WATCH_DIR" 2>/dev/null
    )
    # Debounce: absorb multiple rapid saves before triggering
    sleep "$DEBOUNCE_SECONDS"
    run_revision_and_migrate "$WATCH_DIR/$changed" || true
  done

else
  # ── Polling fallback ──────────────────────────────────────────────────────
  _info "inotifywait not found — polling every 2 seconds."
  _info "For instant reactions:  sudo apt install inotify-tools"

  declare -A prev_mtimes=()
  while IFS= read -r -d '' f; do
    prev_mtimes["$f"]=$(stat -c '%Y' "$f")
  done < <(find "$WATCH_DIR" -name '*.py' -print0)

  _info "Watching ${#prev_mtimes[@]} file(s) in $WATCH_DIR — waiting for changes ..."

  while true; do
    sleep 2
    changed_file=""
    declare -A curr_mtimes=()

    while IFS= read -r -d '' f; do
      curr_mtimes["$f"]=$(stat -c '%Y' "$f")
      if [[ -z "${prev_mtimes[$f]+set}" ]] || \
         [[ "${curr_mtimes[$f]}" != "${prev_mtimes[$f]}" ]]; then
        changed_file="$f"
      fi
    done < <(find "$WATCH_DIR" -name '*.py' -print0)

    if [[ -n "$changed_file" ]]; then
      # Update snapshot before running (avoids re-trigger on slow systems)
      prev_mtimes=()
      for k in "${!curr_mtimes[@]}"; do
        prev_mtimes["$k"]="${curr_mtimes[$k]}"
      done
      sleep "$DEBOUNCE_SECONDS"
      run_revision_and_migrate "$changed_file" || true
    fi
  done
fi
