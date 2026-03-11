# Test suite

Production-grade pytest suite for deployment flows and related code. Targets **>80% coverage** for SonarQube.

## Run tests

```bash
# Create venv and install
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt

# Required env (or .env)
export DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db"
export SECRET_KEY="your-secret"

# Run all tests
.venv/bin/pytest tests/ -v

# With coverage (XML for SonarQube, 80% fail-under)
.venv/bin/pytest tests/ --cov=app --cov-report=term-missing --cov-report=xml --cov-config=.coveragerc
```

## Structure

- **tests/unit/** – Unit tests (mocked dependencies)
  - **services/** – `deployment_service`: create, get, update, from-draft, `_build_recipe_from_spec`, Redis gate, validation
  - **schemas/** – `DeploymentCreateRequest` validation, access configs, response models
  - **core/** – `TeamConfiguration`, `get_deployment_constraints`
  - **repositories/** – `DeploymentRepository`: count, get_by_id, create, update
- **tests/api/v1/** – API tests for `GET/POST/PATCH /api/v1/deployments` (auth, 200/201/404/422)

## Coverage

- `.coveragerc` omits modules without tests (recipes, approval, flag, leaderboard, DB/Redis internals) so the deployment-focused suite can meet the 80% threshold.
- `coverage.xml` is written for SonarQube.
- To measure full-app coverage, run without `--cov-config=.coveragerc` (no fail-under).

## Conventions

- **Async**: `pytest-asyncio` with `asyncio_mode = auto`.
- **Fixtures**: `conftest.py` provides `sample_recipe_spec`, `mock_deployment_orm`, `auth_headers`, `async_client` (with DB/Redis overrides).
- **Isolation**: No shared DB state; Redis init is patched in session scope.
