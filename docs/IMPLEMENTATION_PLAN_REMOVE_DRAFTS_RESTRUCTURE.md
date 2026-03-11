# Implementation Plan: Remove `/drafts` from Recipe Endpoints & Restructure (Lab Recipe Only)

**Goal:** Remove the `/drafts` path segment from all recipe endpoints so the API exposes **lab recipes** only. Path parameter `draft_id` becomes `recipe_id` in URLs and in response bodies where it denotes the recipe resource.

**Scope:**
- **In scope:** Recipe router paths, path parameter names, OpenAPI operation_ids/summaries, response schema field names (`draft_id` → `recipe_id` where it refers to the recipe), and all call sites (tests, scripts, services that pass through).
- **Optional / later:** Renaming deployment API `recipe_draft_id` → `recipe_id` and DB column `recipe_draft_id` → `recipe_id` (same UUID; can be a separate change for backward compatibility).

---

## 1. Endpoint mapping (old → new)

| # | Method | Old path | New path | Operation ID (old → new) |
|---|--------|----------|----------|---------------------------|
| 1 | GET | `/api/v1/recipes` | `/api/v1/recipes` | `recipes.list` (unchanged) |
| 2 | POST | `/api/v1/recipes/drafts` | `/api/v1/recipes` | `recipes.drafts.create` → `recipes.create` |
| 3 | GET | `/api/v1/recipes/drafts/{draft_id}` | `/api/v1/recipes/{recipe_id}` | `recipes.drafts.get` → `recipes.get` |
| 4 | PUT | `/api/v1/recipes/drafts/{draft_id}` | `/api/v1/recipes/{recipe_id}` | `recipes.drafts.update` → `recipes.update` |
| 5 | DELETE | `/api/v1/recipes/drafts/{draft_id}` | `/api/v1/recipes/{recipe_id}` | `recipes.drafts.delete` → `recipes.delete` |
| 6 | PUT | `/api/v1/recipes/drafts/{draft_id}/network-profile` | `/api/v1/recipes/{recipe_id}/network-profile` | `recipes.drafts.networkProfile.set` → `recipes.networkProfile.set` |
| 7 | GET | `/api/v1/recipes/drafts/{draft_id}/network-profile` | `/api/v1/recipes/{recipe_id}/network-profile` | `recipes.drafts.networkProfile.get` → `recipes.networkProfile.get` |
| 8 | POST | `/api/v1/recipes/drafts/{draft_id}/domains` | `/api/v1/recipes/{recipe_id}/domains` | `recipes.drafts.domains.create` → `recipes.domains.create` |
| 9 | GET | `/api/v1/recipes/drafts/{draft_id}/domains` | `/api/v1/recipes/{recipe_id}/domains` | `recipes.drafts.domains.list` → `recipes.domains.list` |
| 10 | GET | `/api/v1/recipes/drafts/{draft_id}/domains/{domain_id}` | `/api/v1/recipes/{recipe_id}/domains/{domain_id}` | `recipes.drafts.domains.get` → `recipes.domains.get` |
| 11 | PATCH | `/api/v1/recipes/drafts/{draft_id}/domains/{domain_id}` | `/api/v1/recipes/{recipe_id}/domains/{domain_id}` | `recipes.drafts.domains.update` → `recipes.domains.update` |
| 12 | DELETE | `/api/v1/recipes/drafts/{draft_id}/domains/{domain_id}` | `/api/v1/recipes/{recipe_id}/domains/{domain_id}` | `recipes.drafts.domains.delete` → `recipes.domains.delete` |
| 13 | POST | `/api/v1/recipes/drafts/{draft_id}/units` | `/api/v1/recipes/{recipe_id}/units` | `recipes.drafts.units.create` → `recipes.units.create` |
| 14 | GET | `/api/v1/recipes/drafts/{draft_id}/units` | `/api/v1/recipes/{recipe_id}/units` | `recipes.drafts.units.list` → `recipes.units.list` |
| 15 | GET | `/api/v1/recipes/drafts/{draft_id}/units/{unit_id}` | `/api/v1/recipes/{recipe_id}/units/{unit_id}` | `recipes.drafts.units.get` → `recipes.units.get` |
| 16 | PATCH | `/api/v1/recipes/drafts/{draft_id}/units/{unit_id}` | `/api/v1/recipes/{recipe_id}/units/{unit_id}` | `recipes.drafts.units.update` → `recipes.units.update` |
| 17 | DELETE | `/api/v1/recipes/drafts/{draft_id}/units/{unit_id}` | `/api/v1/recipes/{recipe_id}/units/{unit_id}` | `recipes.drafts.units.delete` → `recipes.units.delete` |
| 18 | POST | `/api/v1/recipes/drafts/{draft_id}/challenges` | `/api/v1/recipes/{recipe_id}/challenges` | `recipes.drafts.challenges.create` → `recipes.challenges.create` |
| 19 | GET | `/api/v1/recipes/drafts/{draft_id}/challenges` | `/api/v1/recipes/{recipe_id}/challenges` | `recipes.drafts.challenges.list` → `recipes.challenges.list` |
| 20 | GET | `/api/v1/recipes/drafts/{draft_id}/challenges/{challenge_id}` | `/api/v1/recipes/{recipe_id}/challenges/{challenge_id}` | `recipes.drafts.challenges.get` → `recipes.challenges.get` |
| 21 | PATCH | `/api/v1/recipes/drafts/{draft_id}/challenges/{challenge_id}` | `/api/v1/recipes/{recipe_id}/challenges/{challenge_id}` | `recipes.drafts.challenges.update` → `recipes.challenges.update` |
| 22 | DELETE | `/api/v1/recipes/drafts/{draft_id}/challenges/{challenge_id}` | `/api/v1/recipes/{recipe_id}/challenges/{challenge_id}` | `recipes.drafts.challenges.delete` → `recipes.challenges.delete` |
| 23 | POST | `/api/v1/recipes/drafts/{draft_id}/gateways` | `/api/v1/recipes/{recipe_id}/gateways` | `recipes.drafts.gateways.create` → `recipes.gateways.create` |
| 24 | GET | `/api/v1/recipes/drafts/{draft_id}/gateways` | `/api/v1/recipes/{recipe_id}/gateways` | `recipes.drafts.gateways.list` → `recipes.gateways.list` |
| 25 | GET | `/api/v1/recipes/drafts/{draft_id}/gateways/{gateway_id}` | `/api/v1/recipes/{recipe_id}/gateways/{gateway_id}` | `recipes.drafts.gateways.get` → `recipes.gateways.get` |
| 26 | PATCH | `/api/v1/recipes/drafts/{draft_id}/gateways/{gateway_id}` | `/api/v1/recipes/{recipe_id}/gateways/{gateway_id}` | `recipes.drafts.gateways.update` → `recipes.gateways.update` |
| 27 | DELETE | `/api/v1/recipes/drafts/{draft_id}/gateways/{gateway_id}` | `/api/v1/recipes/{recipe_id}/gateways/{gateway_id}` | `recipes.drafts.gateways.delete` → `recipes.gateways.delete` |
| 28 | PUT | `/api/v1/recipes/drafts/{draft_id}/scoring` | `/api/v1/recipes/{recipe_id}/scoring` | `recipes.drafts.scoring.set` → `recipes.scoring.set` |
| 29 | GET | `/api/v1/recipes/drafts/{draft_id}/scoring` | `/api/v1/recipes/{recipe_id}/scoring` | `recipes.drafts.scoring.get` → `recipes.scoring.get` |
| 30 | POST | `/api/v1/recipes/drafts/{draft_id}/validate` | `/api/v1/recipes/{recipe_id}/validate` | `recipes.drafts.validate` → `recipes.validate` |
| 31 | POST | `/api/v1/recipes/drafts/{draft_id}/submit` | `/api/v1/recipes/{recipe_id}/submit` | `recipes.drafts.submit` → `recipes.submit` |
| 32 | POST | `/api/v1/recipes/drafts/{draft_id}/review` | `/api/v1/recipes/{recipe_id}/review` | `recipes.drafts.review` → `recipes.review` |
| 33 | POST | `/api/v1/recipes/drafts/{draft_id}/publish` | `/api/v1/recipes/{recipe_id}/publish` | `recipes.drafts.publish` → `recipes.publish` |
| — | *(removed)* | ~~`POST /api/v1/recipes/{recipe_id}/challenges/{challenge_key}/submit`~~ | — | Flag submission is handled by **exercise instance** API; this recipe-level endpoint was removed. |
| 34 | GET | `/api/v1/recipes/leaderboard` | `/api/v1/recipes/leaderboard` | (unchanged) |
| 35 | GET | `/api/v1/recipes/leaderboard/me` | `/api/v1/recipes/leaderboard/me` | (unchanged) |

