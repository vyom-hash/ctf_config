#!/usr/bin/env python3
"""
Generate or fetch deployment JSON, with the recipe snapshot embedded.

Three modes
───────────
  Mode 1 — generate request payload (looks up recipe_version_id from DB):
    python -m scripts.generate_deployment_json <draft_id>

  Mode 2 — generate from-draft request payload (all fields explicit):
    python -m scripts.generate_deployment_json <draft_id> \\
        --recipe-version 1 \\
        --experience-type hands-on-lab \\
        --duration-hours 24 \\
        --access-mode gateway
    (provider_profile is returned by the API as a constant; not sent in request.)

  Mode 3 — create a deployment then GET the full enriched response:
    python -m scripts.generate_deployment_json <draft_id> --deploy --token <jwt>

  Mode 4 — GET an existing deployment and return enriched JSON:
    python -m scripts.generate_deployment_json --get-deployment <deployment_id> --token <jwt>

Usage
─────
    # Generate request payload only
    python -m scripts.generate_deployment_json a1b2c3d4-...

    # Create deployment and print full enriched response
    python -m scripts.generate_deployment_json a1b2c3d4-... --deploy --token eyJ...

    # Fetch and enrich an existing deployment by ID
    python -m scripts.generate_deployment_json --get-deployment <dep_id> --token eyJ...

    # Write output to file
    python -m scripts.generate_deployment_json --get-deployment <dep_id> \\
        --token eyJ... --output response.json

Requirements
────────────
    Same as the app: see requirements.txt. Run from repo root so app is importable.
    Generate a token:  python gen_token.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import uuid
from typing import Optional

# ── Repo root resolution ──────────────────────────────────────────────────────
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
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


# ─────────────────────────────── CLI args ────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate or fetch deployment JSON with the recipe snapshot embedded.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "draft_id",
        type=str,
        nargs="?",
        default=None,
        help="UUID of the approved recipe draft (required except with --get-deployment)",
    )
    p.add_argument(
        "--name",
        type=str,
        default=None,
        help="Optional deployment name (max 255 chars)",
    )
    p.add_argument(
        "--member-ids",
        type=str,
        default=None,
        help="Comma-separated member UUIDs (e.g. uuid1,uuid2)",
    )
    p.add_argument(
        "--include-access-defaults",
        action="store_true",
        help="Include default access config",
    )

    # ── Mode 2: from-draft fields ─────────────────────────────────────────────
    draft_group = p.add_argument_group(
        "from-draft mode (Mode 2)",
        "Supply these to generate a complete from-draft request payload.\n"
        "recipe-version plus experience-type, duration-hours, access-mode are required (or omit all for Mode 1).",
    )
    draft_group.add_argument(
        "--recipe-version",
        type=int,
        default=None,
        metavar="N",
        help="Recipe version number (e.g. 1). Activates from-draft mode.",
    )
    draft_group.add_argument(
        "--experience-type",
        type=str,
        default=None,
        metavar="TYPE",
        help='Experience type (e.g. "hands-on-lab"). Required in from-draft mode.',
    )
    draft_group.add_argument(
        "--duration-hours",
        type=int,
        default=None,
        metavar="HOURS",
        help="Deployment duration in hours, 1-720. Required in from-draft mode.",
    )
    draft_group.add_argument(
        "--access-mode",
        type=str,
        default=None,
        metavar="MODE",
        help='Access mode (e.g. "gateway", "ssh", "vnc"). Required in from-draft mode.',
    )

    # ── Deploy / fetch options ─────────────────────────────────────────────────
    api_group = p.add_argument_group("API options")
    api_group.add_argument(
        "--deploy",
        action="store_true",
        help="POST the payload to the API and print the enriched deployment JSON",
    )
    api_group.add_argument(
        "--get-deployment",
        type=str,
        default=None,
        metavar="UUID",
        help="GET an existing deployment by ID and return the enriched JSON (skips creation)",
    )
    api_group.add_argument(
        "--token",
        type=str,
        default=None,
        metavar="JWT",
        help="Bearer token (required with --deploy or --get-deployment). "
             "Generate one with: python gen_token.py",
    )
    api_group.add_argument(
        "--api-url",
        type=str,
        default="http://localhost:8000",
        metavar="URL",
        help="Base URL of the running API (default: http://localhost:8000)",
    )

    # ── Output ────────────────────────────────────────────────────────────────
    p.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Write output JSON to file instead of stdout",
    )
    p.add_argument(
        "--pretty",
        action="store_true",
        default=True,
        help="Pretty-print JSON (default: True)",
    )
    p.add_argument(
        "--no-pretty",
        action="store_false",
        dest="pretty",
        help="Compact JSON output",
    )
    return p.parse_args()


# ─────────────────────────────── Access defaults ──────────────────────────────

def _default_access_payload() -> dict:
    """Default jumphost/access config matching the API schema."""
    return {
        "access": {
            "entry_method": "gateway",
            "ssh_public_key_ref": "secret://org/default-ssh-key",
            "floating_ip_enabled": False,
            "remote_console_enabled": True,
        },
    }


# ─────────────────────────────── DB lookup ───────────────────────────────────

_FROM_DRAFT_FIELDS = (
    "recipe_version",
    "experience_type",
    "duration_hours",
    "access_mode",
)


async def _build_payload(
    draft_id: uuid.UUID,
    name: Optional[str],
    member_ids: list[uuid.UUID],
    include_access: bool,
    # from-draft mode (Mode 2)
    recipe_version: Optional[int] = None,
    experience_type: Optional[str] = None,
    duration_hours: Optional[int] = None,
    access_mode: Optional[str] = None,
) -> dict:
    """
    Build the POST /api/v1/deployments request payload.

    Mode 1 (by version_id): recipe_version is None.
      Looks up the latest approved recipe_version_id from DB.

    Mode 2 (from-draft): recipe_version is provided.
      Builds a complete from-draft payload with all required fields.
      No DB lookup needed for the version ID.
    """
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.recipe import RecipeVersion
    from app.repositories.recipe_repository import RecipeRepository

    if recipe_version is not None:
        # ── Mode 2: from-draft ────────────────────────────────────────────────
        payload: dict = {
            "recipe_draft_id": str(draft_id),
            "recipe_version": recipe_version,
            "experience_type": experience_type,
            "duration_hours": duration_hours,
            "access_mode": access_mode,
        }
    else:
        # ── Mode 1: by recipe_version_id (DB lookup) ──────────────────────────
        repo = RecipeRepository()
        async with AsyncSessionLocal() as session:
            version = await repo.get_latest_approved_version(session, draft_id)
            if version is None:
                any_result = await session.execute(
                    select(RecipeVersion).where(RecipeVersion.draft_id == draft_id).limit(1)
                )
                any_v = any_result.scalar_one_or_none()
                if any_v is None:
                    raise SystemExit(
                        f"No recipe version found for draft_id={draft_id}. "
                        "Ensure the draft exists and has been published."
                    )
                raise SystemExit(
                    f"No approved, published recipe version for draft_id={draft_id}. "
                    f"Latest version: is_published={any_v.is_published}, "
                    f"approval_status={any_v.approval_status}. "
                    "Submit for approval and publish first."
                )
        payload = {"recipe_version_id": str(version.id)}

    if name is not None:
        payload["name"] = name
    if member_ids:
        payload["member_ids"] = [str(m) for m in member_ids]
    if include_access:
        payload.update(_default_access_payload())
    return payload


# ─────────────────────────────── HTTP helpers ────────────────────────────────

def _api_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _check_response(response) -> None:
    """Print status line and exit on non-2xx."""
    print(f"← {response.status_code} {response.reason_phrase}", file=sys.stderr)
    if not response.is_success:
        try:
            error_body = json.dumps(response.json(), indent=2)
        except Exception:
            error_body = response.text
        print(f"Error response:\n{error_body}", file=sys.stderr)
        sys.exit(response.status_code)


def _post_deployment(client, api_url: str, token: str, payload: dict) -> dict:
    """POST /api/v1/deployments — returns the 201 create response."""
    url = f"{api_url.rstrip('/')}/api/v1/deployments"
    print(f"→ POST {url}", file=sys.stderr)
    response = client.post(url, json=payload, headers=_api_headers(token))
    _check_response(response)
    return response.json()


def _get_deployment(client, api_url: str, token: str, deployment_id: str) -> dict:
    """GET /api/v1/deployments/{id} — returns the complete DeploymentResponse."""
    url = f"{api_url.rstrip('/')}/api/v1/deployments/{deployment_id}"
    print(f"→ GET  {url}", file=sys.stderr)
    response = client.get(url, headers=_api_headers(token))
    _check_response(response)
    return response.json()


def _create_and_fetch(api_url: str, token: str, payload: dict) -> dict:
    """
    POST to create the deployment, then GET the full record.

    The POST response (DeploymentCreateResponse) omits name, member_ids, and
    updated_at.  The follow-up GET returns the complete DeploymentResponse with
    every field populated, including recipe_draft_id, provider_profile (constant),
    experience_type, duration_hours, and access_mode.
    """
    import httpx

    with httpx.Client(timeout=30) as client:
        create_resp = _post_deployment(client, api_url, token, payload)
        deployment_id = create_resp["deployment_id"]
        print(f"   deployment_id: {deployment_id}", file=sys.stderr)
        full_resp = _get_deployment(client, api_url, token, deployment_id)

    return full_resp


def _fetch_and_return(api_url: str, token: str, deployment_id: str) -> dict:
    """GET an existing deployment by ID and return its full DeploymentResponse."""
    import httpx

    with httpx.Client(timeout=30) as client:
        return _get_deployment(client, api_url, token, deployment_id)


# ─────────────────────────────── Recipe enrichment ───────────────────────────

async def _fetch_recipe_spec(deployment_id: uuid.UUID) -> Optional[dict]:
    """Fetch the recipe_spec JSONB snapshot stored on the deployment row."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.deployment import Deployment

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Deployment.recipe_spec).where(Deployment.id == deployment_id)
        )
        return result.scalar_one_or_none()


