#!/usr/bin/env python3
"""
CTF Config Service — end-to-end deployment creation script.

Given an approved & published recipe draft ID, this script:
  1. Resolves the approved recipe_version_id (DB lookup).
  2. Creates a deployment via POST /api/v1/deployments.
  3. Fetches the full deployment record via GET /api/v1/deployments/{id}.
  4. Fetches the recipe data via GET /api/v1/recipes/{recipe_id}.
  5. Combines them and prints the enriched deployment JSON.

Usage
-----
    python3 e2e_deployment.py <draft_id>
    python3 e2e_deployment.py <draft_id> --base-url http://localhost:8000
    python3 e2e_deployment.py <draft_id> --name "Weekend CTF"
    python3 e2e_deployment.py <draft_id> --output deployment.json

The JWT secret is read from SECRET_KEY in .env automatically; override with --secret.

Requirements: Python 3.10+. SQLAlchemy (from requirements.txt) for DB lookup only.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Optional

# ── Repo root + .env loading ──────────────────────────────────────────────────
_REPO_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO_ROOT))

import os  # noqa: E402

_env_file = _REPO_ROOT / ".env"
if _env_file.exists():
    with _env_file.open() as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip())


# ─────────────────────────────── JWT (stdlib) ────────────────────────────────

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_token(secret: str, ttl_hours: int = 8) -> tuple[str, str]:
    uid = str(uuid.uuid4())
    header  = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({"sub": uid, "exp": int(time.time()) + ttl_hours * 3600}).encode())
    sig_input = f"{header}.{payload}".encode()
    sig = _b64url(hmac.new(secret.encode(), sig_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}", uid


# ─────────────────────────────── HTTP client ─────────────────────────────────

class APIClient:
    def __init__(self, base_url: str, token: str):
        self.base = base_url.rstrip("/")
        self.token = token

    def _request(self, method: str, path: str, body: Any = None) -> Any:
        url = f"{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type":  "application/json",
                "Accept":        "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body_text = e.read().decode(errors="replace")
            print(f"\n  [HTTP {e.code}] {method} {path}", file=sys.stderr)
            print(f"  {body_text}", file=sys.stderr)
            sys.exit(1)

    def post(self, path: str, body: Any) -> Any:
        return self._request("POST", path, body)

    def get(self, path: str) -> Any:
        return self._request("GET", path)


# ─────────────────────────────── Pretty printer ───────────────────────────────

def section(title: str) -> None:
    width = 72
    print(f"\n{'═' * width}")
    print(f"  {title}")
    print("═" * width)


def ok(label: str, value: Any = "") -> None:
    print(f"  ✓  {label}  {value}")


def show_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str))


# ─────────────────────────────── DB lookup ───────────────────────────────────

async def _resolve_recipe_version_id(draft_id: uuid.UUID) -> uuid.UUID:
    """Return the latest approved recipe_version_id for the given draft."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.recipe import RecipeVersion
    from app.repositories.recipe_repository import RecipeRepository

    repo = RecipeRepository()
    async with AsyncSessionLocal() as session:
        version = await repo.get_latest_approved_version(session, draft_id)
        if version is not None:
            return version.id

        any_result = await session.execute(
            select(RecipeVersion).where(RecipeVersion.recipe_id == draft_id).limit(1)
        )
        any_v = any_result.scalar_one_or_none()
        if any_v is None:
            raise SystemExit(
                f"\n  [ERROR] No recipe version found for draft_id={draft_id}\n"
                "          Ensure the draft exists and has been published."
            )
        raise SystemExit(
            f"\n  [ERROR] No approved, published version for draft_id={draft_id}\n"
            f"          Latest: is_published={any_v.is_published}, "
            f"approval_status={any_v.approval_status}\n"
            "          Submit for approval and publish first."
        )


# ─────────────────────────────── Main flow ───────────────────────────────────

