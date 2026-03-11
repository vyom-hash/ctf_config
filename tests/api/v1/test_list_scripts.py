import pytest
from uuid import uuid4
from unittest.mock import patch, AsyncMock


BASE_URL = "/api/v1/scripts"


class TestListScripts:

    async def test_list_success_default_pagination(self, async_client):
        script_id = uuid4()

        mock_item = {
            "id": script_id,
            "tenant_id": uuid4(),
            "title": "Test Script",
            "summary": "Test summary",
            "category": "test",
            "execution_type": "sync",
            "status": "DRAFT",
            "checksum_sha256": "abc123",
            "artifact_location": "/tmp/file.py",
            "current_version": 1,
            "new_version": 2,
        }

        mock_response = {
            "total": 1,
            "page": 1,
            "page_size": 10,
            "items": [mock_item],
        }

        with patch(
            "app.api.v1.routers.script_metadata.list_scripts_service",
            new_callable=AsyncMock,
        ) as mock_list:

            mock_list.return_value = mock_response

            resp = await async_client.get(BASE_URL)

        assert resp.status_code == 201
        assert resp.json()["total"] == 1


    async def test_list_with_filters(self, async_client):
        tenant_id = uuid4()

        mock_response = {
            "total": 0,
            "page": 1,
            "page_size": 5,  # 👈 match request
            "items": [],
        }

        with patch(
            "app.api.v1.routers.script_metadata.list_scripts_service",
            new_callable=AsyncMock,
        ) as mock_list:

            mock_list.return_value = mock_response

            resp = await async_client.get(
                BASE_URL,
                params={
                    "tenant_id": str(tenant_id),
                    "category": "test",
                    "execution_type": "sync",
                    "status": "DRAFT",
                    "page": 1,
                    "page_size": 5,
                },
            )

        assert resp.status_code == 201
        assert resp.json()["page_size"] == 5


    async def test_invalid_page_number(self, async_client):
        resp = await async_client.get(
            BASE_URL,
            params={"page": 0},
        )

        assert resp.status_code == 422