**Route order note:** After removing `/drafts`, `GET /recipes/{recipe_id}` must not conflict with `GET /recipes/leaderboard`. FastAPI matches in order; keep `GET /leaderboard` and `GET /leaderboard/me` before any `GET /{recipe_id}` if necessary, or ensure `leaderboard` is a literal path so `/{recipe_id}` does not match it (current code has `/{recipe_id}` for flag submit; list is `""`). So define `GET /leaderboard` and `GET /leaderboard/me` before `GET /{recipe_id}`.

---

## 2. Response and request body field renames (API contract)

| Schema | Old field | New field | Notes |
|--------|-----------|-----------|--------|
| DraftResponse | `draft_id` | `recipe_id` | Create response; same UUID. |
| DraftDetailResponse | `draft_id` | `recipe_id` | Full recipe detail; serializer comment references "draft_id at the top". |
| SubmitForApprovalResponse | `draft_id` | `recipe_id` | |
| ReviewResponse | `draft_id` | `recipe_id` | |

**Optional (deployment, can be phase 2):**

| Schema | Old field | New field |
|--------|-----------|-----------|
| DeploymentCreateRequest | `recipe_draft_id` | `recipe_id` (for “by recipe” mode) |
| DeploymentCreateFromDraftRequest | `recipe_draft_id` | `recipe_id` |
| DeploymentResponse / DeploymentListItem | `recipe_draft_id` | `recipe_id` |

