#!/usr/bin/env python3
"""
CTF Config Service — end-to-end recipe creation script.

Walks through all 9 steps of the draft → publish flow using randomly
generated test data, then fetches and prints the final approved recipe.

Usage
-----
    python3 e2e_recipe.py
    python3 e2e_recipe.py --base-url http://localhost:8000
    python3 e2e_recipe.py --base-url http://localhost:8000 --secret <SECRET_KEY>

The script reads SECRET_KEY from .env automatically when --secret is omitted.

Requirements: Python 3.10+ stdlib only (no extra packages needed).
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
    """Read SECRET_KEY from .env file in the current working directory."""
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

def _rand_suffix(n: int = 4) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def random_recipe_name() -> str:
    adjectives = ["advanced", "stealth", "covert", "elite", "rogue", "shadow"]
    nouns = ["ops", "breach", "intrusion", "escalation", "pivoting", "exfil"]
    return f"{random.choice(adjectives)}-{random.choice(nouns)}-{_rand_suffix()}"


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
#  Main flow
# ══════════════════════════════════════════════════════════════════════════════

def run(base_url: str, secret: str) -> None:
    token, user_id = make_token(secret)
    api = APIClient(base_url, token)

    print(f"\n  User ID : {user_id}")
    print(f"  Base URL: {base_url}")

    # ── Step 1 — Create draft ─────────────────────────────────────────────────
    section("STEP 1 — Create recipe draft")

    recipe_name = random_recipe_name()
    draft_payload = {
        "name":               recipe_name,
        "description":        f"Auto-generated CTF scenario: {recipe_name}",
        "category":           "CTF",
    }
    draft = api.post("/api/v1/recipes", draft_payload)
    recipe_id = draft["recipe_id"]
    ok("Recipe created", f"id={recipe_id}")
    ok("Approval status", draft["approval_status"])

    # ── Step 2 — Network profile ──────────────────────────────────────────────
    section("STEP 2 — Configure network profile")

    net_payload = {
        "gw_offset":     1,
        "dns_resolvers": ["8.8.8.8", "1.1.1.1"],
    }
    net = api.put(f"/api/v1/recipes/{recipe_id}/network-profile", net_payload)
    ok("GW offset", net["gw_offset"])
    ok("DNS resolvers", net["dns"])

    # ── Step 3 — Domains ──────────────────────────────────────────────────────
    section("STEP 3 — Add network domains")

    domains_payload = [
        {
            "name":          "internal-net",
            "description":   "Internal target network (isolated)",
            "enable_egress": False,
        },
        {
            "name":          "dmz",
            "description":   "DMZ — public-facing segment",
            "enable_egress": True,
        },
    ]
    for d in domains_payload:
        r = api.post(f"/api/v1/recipes/{recipe_id}/domains", d)
        ok("Domain added", f"name={r['name']}  id={r['id']}")

    # ── Step 4 — Workload units ───────────────────────────────────────────────
    section("STEP 4 — Add workload units")

    units_payload = [
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
    ]

    unit_ids: dict[str, str] = {}
    for u in units_payload:
        r = api.post(f"/api/v1/recipes/{recipe_id}/units", u)
        unit_ids[u["name"]] = r["id"]
        ok("Unit added", f"name={r['name']}  id={r['id']}")

    # Challenges are created separately via POST /api/v1/challenges, not on the recipe.

    # ── Step 5 — Gateway ──────────────────────────────────────────────────────
    section("STEP 5 — Add access gateway")

    gateway_payload = {
        "gateway_key":     "edge-gw-01",
        "gateway_type":    "vyos",
        "runtime_profile": "oe:gateway",
        "resource_tier":   "md",
        "is_active":       True,
        "secure_shell":    True,
        "egress_ip":       False,
        "ingress_policies": [
            {"wl_unit": "web-server-01", "int_port": 80,  "proto": "tcp", "name": "http",  "ext_port": 80},
            {"wl_unit": "web-server-01", "int_port": 443, "proto": "tcp", "name": "https", "ext_port": 443},
            {"wl_unit": "attacker-kali", "int_port": 22,  "proto": "tcp", "name": "ssh",   "ext_port": 22},
        ],
    }
    gw = api.post(f"/api/v1/recipes/{recipe_id}/gateways", gateway_payload)
    ok("Gateway added", f"key={gw['gateway_key']}  id={gw['id']}")
    ok("Ingress policies", f"{len(gw['ingress_policies'])} rules")

    # ── Step 6 — Validate ─────────────────────────────────────────────────────
    section("STEP 6 — Validate draft")

    validation = api.post(f"/api/v1/recipes/{recipe_id}/validate")
    if not validation["is_valid"]:
        print("\n  [VALIDATION FAILED]", file=sys.stderr)
        for err in validation["errors"]:
            print(f"    ✗  {err}", file=sys.stderr)
        sys.exit(1)
    ok("Validation passed", "✓  No errors")

    # ── Step 8b — Submit for approval ─────────────────────────────────────────
    section("STEP 8b — Submit for approval")

    submit = api.post(f"/api/v1/recipes/{recipe_id}/submit")
    ok("Approval status", submit["approval_status"])
    ok("Message", submit["message"])

    if submit["approval_status"] != "APPROVED":
        print(
            "\n  Draft is PENDING_APPROVAL — reviewer action needed.\n"
            "  Set AUTO_APPROVE_RECIPES=true in .env to skip this step.",
            file=sys.stderr,
        )
        sys.exit(0)

    # ── Step 9 — Publish ──────────────────────────────────────────────────────
    section("STEP 9 — Publish draft")

    published = api.post(f"/api/v1/recipes/{recipe_id}/publish")
    ok("Version",  published["version_number"])
    ok("Version ID", published["recipe_version_id"])
    #ok("Checksum", published["checksum"])
    ok("Status",   published.get("status", "published"))

    # ── Final output — full recipe detail ─────────────────────────────────────
    section("FINAL — Approved & Published Recipe")

    final = api.get(f"/api/v1/recipes/{recipe_id}")
    show_json(final)

    print(f"\n{'═' * 72}")
    print(f"  Recipe '{recipe_name}' published successfully!")
    print(f"  Recipe ID       : {recipe_id}")
    print(f"  Recipe Version  : {published['recipe_version_id']}")
    print(f"  Version Number  : {published['version_number']}")
    #print(f"  SHA-256 Checksum: {published['checksum']}")
    print(f"{'═' * 72}\n")


# ─────────────────────────────── Entry point ──────────────────────────────────

def main() -> None:
    default_secret = _load_secret_from_env()

    parser = argparse.ArgumentParser(description="E2E recipe creation script")
    parser.add_argument(
        "--base-url", default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--secret", default=default_secret,
        help="JWT secret key — read from .env SECRET_KEY by default",
    )
    args = parser.parse_args()
    run(args.base_url, args.secret)


if __name__ == "__main__":
    main()
