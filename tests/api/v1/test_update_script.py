import pytest
from uuid import uuid4
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException


BASE_URL = "/api/v1/scripts"


class TestUpdateScript:

    async def test_201_update_success(self, async_client):
        script_id = uuid4()

        mock_response = {
            "id": script_id,
            "tenant_id": uuid4(),
            "title": "Updated Title",
            "summary": "Updated summary",
            "category": "test",
            "execution_type": "sync",
            "status": "DRAFT",
            "checksum_sha256": "abc123",
            "artifact_location": "/tmp/file.py",
            "current_version": 1,
            "new_version": 2
        }

        with patch(
            "app.api.v1.routers.script_metadata.update_script_service",
            new_callable=AsyncMock,
        ) as mock_update:

            mock_update.return_value = mock_response

            resp = await async_client.put(
                f"{BASE_URL}/{script_id}",
                json={"title": "Updated Title"},
            )

        assert resp.status_code == 201
        assert resp.json()["title"] == "Updated Title"


    async def test_404_when_not_found(self, async_client):
        script_id = uuid4()

        with patch(
            "app.api.v1.routers.script_metadata.update_script_service",
            new_callable=AsyncMock,
        ) as mock_update:

            mock_update.side_effect = HTTPException(
                status_code=404,
                detail="Script not found."
            )

            resp = await async_client.put(
                f"{BASE_URL}/{script_id}",
                json={"title": "Updated Title"},
            )

        assert resp.status_code == 404


    async def test_422_invalid_type(self, async_client):
        script_id = uuid4()

        resp = await async_client.put(
            f"{BASE_URL}/{script_id}",
            json={"title": 123},  # invalid type
        )

        assert resp.status_code == 422