Internal service/repo arguments can stay as `draft_id` (or be renamed to `recipe_id` for clarity); only the **HTTP API** path and request/response field names are standardized on “recipe”.

---

## 3. Files to modify (checklist)

### 3.1 Router and API surface
- **`app/api/v1/routers/recipes.py`**
  - Replace every path `/drafts/{draft_id}` with `/{recipe_id}`.
  - Rename every path parameter `draft_id` → `recipe_id` in handler signatures.
  - Update all `operation_id` from `recipes.drafts.*` to `recipes.*` as in the table above.
  - Update summaries/descriptions that say "draft" to "recipe" or "lab recipe" where appropriate.
  - Ensure route order: list `GET ""`, then `POST ""`, then literal routes (`/leaderboard`, `/leaderboard/me`), then `GET /{recipe_id}`, `PUT /{recipe_id}`, etc. (Flag submit `POST /{recipe_id}/challenges/{challenge_key}/submit` was removed; use exercise instance API.)

### 3.2 Recipe schemas (response field renames)
- **`app/api/schemas/recipe.py`**
  - `DraftResponse`: `draft_id` → `recipe_id`.
  - `DraftDetailResponse`: `draft_id` → `recipe_id`; update `_strip_nested_recipe_ids` / serializer comment if it references `draft_id`.
  - `SubmitForApprovalResponse`: `draft_id` → `recipe_id`.
  - `ReviewResponse`: `draft_id` → `recipe_id`.

### 3.3 Recipe service layer (internal only; optional rename)
- **`app/services/recipe_service.py`**
  - All functions that take `draft_id: uuid.UUID` can keep the argument name (internal) or rename to `recipe_id` for consistency. If renamed, update every call site and error message ("Draft '…' not found" → "Recipe '…' not found").
  - `DraftResponse(draft_id=...)` → `DraftResponse(recipe_id=...)` (or keep schema field as `recipe_id` and pass `recipe_id=recipe_id`).
  - Same for any place that builds `SubmitForApprovalResponse` / `ReviewResponse` with `draft_id=` → `recipe_id=`.

### 3.4 Approval service
- **`app/services/approval_service.py`**
  - Functions take `draft_id`; callers pass the same UUID from the new path param `recipe_id`. No API change; internal param can stay `draft_id` or be renamed to `recipe_id`.

### 3.5 Deployment (optional phase 2)
- **`app/api/schemas/deployment.py`**
  - If standardizing deployment API: `recipe_draft_id` → `recipe_id` in request/response schemas and validators.
- **`app/api/v1/routers/deployments.py`**
  - Docstrings and error messages that mention `recipe_draft_id`.
- **`app/services/deployment_service.py`**
  - Use of `request.recipe_draft_id` → `request.recipe_id` if schema is changed; internal variables and error context can stay or align with new name.
- **`app/models/deployment.py`**
  - DB column remains `recipe_draft_id` unless a migration renames it; API can still expose `recipe_id` and map to/from that column.

### 3.6 Tests
- **`tests/api/v1/test_recipes_router.py`**
  - Replace every URL `/api/v1/recipes/drafts/{draft_id}` with `/api/v1/recipes/{recipe_id}`; use variable `recipe_id` instead of `draft_id` where relevant.
- **`tests/unit/services/test_recipe_service_delete.py`**
  - All `draft_id` in calls to `delete_draft`, `delete_domain`, etc. can stay (internal); if service renames param to `recipe_id`, update test signatures/calls.