def _enrich_with_recipe(deployment_json: dict) -> dict:
    """
    Replace recipe_version_id / recipe_draft_id with the full recipe snapshot.

    Fetches the recipe_spec stored on the deployment row (the immutable snapshot
    taken at creation time) and embeds it under a top-level "recipe" key.
    The raw ID fields are removed so callers get data, not opaque UUIDs.
    """
    deployment_id = uuid.UUID(deployment_json["deployment_id"])
    recipe_spec = asyncio.run(_fetch_recipe_spec(deployment_id))
    enriched = {**deployment_json}
    enriched.pop("recipe_version_id", None)
    enriched.pop("recipe_draft_id", None)
    enriched["recipe"] = recipe_spec  # None if snapshot was not captured
    return enriched


# ─────────────────────────────── Output helper ───────────────────────────────

def _dump(data: dict, pretty: bool, output_path: Optional[str]) -> None:
    indent = 2 if pretty else None
    separators = (",", ": ") if pretty else (",", ":")
    out = json.dumps(data, indent=indent, separators=separators, default=str)

    if output_path:
        with open(output_path, "w") as f:
            f.write(out)
        print(f"Wrote JSON to {output_path}", file=sys.stderr)
    else:
        print(out)


# ─────────────────────────────── Arg validation helpers ──────────────────────

