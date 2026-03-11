# Deployment Creation Logic — Design (CTF Platform)

Production-ready design for deployment creation with constraint enforcement, concurrency safety, and horizontal scalability. Recipe model is unchanged; this document focuses only on **deployment creation** using platform constraints.

---

## 1. Constraint enforcement summary

| Constraint | Enforcement point | Behaviour |
|------------|--------------------|-----------|
| **maximum_concurrent_deployments** | Before insert | Count deployments with `status IN ('ALLOCATING','RUNNING')`. If count ≥ 1000 → reject with **429** or business error **409**. |
| **auto_expire_minutes** | At creation | Set `expires_at = now() + 120` minutes (UTC). Stored on deployment. A separate **expiration job / event** triggers teardown when `expires_at` is reached. |
| **team_configuration** | Request validation | If `enabled == false`: force `team_size = 1`, reject if `member_ids` length > 1. If `enabled == true`: require `min ≤ team_size ≤ max` and `len(member_ids) == team_size`. |

Constraints are **platform-level** (not stored per-recipe). They are read from config or a small `platform_constraints` table and applied at deployment creation time. Recipe is never mutated.

---

## 2. API contract

### 2.1 Request JSON schema

- **Endpoint:** `POST /api/v1/deployments`
- **Content-Type:** `application/json`
- **Auth:** Required (Bearer token).

```json
{
  "recipe_version_id": "uuid",
  "name": "optional string, max 255",
  "member_ids": ["uuid", "..." ]
}
```

- **recipe_version_id** (required): References a **published, approved** `recipe_versions.id`. Must not be `draft_id`.
- **name** (optional): Human-readable label, max 255 chars.
- **member_ids** (optional): List of user/team member UUIDs. Length must satisfy `team_configuration` (see below). Omitted or `[]` implies single-member when teams disabled.

**Excluded from request (as required):**

- No `draft_id`.
- No runtime infra details (subnets, IPs, cluster IDs, etc.).
- No `expires_at` (server-computed from `auto_expire_minutes`).
- No `team_size` (derived from `len(member_ids)` after validation).

### 2.2 Response JSON schema — success (201 Created)

```json
{
  "deployment_id": "uuid",
  "recipe_version_id": "uuid",
  "status": "ALLOCATING",
  "expires_at": "2026-02-23T14:30:00Z",
  "team_size": 1,
  "created_at": "2026-02-23T12:30:00Z"
}
```

- **deployment_id:** New deployment primary key.
- **recipe_version_id:** Echo of request (immutable reference).
- **status:** Initial state is **ALLOCATING**.
- **expires_at:** ISO 8601 UTC; `now() + auto_expire_minutes`.
- **team_size:** Enforced/validated size (1 when teams disabled).
- **created_at:** Server-set creation time (UTC).

### 2.3 Validation error responses

- **400 Bad Request** — Invalid payload (e.g. invalid UUID, schema violation).

```json
{
  "detail": [
    { "loc": ["body", "recipe_version_id"], "msg": "field required", "type": "value_error.missing" }
  ]
}
```

- **404 Not Found** — `recipe_version_id` does not exist.

```json
{
  "detail": {
    "error": "Recipe version not found",
    "recipe_version_id": "uuid"
  }
}
```

- **409 Conflict** — Version not deployable (unpublished / not approved) or **business rule** (e.g. team size).

```json
{
  "detail": {
    "error": "Recipe version not approved for deployment",
    "recipe_version_id": "uuid",
    "approval_status": "PENDING_APPROVAL"
  }
}
```

```json
{
  "detail": {
    "error": "team_configuration",
    "message": "Teams are disabled; only one member allowed",
    "code": "TEAM_SIZE_VIOLATION"
  }
}
```

- **429 Too Many Requests** — Concurrency limit reached.

```json
{
  "detail": {
    "error": "maximum_concurrent_deployments",
    "message": "Concurrent deployment limit reached (1000). Try again later.",
    "code": "DEPLOYMENT_LIMIT_EXCEEDED"
  }
}
```

- **422 Unprocessable Entity** — Version not published.

```json
{
  "detail": {
    "error": "Recipe version not published",
    "recipe_version_id": "uuid"
  }
}
```

### 2.4 Deployment lifecycle initial state

- On successful creation, deployment is inserted with:
  - **status = ALLOCATING**
  - **expires_at = now() + auto_expire_minutes** (e.g. 120)
  - **recipe_version_id** set (no draft_id)
  - **team_size** and **member_ids** stored as validated
- Downstream orchestrator consumes the created record and provisions infra; this service does **not** store runtime infra details in the deployment request/response.

---

## 3. Deployment status state machine