- **`tests/unit/services/test_deployment_service.py`**
  - Any assertion on `recipe_draft_id` in responses; if deployment schema is changed to `recipe_id`, update assertions. Mock/create payloads with `recipe_id` if that becomes the request field.
- **`tests/unit/schemas/test_deployment_schemas.py`**
  - If deployment schema is updated: `recipe_draft_id` → `recipe_id` in test data and assertions.
- **`tests/api/v1/test_deployments_router.py`**
  - Request bodies that use `recipe_draft_id` → `recipe_id` if schema changed.
- **`tests/conftest.py`**
  - Fixtures like `recipe_draft_id` can be renamed to `recipe_id` for clarity when used in recipe/deployment tests.

### 3.7 Scripts and E2E
- **`e2e_recipe.py`**
  - After create, use `recipe_id = draft["recipe_id"]` (or keep reading same key if response still returns `recipe_id`). Replace every `/api/v1/recipes/drafts/{draft_id}` with `/api/v1/recipes/{recipe_id}` and use `recipe_id` variable.
- **`e2e_deployment.py`**
  - Replace `/api/v1/recipes/drafts/{draft_id}` with `/api/v1/recipes/{recipe_id}`; CLI arg can stay `draft_id` for backward compatibility or be renamed to `recipe_id`.
- **`scripts/generate_deployment_json.py`**
  - Same: use `recipe_id` in URLs; CLI and internal vars can be renamed from `draft_id` to `recipe_id` for consistency.

### 3.8 Repositories and models
- **`app/repositories/recipe_repository.py`**
  - Method `get_version_ids_by_draft_id` can stay (internal); no URL change. Optional rename to `get_version_ids_by_recipe_id`.
- **`app/models/recipe.py`**, **`app/models/deployment.py`**
  - Comments only; update references from “draft” to “recipe” where it describes the API/resource. No DB or column renames in this plan.

### 3.9 Docs and comments
- **`app/core/security.py`**, **`app/services/approval_service.py`** (docstrings)
  - Replace “POST /drafts/{id}/...” with “POST /recipes/{id}/...” where describing the API.
- **`docs/` or `change_logs/`**
  - Add a short changelog entry: “Recipe API: removed `/drafts` from paths; use `/api/v1/recipes/{recipe_id}` and `recipe_id` in responses.”

---

## 4. Implementation order

1. **Schemas**  
   - In `app/api/schemas/recipe.py`: rename `draft_id` → `recipe_id` in `DraftResponse`, `DraftDetailResponse`, `SubmitForApprovalResponse`, `ReviewResponse`. Update serializers/comments that reference `draft_id`.

2. **Recipe service**  
   - In `app/services/recipe_service.py`: ensure create returns `DraftResponse(recipe_id=...)`; approval/publish flows that build `SubmitForApprovalResponse`/`ReviewResponse` use `recipe_id=`. Optionally rename internal `draft_id` parameters to `recipe_id` and adjust error messages.

3. **Recipe router**  
   - In `app/api/v1/routers/recipes.py`: change all paths and path params as in section 1; update operation_ids and descriptions; fix route order for `/{recipe_id}` vs `/leaderboard`.

4. **Tests (recipe)**  
   - Update `tests/api/v1/test_recipes_router.py` and `tests/unit/services/test_recipe_service_delete.py` to use new URLs and, if applicable, new response fields and param names.

5. **Scripts and E2E**  
   - Update `e2e_recipe.py`, `e2e_deployment.py`, `scripts/generate_deployment_json.py` to call new endpoints and use `recipe_id` in URLs.

6. **Deployment API (optional)**  
   - If doing phase 2: deployment schemas and deployment service/router and related tests as in 3.5 and 3.6.

7. **Docs and comments**  
   - Update docstrings and add changelog entry.

---

## 5. Summary

- **Endpoints:** Remove `/drafts` from every recipe path; use `/{recipe_id}` and path param `recipe_id`.
- **Operation IDs:** `recipes.drafts.*` → `recipes.*` (e.g. `recipes.create`, `recipes.get`, `recipes.domains.list`).
- **Response fields:** `draft_id` → `recipe_id` in recipe-related response schemas.
- **Internal code:** Optionally rename `draft_id` → `recipe_id` in services/repos for consistency; not required for the API contract.
- **Deployment:** Optional later step to rename `recipe_draft_id` → `recipe_id` in deployment request/response and docs; DB column can remain for compatibility unless a migration is desired.

This plan keeps the **lab recipe** as the single resource at `/api/v1/recipes` and `/api/v1/recipes/{recipe_id}` with no “drafts” in the URL surface.
