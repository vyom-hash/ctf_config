import pytest
from uuid import uuid4
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException


BASE_URL = "/api/v1/scripts"


class TestGetScriptDetail:

    async def test_get_success(self, async_client):
        script_id = uuid4()

        mock_response = {
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

        with patch(
            "app.api.v1.routers.script_metadata.get_script_detail_service",
            new_callable=AsyncMock,
        ) as mock_get:

            mock_get.return_value = mock_response

            resp = await async_client.get(
                f"{BASE_URL}/{script_id}"
            )

        assert resp.status_code == 201
        assert resp.json()["id"] == str(script_id)


    async def test_404_not_found(self, async_client):
        script_id = uuid4()

        with patch(
            "app.api.v1.routers.script_metadata.get_script_detail_service",
            new_callable=AsyncMock,
        ) as mock_get:

            mock_get.side_effect = HTTPException(
                status_code=404,
                detail="Script not found."
            )

            resp = await async_client.get(
                f"{BASE_URL}/{script_id}"
            )

        assert resp.status_code == 404