```
                    ┌─────────────────┐
                    │   ALLOCATING  │  ← Initial state on create
                    └────────┬────────┘
                             │
              success        │        failure
                    ┌───────▼───────┐
                    │     RUNNING    │
                    └───────┬───────┘
                             │
         manual teardown /   │   expires_at reached
         user request       │   (scheduler/job)
                    ┌───────▼───────┐
                    │  TEARING_DOWN │
                    └───────┬───────┘
                             │
                    ┌────────▼────────┐
                    │    ARCHIVED   │  (final)
                    └─────────────────┘
```

- **ALLOCATING** → **RUNNING**: Orchestrator reports success.
- **ALLOCATING** → **ARCHIVED**: Orchestrator reports failure (optional; can go to RUNNING then ARCHIVED).
- **RUNNING** → **TEARING_DOWN**: User request or **expiration event**.
- **TEARING_DOWN** → **ARCHIVED**: Teardown complete.

**Concurrency count:** Only **RUNNING** and **ALLOCATING** count toward `maximum_concurrent_deployments`. ARCHIVED and TEARING_DOWN do not.

---

## 4. Where each enforcement happens

| Enforcement | Where |
|-------------|--------|
| **maximum_concurrent_deployments** | In deployment creation path: before inserting a new row, count rows with `status IN ('ALLOCATING','RUNNING')`. If count ≥ limit, return 429 (or 409). Prefer inside same transaction as insert (or after acquiring a lock) to avoid races. |
| **auto_expire_minutes** | At creation time: compute `expires_at = now() + auto_expire_minutes` and persist. **Expiration enforcement** is out-of-band: a **scheduler / cron / event-driven job** (e.g. every 1–5 minutes) selects deployments where `expires_at <= now()` and `status = 'RUNNING'`, then triggers teardown (e.g. publish event or call teardown API). This service only stores the timestamp. |
| **team_configuration** | In request validation (before DB write): if `enabled == false`, require at most one member and set `team_size = 1`; if `enabled == true`, validate `min ≤ len(member_ids) ≤ max` and set `team_size = len(member_ids)`. Reject with 409 and clear error body if violated. |
| **recipe_version_id only, no draft_id** | API schema accepts only `recipe_version_id`. Version existence, `is_published`, and `approval_status == APPROVED` are checked before creating the deployment. Recipe is never mutated. |
| **No runtime infra in request** | Request schema and validation reject any extra fields that represent infra (not in the defined schema). Only `recipe_version_id`, `name`, and `member_ids` are accepted. |

---

## 5. Concurrency and locking strategy

**Goal:** At 1 lakh (100k) users, many concurrent POSTs must not allow the system to exceed 1000 RUNNING+ALLOCATING deployments, and must avoid race conditions.

**Recommended: hybrid approach**

1. **Redis atomic counter (primary gate)**  
   - Key: e.g. `ctf:deployments:active_count`.  
   - Before starting the creation transaction: **INCR** (or **INCR** only when transitioning to ALLOCATING if you create in PENDING first). If count > 1000, **DECR** and return 429.  
   - When a deployment leaves RUNNING/ALLOCATING (e.g. → ARCHIVED), **DECR**.  
   - Pros: very fast, horizontally scalable, no DB lock contention.  
   - Cons: counter can drift if app crashes after INCR and before insert; mitigate with a **periodic reconciliation job** that sets Redis count from DB.

2. **Database check inside transaction (authoritative)**  
   - In the same transaction that inserts the new deployment row:  
     - **SELECT COUNT(*) FROM deployments WHERE status IN ('ALLOCATING','RUNNING')** (or use a partial unique index / advisory lock if needed).  
     - If count ≥ 1000, **ROLLBACK** and return 429.  
   - This guarantees correctness even if Redis is wrong.

3. **Suggested flow**  
   - **Option A (prefer for scale):**  
     - Try Redis INCR; if new value > 1000, DECR and return 429.  
     - Open DB transaction: validate version, team, then **SELECT COUNT(*) ... FOR UPDATE** (or advisory lock) so the count is stable, check count < 1000, insert deployment, commit.  
     - If insert fails (e.g. unique constraint), DECR Redis.  
   - **Option B (simpler):**  
     - DB-only: serializable transaction or **SELECT ... FOR UPDATE** on a single “guard” row (e.g. `platform_constraints` row), then count deployments, check limit, insert. No Redis, but lower throughput under very high concurrency.

**Recommendation:** Use **Redis as a fast gate** to reject excess load early, and **DB count inside transaction** as the source of truth. No need to store per-deployment locks; the critical section is “count + insert” in one transaction.

---

## 6. Suggested DB indexes for scale

- **Count query (concurrency check):**  
  `CREATE INDEX idx_deployments_status_running_allocating ON deployments (status) WHERE status IN ('ALLOCATING','RUNNING');`  
  So `SELECT COUNT(*) FROM deployments WHERE status IN ('ALLOCATING','RUNNING')` is index-only.

- **Expiration job:**  
  `CREATE INDEX idx_deployments_expires_at_running ON deployments (expires_at) WHERE status = 'RUNNING';`  
  So “find deployments to expire” is a small range scan.

