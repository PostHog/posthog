import datetime as dt
from decimal import Decimal

import pytest
from unittest.mock import MagicMock, patch

from posthog.models import Organization, Team

from products.managed_warehouse.backend.facade.api import duckgres_logical_bytes_rows_for_period
from products.managed_warehouse.backend.models import DuckgresDailyScanUsage, DuckgresUsageCursor
from products.managed_warehouse.backend.temporal.duckgres_usage.acking import day_boundary_ack
from products.managed_warehouse.backend.temporal.duckgres_usage.anomalies import detect_anomalies
from products.managed_warehouse.backend.temporal.duckgres_usage.client import ScanRow, UsageResponse, fetch_usage
from products.managed_warehouse.backend.temporal.duckgres_usage.mirror import promote_window
from products.managed_warehouse.backend.temporal.duckgres_usage.team_resolution import (
    ResolvedTeams,
    resolve_billing_teams,
)
from products.managed_warehouse.backend.tests.temporal.duckgres_usage.test_client import USAGE_BODY, _response

ORG = "018f0000-0000-0000-0000-000000000000"
DAY = dt.date(2026, 7, 6)
LOW = dt.datetime(2026, 7, 5, 23, 59, 59, tzinfo=dt.UTC)
HIGH = dt.datetime(2026, 7, 7, tzinfo=dt.UTC)
EXACT_BYTES = 9007199254740993


@pytest.fixture
def scan_configured(settings) -> None:
    settings.DUCKGRES_API_URL = "https://warehouse.example.com"
    settings.DUCKGRES_INTERNAL_SECRET = "test-secret"


@pytest.mark.usefixtures("scan_configured")
@pytest.mark.parametrize(
    "value,valid", [(EXACT_BYTES, True), (10**37 + 7, True), (1.5, False), (True, False), ("1", False), (10**38, False)]
)
@patch("products.managed_warehouse.backend.temporal.duckgres_usage.client.internal_requests")
def test_scan_integer_wire_values_remain_exact(mock_requests: MagicMock, value: object, valid: bool) -> None:
    body = {
        **USAGE_BODY,
        "scans": [
            {
                "date": "2026-07-06",
                "org_id": ORG,
                "team_id": 42,
                "query_source": "standard",
                "logical_bytes_scanned": value,
            }
        ],
    }
    mock_requests.request.return_value = _response(200, body)
    result = fetch_usage()
    assert result.unparsed_row_count == (0 if valid else 1)
    assert [row.logical_bytes_scanned for row in result.scan_rows] == ([value] if valid else [])
    assert mock_requests.request.call_args.kwargs["headers"]["X-Hogtower-Billing-Metrics"] == "logical_bytes_scanned"


@pytest.mark.usefixtures("scan_configured")
@patch("products.managed_warehouse.backend.temporal.duckgres_usage.client.internal_requests")
def test_legacy_server_without_scans_remains_readable(mock_requests: MagicMock) -> None:
    mock_requests.request.return_value = _response(200, USAGE_BODY)
    response = fetch_usage()
    assert response.scan_rows == []
    assert response.scans_malformed is False
    assert response.unparsed_row_count == 0


@pytest.mark.usefixtures("scan_configured")
@pytest.mark.parametrize("scans", [None, {}, "broken"])
@patch("products.managed_warehouse.backend.temporal.duckgres_usage.client.internal_requests")
def test_malformed_scans_withhold_shared_ack(mock_requests: MagicMock, scans: object) -> None:
    mock_requests.request.return_value = _response(200, {**USAGE_BODY, "scans": scans})
    response = fetch_usage()
    anomalies = detect_anomalies(response, ResolvedTeams([], [], set()), None, 0)
    assert any(a.kind == "scans_malformed" and a.recoverable for a in anomalies)


@pytest.mark.django_db
def test_scan_snapshots_restate_exact_totals_across_sources_and_guard_regression() -> None:
    org = Organization.objects.create(id=ORG, name="Scan test")
    team = Team.objects.create(organization=org, name="Scan team")
    response = UsageResponse(
        watermark_low=LOW,
        watermark_high=HIGH,
        rows=[],
        scan_rows=[
            ScanRow(DAY, ORG, team.id, "standard", EXACT_BYTES),
            ScanRow(DAY, ORG, team.id, "endpoints", 11),
        ],
    )
    DuckgresUsageCursor.objects.create(singleton=1, last_complete_watermark=HIGH)
    assert promote_window(response).rows_written == 2
    assert promote_window(response).rows_written == 2
    assert duckgres_logical_bytes_rows_for_period(DAY, DAY) == [{"team_id": team.id, "total": EXACT_BYTES + 11}]
    stored = DuckgresDailyScanUsage.all_teams.get(query_source="standard")
    assert stored.logical_bytes_scanned == Decimal(EXACT_BYTES)
    regressed = UsageResponse(
        watermark_low=LOW,
        watermark_high=HIGH,
        rows=[],
        scan_rows=[
            ScanRow(DAY, ORG, team.id, "standard", 1),
        ],
    )
    result = promote_window(regressed)
    assert result.regressed_org_ids == {ORG}
    assert duckgres_logical_bytes_rows_for_period(DAY, DAY) == [{"team_id": team.id, "total": EXACT_BYTES + 11}]
    assert day_boundary_ack(watermark_low=LOW, watermark_high=HIGH) == HIGH - dt.timedelta(seconds=1)


@pytest.mark.django_db
def test_scan_team_resolution_deduplicates_and_folds_deleted_hints() -> None:
    org = Organization.objects.create(id=ORG, name="Remap test")
    team = Team.objects.create(organization=org, name="Live team")
    duplicate = ScanRow(DAY, ORG, 0, "standard", 5)
    resolution = resolve_billing_teams([], [], [duplicate, duplicate, ScanRow(DAY, ORG, 999999, "standard", 7)])
    assert resolution.duplicate_row_count == 1
    assert resolution.scan_rows == [ScanRow(DAY, ORG, team.id, "standard", 12)]
