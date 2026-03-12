import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from app.services.registry_metadata import list_registry_service


def make_mock_db(count_return=0, items_return=None):
    """Helper to build a mock db that returns different results for two execute() calls."""
    if items_return is None:
        items_return = []

    mock_db = AsyncMock()

    # First execute() call -> total count; Second -> paginated items
    count_result = MagicMock()
    count_result.scalar.return_value = count_return

    items_result = MagicMock()
    items_result.scalars.return_value.all.return_value = items_return

    mock_db.execute = AsyncMock(side_effect=[count_result, items_result])
    return mock_db


def make_filters(**kwargs):
    """Build a simple namespace mimicking ScriptListFilterSchema."""
    defaults = {
        "tenant_id": None,
        "execution_type": None,
        "status": None,
        "page": 1,
        "page_size": 10,
    }
    defaults.update(kwargs)

    class Filters:
        pass

    f = Filters()
    for k, v in defaults.items():
        setattr(f, k, v)
    return f


# ---------------------------------------------------------------------------
# Basic success / empty cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_registry_success():
    """Returns correct total and items when records exist."""
    mock_items = [MagicMock(), MagicMock(), MagicMock()]
    mock_db = make_mock_db(count_return=3, items_return=mock_items)
    filters = make_filters()

    result = await list_registry_service(filters, mock_db)

    assert result["total"] == 3
    assert len(result["items"]) == 3
    assert result["page"] == 1
    assert result["page_size"] == 10


@pytest.mark.asyncio
async def test_list_registry_empty():
    """Returns zero total and empty items list when no records exist."""
    mock_db = make_mock_db(count_return=0, items_return=[])
    filters = make_filters()

    result = await list_registry_service(filters, mock_db)

    assert result["total"] == 0
    assert result["items"] == []


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_registry_pagination_page_2():
    """Correct page / page_size values are echoed back in response."""
    mock_items = [MagicMock()]
    mock_db = make_mock_db(count_return=11, items_return=mock_items)
    filters = make_filters(page=2, page_size=10)

    result = await list_registry_service(filters, mock_db)

    assert result["page"] == 2
    assert result["page_size"] == 10
    assert result["total"] == 11
    assert len(result["items"]) == 1


@pytest.mark.asyncio
async def test_list_registry_custom_page_size():
    """Custom page_size is reflected correctly in the response."""
    mock_items = [MagicMock(), MagicMock()]
    mock_db = make_mock_db(count_return=2, items_return=mock_items)
    filters = make_filters(page=1, page_size=5)

    result = await list_registry_service(filters, mock_db)

    assert result["page_size"] == 5
    assert len(result["items"]) == 2


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_registry_filter_by_tenant_id():
    """tenant_id filter is applied — db is queried and result returned."""
    tenant = uuid4()
    mock_items = [MagicMock()]
    mock_db = make_mock_db(count_return=1, items_return=mock_items)
    filters = make_filters(tenant_id=tenant)

    result = await list_registry_service(filters, mock_db)

    assert result["total"] == 1
    assert len(result["items"]) == 1


@pytest.mark.asyncio
async def test_list_registry_filter_by_execution_type():
    """execution_type filter is applied — correct results returned."""
    mock_items = [MagicMock()]
    mock_db = make_mock_db(count_return=1, items_return=mock_items)
    filters = make_filters(execution_type="batch")

    result = await list_registry_service(filters, mock_db)

    assert result["total"] == 1


@pytest.mark.asyncio
async def test_list_registry_filter_by_status():
    """status filter is applied — correct results returned."""
    mock_items = [MagicMock()]
    mock_db = make_mock_db(count_return=1, items_return=mock_items)
    filters = make_filters(status="approved")

    result = await list_registry_service(filters, mock_db)

    assert result["total"] == 1
    assert result["items"][0] is mock_items[0]


@pytest.mark.asyncio
async def test_list_registry_all_filters_combined():
    """All supported filters combined — db called twice (count + fetch)."""
    tenant = uuid4()
    mock_items = [MagicMock()]
    mock_db = make_mock_db(count_return=1, items_return=mock_items)
    filters = make_filters(
        tenant_id=tenant,
        execution_type="realtime",
        status="approved",
        page=1,
        page_size=10,
    )

    result = await list_registry_service(filters, mock_db)

    assert result["total"] == 1
    assert len(result["items"]) == 1
    assert mock_db.execute.call_count == 2


@pytest.mark.asyncio
async def test_list_registry_no_filters_no_results():
    """No filters, no matching records — returns empty response."""
    mock_db = make_mock_db(count_return=0, items_return=[])
    filters = make_filters()

    result = await list_registry_service(filters, mock_db)

    assert result == {"total": 0, "page": 1, "page_size": 10, "items": []}


# ---------------------------------------------------------------------------
# DB interaction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_registry_db_called_twice():
    """Service must execute exactly two queries: one for count, one for data."""
    mock_db = make_mock_db(count_return=5, items_return=[MagicMock()] * 5)
    filters = make_filters()

    await list_registry_service(filters, mock_db)

    assert mock_db.execute.call_count == 2