def run(
    draft_id: uuid.UUID,
    base_url: str,
    secret: str,
    name: Optional[str],
    output: Optional[str],
    target_env: Optional[str],
) -> None:
    token, user_id = make_token(secret)
    api = APIClient(base_url, token)

    print(f"\n  User ID : {user_id}")
    print(f"  Base URL: {base_url}")
    print(f"  Draft ID: {draft_id}")

    # ── Step 1 — Resolve recipe version ──────────────────────────────────────
    section("STEP 1 — Resolve recipe version")

    recipe_version_id = asyncio.run(_resolve_recipe_version_id(draft_id))
    ok("Recipe version ID", recipe_version_id)

    # ── Step 2 — Create deployment ────────────────────────────────────────────
    section("STEP 2 — Create deployment")

    create_payload: dict = {
        "recipe_version_id": str(recipe_version_id),
        "access": {
            "entry_method": "gateway",
            "ssh_public_key_ref": "secret://org/default-ssh-key",
            "floating_ip_enabled": False,
            "remote_console_enabled": True,
        },
    }
    if name:
        create_payload["name"] = name
    if target_env is not None:
        create_payload["target_env"] = target_env

    create_resp = api.post("/api/v1/deployments", create_payload)
    deployment_id = create_resp["deployment_id"]
    ok("Deployment ID", deployment_id)
    ok("Message",       create_resp.get("message", ""))
    ok("Status",        create_resp["status"])
    ok("Expires at",    create_resp["expires_at"])
    ok("Team size",     create_resp["team_size"])

    # ── Step 3 — Fetch full deployment record ─────────────────────────────────
    section("STEP 3 — Fetch full deployment")

    deployment = api.get(f"/api/v1/deployments/{deployment_id}")
    ok("Created at",         deployment["created_at"])
    ok("Updated at",         deployment["updated_at"])
    ok("Member IDs",         deployment.get("member_ids", []))
    ok("Target env",         deployment.get("target_env", "—"))
    ok("Experience type",   deployment.get("experience_type", "—"))
    ok("Exercise instances", len(deployment.get("exercise_instances", [])))

    # ── Step 4 — Fetch recipe data ────────────────────────────────────────────
    section("STEP 4 — Fetch recipe data")

    recipe = api.get(f"/api/v1/recipes/{draft_id}")
    ok("Recipe name",       recipe.get("name", "—"))
    ok("Approval status",   recipe.get("approval_status", "—"))
    ok("Domains",           len(recipe.get("domains", [])))
    ok("Workload units",    len(recipe.get("workload_units", [])))
    ok("Enable jumphost ?", recipe.get("enable_jumphost", True))

    # Also inspect the immutable recipe snapshot attached to the deployment.
    recipe_snapshot = deployment.get("recipe") or {}
    ok("Snapshot has jumphost_unit", bool(recipe_snapshot.get("jumphost_unit")))

    # ── Step 5 — Combine and output ───────────────────────────────────────────
    section("STEP 5 — Enriched deployment JSON")

    enriched = {
        k: v for k, v in deployment.items()
        if k not in ("recipe_version_id", "recipe_draft_id")
    }

    show_json(enriched)

    if output:
        with open(output, "w") as f:
            json.dump(enriched, f, indent=2, default=str)
        print(f"\n  Written to {output}")

    width = 72
    print(f"\n{'═' * width}")
    print("  Deployment created successfully!")
    print(f"  Draft ID      : {draft_id}")
    print(f"  Deployment ID : {deployment_id}")
    print(f"  Status        : {deployment['status']}")
    print(f"  Expires at    : {deployment['expires_at']}")
    print(f"{'═' * width}\n")


# ─────────────────────────────── Entry point ─────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="E2E deployment creation — creates a deployment and returns enriched JSON.",
    )
    parser.add_argument(
        "draft_id",
        type=str,
        help="UUID of the approved & published recipe draft",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--secret",
        default=os.environ.get("SECRET_KEY", "change-me"),
        help="JWT signing secret — reads SECRET_KEY from .env by default",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Optional deployment name (max 255 chars)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Also write enriched JSON to this file",
    )
    parser.add_argument(
        "--target-env",
        default=None,
        metavar="NAME",
        help="Target cloud name (e.g. openstack-dev, aws-prod); included in deployment JSON",
    )

    args = parser.parse_args()

    try:
        draft_id = uuid.UUID(args.draft_id)
    except ValueError:
        print(f"Invalid draft_id: {args.draft_id}", file=sys.stderr)
        sys.exit(1)

    run(draft_id, args.base_url, args.secret, args.name, args.output, args.target_env)


if __name__ == "__main__":
    main()