- **Lookup by recipe_version (analytics / listing):**  
  `CREATE INDEX idx_deployments_recipe_version_id ON deployments (recipe_version_id);`

- **User / member lookups (if you query by member):**  
  GIN index on `member_ids` (array column) if supported:  
  `CREATE INDEX idx_deployments_member_ids ON deployments USING GIN (member_ids);`

- **Created_at (listing / cleanup):**  
  `CREATE INDEX idx_deployments_created_at ON deployments (created_at DESC);`

---

## 7. Horizontal scalability and safety

- **Stateless API:** No in-memory counters; concurrency enforced via Redis + DB.
- **Idempotency (optional):** If you need exactly-once creation under retries, accept `Idempotency-Key` and store it; on duplicate key return 201 with same `deployment_id`.
- **Connection pooling:** Existing pool (e.g. 20 + 10 overflow) is fine; scale by adding API replicas; DB and Redis handle the load.
- **Transaction scope:** Keep “validate version + check count + insert deployment” in **one** transaction so that under high concurrency you never exceed the limit.
- **Expiration:** Run expiration job in one place (or leader-elected) to avoid duplicate teardown; job only updates status and/or publishes events; actual teardown in orchestrator.

---

## 8. API examples

### Request example

```http
POST /api/v1/deployments HTTP/1.1
Host: api.example.com
Content-Type: application/json
Authorization: Bearer <token>

{
  "recipe_version_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "name": "Weekend CTF Instance",
  "member_ids": ["u1111111-0000-0000-0000-000000000001"]
}
```

### Success response example (201)

```json
{
  "deployment_id": "d9998888-7777-6666-5555-444433332221",
  "recipe_version_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "ALLOCATING",
  "expires_at": "2026-02-23T14:30:00Z",
  "team_size": 1,
  "created_at": "2026-02-23T12:30:00Z"
}
```

### Error response example (429)

```json
{
  "detail": {
    "error": "maximum_concurrent_deployments",
    "message": "Concurrent deployment limit reached (1000). Try again later.",
    "code": "DEPLOYMENT_LIMIT_EXCEEDED"
  }
}
```

### Error response example (409 — team)

```json
{
  "detail": {
    "error": "team_configuration",
    "message": "Teams are disabled; only one member allowed",
    "code": "TEAM_SIZE_VIOLATION"
  }
}
```

---

## 9. Validation logic (pseudocode)

```
FUNCTION create_deployment(request, constraints):
  // 1) Schema + team_configuration
  IF constraints.team_configuration.enabled == false:
    IF len(request.member_ids) > 1:
      RETURN 409, TEAM_SIZE_VIOLATION
    team_size = 1
  ELSE:
    team_size = len(request.member_ids)
    IF team_size < constraints.team_configuration.minimum_members
        OR team_size > constraints.team_configuration.maximum_members:
      RETURN 409, TEAM_SIZE_VIOLATION

  // 2) Version exists, published, approved (existing validation)
  version = get_recipe_version(request.recipe_version_id)
  IF version is NULL: RETURN 404
  IF NOT version.is_published: RETURN 422
  IF version.approval_status != 'APPROVED': RETURN 403

  // 3) Concurrency gate (Redis then DB)
  IF redis.INCR("ctf:deployments:active_count") > constraints.maximum_concurrent_deployments:
    redis.DECR("ctf:deployments:active_count")
    RETURN 429

  BEGIN TRANSACTION
    count = SELECT COUNT(*) FROM deployments
            WHERE status IN ('ALLOCATING','RUNNING')
    IF count >= constraints.maximum_concurrent_deployments:
      redis.DECR("ctf:deployments:active_count")
      ROLLBACK
      RETURN 429

    expires_at = now() + constraints.auto_expire_minutes (minutes)
    INSERT INTO deployments (id, recipe_version_id, status, expires_at, team_size, member_ids, name, created_at)
    VALUES (gen_random_uuid(), request.recipe_version_id, 'ALLOCATING', expires_at, team_size, request.member_ids, request.name, now())
  COMMIT

  RETURN 201, deployment_row
```

---

## 10. State transition diagram (text)

```
                    +------------------+
                    |  ALLOCATING    |  (initial)
                    +--------+---------+
                             |
         +-------------------+-------------------+
         |                                       |
         v                                       v
+----------------+                    +------------------+
|     RUNNING     |                    |   ARCHIVED     |
+--------+-------+                    +------------------+
         |                                       ^
         | user / expiration                     |
         v                                       |
+----------------+                              |
| TEARING_DOWN   |------------------------------+
+----------------+
```

This design keeps recipe immutable, uses only `recipe_version_id`, enforces concurrency and team rules at creation time, and defers expiration to a separate job that triggers teardown—suitable for production and cloud-scale (e.g. 1 lakh users) with Redis + DB and the suggested indexes.