def _require_uuid(value: str, label: str) -> uuid.UUID:
    """Parse a UUID string, printing an error and exiting on failure."""
    try:
        return uuid.UUID(value)
    except ValueError:
        print(f"Invalid {label}: {value}", file=sys.stderr)
        sys.exit(1)


def _parse_member_ids(raw: Optional[str]) -> list[uuid.UUID]:
    """Parse comma-separated UUID strings into a list."""
    if not raw:
        return []
    result: list[uuid.UUID] = []
    for s in raw.split(","):
        s = s.strip()
        if s:
            result.append(_require_uuid(s, "member UUID"))
    return result


def _validate_from_draft_args(args: argparse.Namespace) -> None:
    """Exit with an error if any required from-draft field is missing."""
    required = [
        ("--experience-type", args.experience_type),
        ("--duration-hours", args.duration_hours),
        ("--access-mode", args.access_mode),
    ]
    missing = [flag for flag, val in required if val is None]
    if missing:
        print(
            f"Error: from-draft mode requires all three fields. Missing: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)


# ─────────────────────────────── Entry point ─────────────────────────────────

def main() -> None:
    args = _parse_args()

    # ── Mode 4: GET existing deployment ──────────────────────────────────────
    if args.get_deployment:
        if not args.token:
            print("Error: --token is required with --get-deployment.", file=sys.stderr)
            print("       Generate one with:  python gen_token.py", file=sys.stderr)
            sys.exit(1)
        deployment_id = _require_uuid(args.get_deployment, "--get-deployment")
        print("Mode: get existing deployment", file=sys.stderr)
        raw = _fetch_and_return(args.api_url, args.token, str(deployment_id))
        enriched = _enrich_with_recipe(raw)
        _dump(enriched, args.pretty, args.output)
        return

    # ── Modes 1 / 2 / 3: need draft_id ───────────────────────────────────────
    if not args.draft_id:
        print("Error: draft_id is required (or use --get-deployment <uuid>).", file=sys.stderr)
        sys.exit(1)

    if args.deploy and not args.token:
        print("Error: --token is required when using --deploy.", file=sys.stderr)
        print("       Generate one with:  python gen_token.py", file=sys.stderr)
        sys.exit(1)

    from_draft_mode = args.recipe_version is not None
    if from_draft_mode:
        _validate_from_draft_args(args)

    draft_id = _require_uuid(args.draft_id, "draft_id")
    member_ids = _parse_member_ids(args.member_ids)

    payload = asyncio.run(
        _build_payload(
            draft_id=draft_id,
            name=args.name,
            member_ids=member_ids,
            include_access=args.include_access_defaults,
            recipe_version=args.recipe_version,
            experience_type=args.experience_type,
            duration_hours=args.duration_hours,
            access_mode=args.access_mode,
        )
    )

    mode_label = "from-draft (Mode 2)" if from_draft_mode else "by recipe_version_id (Mode 1)"
    print(f"Mode: {mode_label}", file=sys.stderr)

    if args.deploy:
        print("Request payload:", file=sys.stderr)
        print(json.dumps(payload, indent=2), file=sys.stderr)
        print("", file=sys.stderr)
        response_data = _create_and_fetch(args.api_url, args.token, payload)
        response_data = _enrich_with_recipe(response_data)
        _dump(response_data, args.pretty, args.output)
    else:
        _dump(payload, args.pretty, args.output)


if __name__ == "__main__":
    main()
