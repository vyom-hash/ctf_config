#!/usr/bin/env python3
"""
Test recipe creation (full dummy data) then deployment creation; print model JSON for both.

Flow:
  1. Create recipe draft with dummy data (name, description, category).
  2. Add network profile, domains, workload units, gateway.
  3. Validate, submit for approval, publish.
  4. Print the full recipe model JSON (GET /api/v1/recipes/{id}).
  5. Create deployment via POST /api/v1/deployments (recipe_version_id + access + target_env).
  6. Print the full deployment model JSON (GET /api/v1/deployments/{id}).

Usage
-----
  python3 scripts/test_recipe_and_deployment_api.py
  python3 scripts/test_recipe_and_deployment_api.py --base-url http://localhost:8000

Ensure the API server is running and AUTO_APPROVE_RECIPES=true in .env if you want
submit to auto-approve (otherwise the script exits after submit with PENDING_APPROVAL).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import pathlib
import random
import string
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

# Repo root
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# Load .env
_env_file = _REPO_ROOT / ".env"
if _env_file.exists():
    with _env_file.open() as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip())


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_token(secret: str, user_id: str | None = None, ttl_hours: int = 8) -> tuple[str, str]:
    uid = user_id or str(uuid.uuid4())
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({"sub": uid, "exp": int(time.time()) + ttl_hours * 3600}).encode())
    sig_input = f"{header}.{payload}".encode()
    sig = _b64url(hmac.new(secret.encode(), sig_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}", uid


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
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body_text = e.read().decode(errors="replace")
            print(f"[HTTP {e.code}] {method} {path}\n{body_text}", file=sys.stderr)
            sys.exit(1)

    def post(self, path: str, body: Any = None) -> Any:
        return self._request("POST", path, body)

    def put(self, path: str, body: Any = None) -> Any:
        return self._request("PUT", path, body)

    def get(self, path: str) -> Any:
        return self._request("GET", path)


def _rand_suffix(n: int = 4) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def random_recipe_name() -> str:
    adjectives = ["advanced", "stealth", "covert", "elite", "rogue", "shadow"]
    nouns = ["ops", "breach", "intrusion", "escalation", "pivoting", "exfil"]
    return f"{random.choice(adjectives)}-{random.choice(nouns)}-{_rand_suffix()}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Test recipe + deployment creation and print model JSON")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--secret", default=os.environ.get("SECRET_KEY", "change-me"), help="JWT secret")
    args = parser.parse_args()

    secret = args.secret
    base_url = args.base_url
    token, user_id = make_token(secret)
    api = APIClient(base_url, token)

    print("User ID:", user_id)
    print("Base URL:", base_url)
    print()

    # ─── Recipe creation (dummy data) ─────────────────────────────────────────
    print("=== Creating recipe with dummy data ===")

    recipe_name = random_recipe_name()
    draft = api.post("/api/v1/recipes", {
        "name": recipe_name,
        "description": f"Auto-generated CTF scenario: {recipe_name}",
        "category": "CTF",
    })
    recipe_id = draft["recipe_id"]
    print(f"  Recipe created: id={recipe_id}")

    api.put(f"/api/v1/recipes/{recipe_id}/network-profile", {
        "segmentation_strategy": "multi_net",
        "default_subnet_mask": 24,
        "gateway_offset": 1,
        "dns_resolvers": ["8.8.8.8", "1.1.1.1"],
    })
    for d in [
        {"domain_key": "internal-net", "description": "Internal", "public_ingress_enabled": False},
        {"domain_key": "dmz", "description": "DMZ", "public_ingress_enabled": True},
    ]:
        api.post(f"/api/v1/recipes/{recipe_id}/domains", d)
    for u in [
        {"unit_key": "web-server-01", "functional_role": "target", "network_position_index": 1,
         "runtime_profile": "debian-bullseye-slim", "resource_tier": "medium", "assigned_domain": "dmz", "agent_enabled": True,
         "automation_profile": {"bootstrap_reference": "scripts/web/bootstrap.sh"}},
        {"unit_key": "db-server-01", "functional_role": "target", "network_position_index": 2,
         "runtime_profile": "postgres-15-alpine", "resource_tier": "large", "assigned_domain": "internal-net", "agent_enabled": False},
    ]:
        api.post(f"/api/v1/recipes/{recipe_id}/units", u)
    api.post(f"/api/v1/recipes/{recipe_id}/gateways", {
        "gateway_key": "edge-gw-01",
        "gateway_type": "vyos",
        "runtime_profile": "oe:gateway",
        "resource_tier": "md",
        "is_active": True,
        "exposure_rules": [
            {"unit_key": "web-server-01", "internal_port": 80, "transport_protocol": "tcp"},
            {"unit_key": "db-server-01", "internal_port": 5432, "transport_protocol": "tcp"},
        ],
    })

    validation = api.post(f"/api/v1/recipes/{recipe_id}/validate")
    if not validation["is_valid"]:
        print("Validation failed:", validation.get("errors"), file=sys.stderr)
        sys.exit(1)
    print("  Validation passed")

    submit = api.post(f"/api/v1/recipes/{recipe_id}/submit")
    if submit.get("approval_status") != "APPROVED":
        print("Draft is PENDING_APPROVAL. Set AUTO_APPROVE_RECIPES=true in .env to auto-approve.", file=sys.stderr)
        sys.exit(0)
    print("  Submitted & approved")

    published = api.post(f"/api/v1/recipes/{recipe_id}/publish")
    recipe_version_id = published["recipe_version_id"]
    version_number = published["version_number"]
    print(f"  Published: version_number={version_number}, recipe_version_id={recipe_version_id}")

    # ─── Recipe model JSON ───────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("  RECIPE MODEL JSON (GET /api/v1/recipes/{id})")
    print("=" * 72)
    recipe_json = api.get(f"/api/v1/recipes/{recipe_id}")
    print(json.dumps(recipe_json, indent=2, default=str))

    # ─── Deployment creation ───────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("  Creating deployment (POST /api/v1/deployments)")
    print("=" * 72)

    create_payload = {
        "recipe_version_id": str(recipe_version_id),
        "name": f"Test deployment for {recipe_name}",
        "target_env": "openstack-dev",
        "access": {
            "entry_method": "gateway",
            "ssh_public_key_ref": "secret://org/default-ssh-key",
            "floating_ip_enabled": False,
            "remote_console_enabled": True,
        },
    }
    create_resp = api.post("/api/v1/deployments", create_payload)
    deployment_id = create_resp["deployment_id"]
    print(f"  Deployment created: id={deployment_id}, status={create_resp.get('status')}")

    # ─── Deployment model JSON ────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("  DEPLOYMENT MODEL JSON (GET /api/v1/deployments/{id})")
    print("=" * 72)
    deployment_json = api.get(f"/api/v1/deployments/{deployment_id}")
    print(json.dumps(deployment_json, indent=2, default=str))

    print("\n" + "=" * 72)
    print("  Done. Recipe ID:", recipe_id, "| Deployment ID:", deployment_id)
    print("=" * 72)


if __name__ == "__main__":
    main()
