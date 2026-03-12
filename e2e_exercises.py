#!/usr/bin/env python3
"""
CTF Config Service — end-to-end challenges API demo.

Demonstrates the challenges-as-superset / recipe-as-subset pattern:

  1.  Create a recipe draft and publish it (condensed from e2e_recipe.py).
  2.  Create Challenge instances bound to the published recipe version (1:1 mapping).
  3.  GET /api/v1/recipes/{id}        → recipe JSON includes `exercises` array
                                        where each challenge embeds `recipe` subset.
  4.  Print the enriched JSON blob.

Usage
-----
    python3 e2e_exercises.py
    python3 e2e_exercises.py --base-url http://localhost:8000
    python3 e2e_exercises.py --output exercises_demo.json

The JWT secret is read from SECRET_KEY in .env automatically; override with --secret.

Requirements: Python 3.10+ stdlib only.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import random
import string
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any


# ─────────────────────────── .env reader ──────────────────────────────────────

def _load_secret_from_env(env_file: str = ".env") -> str:
    try:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                if key.strip() == "SECRET_KEY":
                    return val.strip()
    except FileNotFoundError:
        pass
    return "change-me"


# ─────────────────────────── JWT (stdlib) ─────────────────────────────────────

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_token(secret: str, user_id: str | None = None, ttl_hours: int = 8) -> tuple[str, str]:
    uid = user_id or str(uuid.uuid4())
    header  = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({"sub": uid, "exp": int(time.time()) + ttl_hours * 3600}).encode())
    sig_input = f"{header}.{payload}".encode()
    sig = _b64url(hmac.new(secret.encode(), sig_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}", uid


# ─────────────────────────── HTTP helper ──────────────────────────────────────

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

    def post(self, path: str, body: Any = None) -> Any:
        return self._request("POST", path, body)

    def put(self, path: str, body: Any) -> Any:
        return self._request("PUT", path, body)

    def get(self, path: str) -> Any:
        return self._request("GET", path)


# ─────────────────────────── Random test data ─────────────────────────────────

def _rand_suffix(n: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def random_recipe_name() -> str:
    adjectives = ["advanced", "stealth", "covert", "elite", "rogue", "shadow"]
    nouns = ["ops", "breach", "intrusion", "escalation", "pivoting", "exfil"]
    return f"{random.choice(adjectives)}-{random.choice(nouns)}-{_rand_suffix()}"


def _slug(prefix: str) -> str:
    return f"{prefix}-{_rand_suffix()}"


# ─────────────────────────── Pretty printer ───────────────────────────────────

def section(title: str) -> None:
    width = 72
    print(f"\n{'═' * width}")
    print(f"  {title}")
    print('═' * width)


def ok(label: str, value: Any = "") -> None:
    print(f"  ✓  {label}  {value}")


def show_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2))


# ══════════════════════════════════════════════════════════════════════════════
#  Phase 1 — Create and publish recipe (condensed)
# ══════════════════════════════════════════════════════════════════════════════

def _create_and_publish_recipe(api: APIClient) -> tuple[str, str, str, list[str]]:
    """
    Full draft → publish flow.
    Returns (recipe_id, recipe_version_id, recipe_name, unit_keys).
    """
    recipe_name = random_recipe_name()

    # Step 1 — Create draft
    section("PHASE 1 / STEP 1 — Create recipe draft")
    draft = api.post("/api/v1/recipes", {
        "name":        recipe_name,
        "description": f"Auto-generated CTF scenario: {recipe_name}",
        "category":    "CTF",
    })
    recipe_id = draft["recipe_id"]
    ok("Recipe created", f"id={recipe_id}")

    # Step 2 — Network profile
    section("PHASE 1 / STEP 2 — Network profile")
    api.put(f"/api/v1/recipes/{recipe_id}/network-profile", {
        "gw_offset":     1,
        "dns_resolvers": ["8.8.8.8", "1.1.1.1"],
    })
    ok("Network profile set")

    # Step 3 — Domains
    section("PHASE 1 / STEP 3 — Domains")
    for d in [
        {"name": "internal-net", "description": "Isolated target network",
         "enable_egress": False},
        {"name": "dmz", "description": "Public-facing segment",
         "enable_egress": True},
    ]:
        r = api.post(f"/api/v1/recipes/{recipe_id}/domains", d)
        ok("Domain added", f"name={r['name']}")

    # Step 4 — Workload units
    section("PHASE 1 / STEP 4 — Workload units")
    unit_keys = []
    for u in [
        {
            "name":               "web-server-01",
            "description":        "Web server target",
            "allocation_index":   1,
            "runtime_profile":    "debian-bullseye-slim",
            "resource_tier":      "medium",
            "assigned_domain":    "dmz",
            "unit_control_active": True,
            "automation_profile": {
                "bootstrap_automation":  "scripts/web/bootstrap.sh",
                "preflight_automation":  "scripts/web/init.sh",
                "heartbeat_automation":  "scripts/web/healthcheck.sh",
            },
        },
        {
            "name":               "db-server-01",
            "description":        "Database target",
            "allocation_index":   2,
            "runtime_profile":    "postgres-15-alpine",
            "resource_tier":      "large",
            "assigned_domain":    "internal-net",
            "unit_control_active": False,
        },
        {
            "name":               "attacker-kali",
            "description":        "Attacker machine",
            "allocation_index":   3,
            "runtime_profile":    "kali-rolling",
            "resource_tier":      "medium",
            "assigned_domain":    "dmz",
            "unit_control_active": True,
        },
    ]:
        r = api.post(f"/api/v1/recipes/{recipe_id}/units", u)
        unit_keys.append(r["name"])
        ok("Unit added", f"name={r['name']}")

    # Step 5 — Gateway
    section("PHASE 1 / STEP 5 — Gateway")
    gw = api.post(f"/api/v1/recipes/{recipe_id}/gateways", {
        "gateway_key": "edge-gw-01", "gateway_type": "vyos",
        "runtime_profile": "oe:gateway", "resource_tier": "md", "is_active": True,
        "secure_shell": True, "egress_ip": False,
        "ingress_policies": [
            {"wl_unit": "web-server-01", "int_port": 80, "proto": "tcp", "name": "http", "ext_port": 80},
            {"wl_unit": "attacker-kali", "int_port": 22, "proto": "tcp", "name": "ssh",  "ext_port": 22},
        ],
    })
    ok("Gateway added", f"key={gw['gateway_key']}")

    # Step 6 — Jumphost unit
    section("PHASE 1 / STEP 6 — Jumphost unit")
    jh = api.put(f"/api/v1/recipes/{recipe_id}/jumphost", {
        "enable": True,
        "allow_vnc": True,
        "resource_tier": "md",
        "assigned_domain": "internal",
        "runtime_profile": "oe:jumphost",
        "egress_ip": False,
        "allocation_index": 5,
    })
    ok("Jumphost unit set", f"runtime_profile={jh['runtime_profile']}")

    # Step 7 — Validate
    section("PHASE 1 / STEP 7 — Validate")
    val = api.post(f"/api/v1/recipes/{recipe_id}/validate")
    if not val["is_valid"]:
        for err in val["errors"]:
            print(f"  ✗  {err}", file=sys.stderr)
        sys.exit(1)
    ok("Validation passed")

    # Step 8 — Submit for approval
    section("PHASE 1 / STEP 8 — Submit for approval")
    submit = api.post(f"/api/v1/recipes/{recipe_id}/submit")
    ok("Approval status", submit["approval_status"])
    if submit["approval_status"] != "APPROVED":
        print(
            "\n  Draft is PENDING_APPROVAL — set AUTO_APPROVE_RECIPES=true in .env",
            file=sys.stderr,
        )
        sys.exit(0)

    # Step 9 — Publish
    section("PHASE 1 / STEP 9 — Publish")
    published = api.post(f"/api/v1/recipes/{recipe_id}/publish")
    recipe_version_id = published["recipe_version_id"]
    ok("Version number", published["version_number"])
    ok("Version ID", recipe_version_id)

    return recipe_id, recipe_version_id, recipe_name, unit_keys


# ══════════════════════════════════════════════════════════════════════════════
#  Phase 2 — Create exercise instances (superset)
# ══════════════════════════════════════════════════════════════════════════════

def _create_exercises(
    api: APIClient,
    recipe_version_id: str,
    experience_mode: str = "both",
    target_units: list[str] = None,
) -> list[dict]:
    """
    Create challenge instances bound to the recipe version.
    Returns list of created challenge dicts.
    """
    if target_units is None:
        target_units = []
    exercises_payload = [
        # Exercise 1: Guided Mode
        {
            "instance_slug":    _slug("sqli-login-bypass"),
            "recipe_version_id": recipe_version_id,
            "title":            "SQL Injection — Login Bypass",
            "domain_tags":      ["web", "sql-injection", "authentication"],
            "difficulty":       "intermediate",
            "reward_points":    300,
            "description":      (
                "Exploit a classic SQL injection vulnerability in the login form "
                "to bypass authentication and retrieve the hidden admin flag."
            ),
            "verification_automation": "tpl-web-sqli-v2",
            "scoring_type":     "decay",
            "type":             "guided",
            "progression_mode": "independent",
            "resource_scope":   "per_user",
            "sub_category":     "selfpaced",
            "validation_targets": [
                {
                    "label":          "admin-flag",
                    "flag_template":  "CTF{sql1_byp4ss_{uuid}}",
                    "custom_evaluator": None,
                    "target_units": ["web-server-01"],
                    "flag_store": {
                        "category":        "file",
                        "location":        "/var/www/html/.flag",
                        "file_permission": "0440",
                        "file_owner":      "www-data",
                        "file_group":      "www-data",
                        "mkdir":           False,
                        "type":            "rewrite",
                    },
                },
            ],
            "hints": [
                {
                    "hint":           "Look carefully at how the login query is constructed. Is user input sanitized?",
                    "points_impacted": 50,
                },
                {
                    "hint":           "Try adding a single quote after the username field and observe the error response.",
                    "points_impacted": 100,
                },
            ],
            "objectives": [
                {"goal": "Identified injection point",  "points_impacted": 75},
                {"goal": "Extracted admin credentials", "points_impacted": 150},
            ],
        },
        # Exercise 2: Jeopardy Mode (No guidance steps or checkpoints)
        {
            "instance_slug":    _slug("crypto-basic-xor"),
            "recipe_version_id": recipe_version_id,
            "title":            "Cryptography — Basic XOR",
            "domain_tags":      ["crypto", "xor"],
            "difficulty":       "beginner",
            "reward_points":    100,
            "description":      (
                "A classic Jeopardy-style challenge. You are given a ciphertext and a known plain text format. "
                "Can you reverse the XOR operation to retrieve the flag?"
            ),
            "verification_automation": None,
            "scoring_type":     "flat",
            "type":             "jeopardy",
            "progression_mode": "independent",
            "resource_scope":   "per_user",
            "sub_category":     "selfpaced",
            "validation_targets": [
                {
                    "label":          "xored-flag",
                    "flag_template":  "CTF{x0r_1s_l0v3_{uuid}}",
                    "custom_evaluator": None,
                    "target_units": target_units,
                    "flag_store": {
                        "category":        "file",
                        "location":        "/opt/challenge/flag.txt",
                        "file_permission": "0444",
                        "file_owner":      "root",
                        "file_group":      "root",
                        "mkdir":           True,
                        "type":            "add",
                    },
                },
            ],
        },
    ]

    if experience_mode != "both":
        exercises_payload = [ep for ep in exercises_payload if ep.get("type") == experience_mode]

    created = []
    for payload in exercises_payload:
        r = api.post("/api/v1/challenges", payload)
        created.append(r)
        ok("Challenge created", f"slug={payload['instance_slug']}  id={r['id']}")

    return created


# ══════════════════════════════════════════════════════════════════════════════
#  Output reshaping — match target deployment response format
# ══════════════════════════════════════════════════════════════════════════════

def _reshape_deployment_output(deployment: dict) -> dict:
    """Pass-through — deployment response is already in the new structured format."""
    return deployment


# ══════════════════════════════════════════════════════════════════════════════
#  Main flow
# ══════════════════════════════════════════════════════════════════════════════

def run(
    base_url: str,
    secret: str,
    output_file: str | None,
    existing_recipe_id: str | None = None,
    existing_recipe_version_id: str | None = None,
    experience_mode: str = "both",
) -> None:
    token, user_id = make_token(secret)
    api = APIClient(base_url, token)

    print(f"\n  User ID : {user_id}")
    print(f"  Base URL: {base_url}")

    # ── Phase 1: Create + publish recipe (or reuse existing) ─────────────────
    if existing_recipe_id and existing_recipe_version_id:
        section("PHASE 1 — Using existing published recipe")
        recipe_id = existing_recipe_id
        recipe_version_id = existing_recipe_version_id
        detail = api.get(f"/api/v1/recipes/{recipe_id}")
        recipe_name = detail.get("name", "<unknown>")
        
        # Extract target units if using existing recipe
        unit_keys = []
        for unit in detail.get("workload_units", []):
            unit_keys.append(unit.get("name"))
                 
        ok("Recipe id", recipe_id)
        ok("Recipe version id", recipe_version_id)
    else:
        recipe_id, recipe_version_id, recipe_name, unit_keys = _create_and_publish_recipe(api)

    # ── Phase 2: Create challenges ────────────────────────────────────────────
    section("PHASE 2 — Create challenges (superset)")
    exercises = _create_exercises(api, recipe_version_id, experience_mode, unit_keys)
    ok("Challenges created", len(exercises))

    # ── Phase 3: Create deployment ────────────────────────────────────────────
    section("PHASE 3 — Create deployment")
    create_payload: dict = {
        "recipe_version_id": recipe_version_id,
        "access": {
            "entry_method":          "gateway",
            "ssh_public_key_ref":    "secret://org/default-ssh-key",
            "floating_ip_enabled":   False,
            "remote_console_enabled": True,
        },
        "target_env": "d1-taget-cloud",
    }
    create_resp = api.post("/api/v1/deployments", create_payload)
    deployment_id = create_resp["dep_id"]
    ok("Deployment ID", deployment_id)
    ok("Target env",    create_resp.get("target_env", "—"))

    # ── Phase 4: GET full deployment ──────────────────────────────────────────
    section("PHASE 4 — Fetch deployment (recipe_specs + challenge_specs)")
    deployment = api.get(f"/api/v1/deployments/{deployment_id}")
    recipe_specs = deployment.get("recipe_specs") or {}
    challenge_specs = deployment.get("challenge_specs") or {}
    challenges = challenge_specs.get("challenges") or []
    ok("recipe_specs present",    bool(recipe_specs))
    ok("Challenges",              len(challenges))
    ok("Execution type",          challenge_specs.get("execution_type", "—"))
    for ch in challenges:
        print(f"  ┌─ Challenge : {ch.get('title')}")
        print(f"  │  id        : {ch.get('id')}")
        print(f"  │  level     : {ch.get('level')}")
        print(f"  └─ points    : {ch.get('points')}")

    # ── Final JSON output ────────────────────────────────────────────────────
    final_output = _reshape_deployment_output(deployment)

    section("FINAL — Enriched deployment JSON (recipe_spec + challenges)")
    show_json(final_output)

    if output_file:
        with open(output_file, "w") as f:
            json.dump(final_output, f, indent=2)
        print(f"\n  JSON written to: {output_file}")

    print(f"\n{'═' * 72}")
    print(f"  Recipe '{recipe_name}' — deployment demo complete!")
    print(f"  Recipe ID        : {recipe_id}")
    print(f"  Recipe Version ID: {recipe_version_id}")
    print(f"  Deployment dep_id: {deployment_id}")
    print(f"  Challenges created: {len(exercises)}")
    print(f"{'═' * 72}\n")


# ─────────────────────────────── Entry point ──────────────────────────────────

def main() -> None:
    default_secret = _load_secret_from_env()

    parser = argparse.ArgumentParser(
        description="E2E challenges demo — challenges as superset, recipe as subset"
    )
    parser.add_argument(
        "--base-url", default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--secret", default=default_secret,
        help="JWT secret key — read from .env SECRET_KEY by default",
    )
    parser.add_argument(
        "--output", default=None,
        help="Optional: write final JSON to this file path",
    )
    parser.add_argument(
        "--recipe-id",
        default=None,
        help=(
            "Optional: use an existing recipe id instead of creating a new one "
            "(for example, the Recipe ID printed by e2e_recipe.py)"
        ),
    )
    parser.add_argument(
        "--recipe-version-id",
        default=None,
        help=(
            "Optional: use an existing recipe version id instead of creating a new one "
            "(for example, the Recipe Version ID printed by e2e_recipe.py)"
        ),
    )
    parser.add_argument(
        "--experience-mode",
        choices=["jeopardy", "guided", "both"],
        default="both",
        help="Filter the type of exercises created: 'jeopardy', 'guided', or 'both'",
    )
    args = parser.parse_args()
    run(
        args.base_url,
        args.secret,
        args.output,
        args.recipe_id,
        args.recipe_version_id,
        args.experience_mode,
    )


if __name__ == "__main__":
    main()
