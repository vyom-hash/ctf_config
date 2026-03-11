"""
Deployment constants — not stored in DB; used in API responses only.

provider_profile is injected into POST/GET/PATCH deployment responses.
"""
from __future__ import annotations

from typing import Any

# Hardcoded provider profile; not persisted. Used in deployment create/get/update responses.
PROVIDER_PROFILE: dict[str, Any] = {
    "provider_type": "openstack",
    "region": "RegionOne",
    "auth_url": "http://192.168.2.210:5000",
    "domain_name": "Default",
    "user_name": "heyadav",
    "password": "JaiHind1!",
    "tenant_name": "terraform-temp",
}
