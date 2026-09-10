from uuid import uuid4

import pytest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from products.managed_warehouse.backend.presentation import views


@pytest.fixture(autouse=True)
def _clear_local_control_plane() -> None:
    cache.clear()


@override_settings(MANAGED_WAREHOUSE_LOCAL_DEV_ENABLED=True)
def test_local_control_plane_supports_the_managed_warehouse_ui_lifecycle() -> None:
    organization_id = uuid4()

    with patch(
        "products.managed_warehouse.backend.presentation.views.internal_requests.request",
        side_effect=AssertionError("local managed warehouse requests must not use the network"),
    ):
        missing = views._request("GET", organization_id, "/warehouse/status")
        provisioned = views._request(
            "POST",
            organization_id,
            "/provision",
            json_body={"database_name": "local-demo", "team_id": 1, "schema_name": "project_one"},
        )
        status_response = views._request("GET", organization_id, "/warehouse/status")
        presented_status = views.status_for(organization_id)
        teams_response = views._request("GET", organization_id, "/teams")
        trino_response = views._request("GET", organization_id, "/trino", require_enabled=False)
        monitoring_response = views._request("GET", organization_id, "/monitoring/snapshot")
        deprovisioned = views._request("POST", organization_id, "/deprovision")
        deleted_status = views._request("GET", organization_id, "/warehouse/status")
        deleted = views._request("DELETE", organization_id, "")

    assert missing.status_code == 404
    assert provisioned.status_code == 202
    assert provisioned.data["password"] == "posthog"
    assert status_response.status_code == 200
    assert status_response.data["state"] == "ready"
    assert status_response.data["connection"]["port"] == 15432
    assert presented_status.data["connection"] == {
        "host": "127.0.0.1",
        "port": 15432,
        "database": "ducklake",
        "username": "posthog",
    }
    assert teams_response.data["teams"] == [
        {"team_id": 1, "schema_name": "project_one", "enabled": True, "backfill_enabled": False}
    ]
    assert trino_response.data["status"]["connection"] == {
        "host": "127.0.0.1",
        "port": 38080,
        "username": "posthog",
    }
    assert monitoring_response.data["totals"]["running_queries"] == 0
    assert deprovisioned.status_code == 202
    assert deleted_status.data["state"] == "deleted"
    assert deleted.status_code == 200
    assert views._request("GET", organization_id, "/warehouse/status").status_code == 404


@override_settings(MANAGED_WAREHOUSE_LOCAL_DEV_ENABLED=True)
def test_local_control_plane_enforces_schema_uniqueness() -> None:
    organization_id = uuid4()
    views._request(
        "POST",
        organization_id,
        "/provision",
        json_body={"database_name": "local-demo", "team_id": 1, "schema_name": "project_one"},
    )

    response = views._request(
        "POST",
        organization_id,
        "/teams",
        json_body={"team_id": 2, "schema_name": "project_one"},
    )

    assert response.status_code == 409


@override_settings(MANAGED_WAREHOUSE_LOCAL_DEV_ENABLED=False)
def test_local_control_plane_does_not_bypass_the_feature_flag_when_disabled() -> None:
    organization_id = uuid4()

    with patch(
        "products.managed_warehouse.backend.presentation.views.posthoganalytics.feature_enabled", return_value=False
    ):
        response = views._request("GET", organization_id, "/warehouse/status")

    assert response.status_code == 403
