from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import patch

from products.warehouse_sources.sources.apify_dataset import apify_dataset
from products.warehouse_sources.sources.apify_dataset._config import ApifyDatasetSourceConfig
from products.warehouse_sources.sources.apify_dataset.apify_dataset import ApifyResumeConfig, validate_credentials
from products.warehouse_sources.sources.apify_dataset.settings import (
    ACTOR_BUILDS_ENDPOINT,
    ACTOR_RUNS_ENDPOINT,
    ACTOR_TASKS_ENDPOINT,
    ACTORS_ENDPOINT,
    DATASET_ITEMS_ENDPOINT,
    DATASET_STATISTICS_ENDPOINT,
    REQUEST_QUEUES_ENDPOINT,
    USAGE_MONTHLY_ENDPOINT,
)
from products.warehouse_sources.sources.apify_dataset.source import ApifyDatasetSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, scripted_network


def _driver() -> SourceDriver:
    return SourceDriver(ApifyDatasetSource(), ApifyDatasetSourceConfig(api_token="tok", dataset_id="ds1"))


def _platform_page(items: Any, total: int | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": {"items": items, "total": total if total is not None else len(items)}})


class TestPagination:
    @patch.object(apify_dataset, "PAGE_SIZE", 2)
    def test_progresses_offset_and_terminates_on_header_total(self) -> None:
        # total=3: page 1 (2 rows, full) -> continue; page 2 (offset 2, 1 row) -> offset 4 >= 3 -> stop.
        result = _driver().run(
            DATASET_ITEMS_ENDPOINT,
            [
                ScriptedResponse(json=[{"i": 0}, {"i": 1}], headers={"X-Apify-Pagination-Total": "3"}),
                ScriptedResponse(json=[{"i": 2}], headers={"X-Apify-Pagination-Total": "3"}),
            ],
        )

        assert [row["i"] for row in result.rows] == [0, 1, 2]
        assert result.params("offset") == ["0", "2"]
        assert result.params("limit") == ["2", "2"]
        assert result.params("format") == ["json", "json"]
        assert result.saved_states == [ApifyResumeConfig(offset=2)]

    @patch.object(apify_dataset, "PAGE_SIZE", 2)
    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            DATASET_ITEMS_ENDPOINT,
            [ScriptedResponse(json=[{"i": 200}], headers={"X-Apify-Pagination-Total": "201"})],
            resume_state=ApifyResumeConfig(offset=200),
        )

        assert result.params("offset") == ["200"]

    @patch.object(apify_dataset, "PAGE_SIZE", 2)
    def test_non_list_body_raises_loudly(self) -> None:
        # A misrouted request returning an error object (not a list) must fail loud, not sync it as a row.
        result = _driver().run(
            DATASET_ITEMS_ENDPOINT,
            [ScriptedResponse(json={"error": "wrong shape"}, headers={"X-Apify-Pagination-Total": "0"})],
        )

        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


class TestValidateCredentials:
    def test_not_found_message(self) -> None:
        with scripted_network([ScriptedResponse(status=404)]):
            ok, msg = validate_credentials("tok", "ds1")
        assert ok is False
        assert "Dataset not found" in (msg or "")

    def test_network_error_message(self) -> None:
        with scripted_network([ConnectionResetError("boom")]):
            ok, msg = validate_credentials("tok", "ds1")
        assert ok is False
        assert "reach the Apify API" in (msg or "")


class TestPlatformEndpoints:
    @patch.object(apify_dataset, "PAGE_SIZE", 2)
    def test_pages_on_envelope_total_and_checkpoints_offset(self) -> None:
        result = _driver().run(
            ACTOR_RUNS_ENDPOINT,
            [_platform_page([{"id": "a"}, {"id": "b"}], total=3), _platform_page([{"id": "c"}], total=3)],
        )

        assert [row["id"] for row in result.rows] == ["a", "b", "c"]
        assert result.params("offset") == ["0", "2"]
        assert result.saved_states == [ApifyResumeConfig(offset=2)]

    def test_incremental_sends_started_after_from_watermark(self) -> None:
        result = _driver().run(
            ACTOR_RUNS_ENDPOINT,
            [_platform_page([])],
            incremental_field="startedAt",
            db_incremental_field_last_value=datetime(2026, 3, 4, 5, 6, 7, 890000, tzinfo=UTC),
        )

        # Truncated to whole seconds, which only ever re-fetches the boundary row.
        assert result.requests[0].param("startedAfter") == "2026-03-04T05:06:07Z"

    def test_missing_envelope_raises_loudly(self) -> None:
        result = _driver().run(
            ACTORS_ENDPOINT, [ScriptedResponse(json={"error": {"type": "insufficient-permissions"}})]
        )

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)

    def test_monthly_usage_becomes_one_row_per_day(self) -> None:
        result = _driver().run(
            USAGE_MONTHLY_ENDPOINT,
            [
                ScriptedResponse(
                    json={
                        "data": {
                            "usageCycle": {"startAt": "2026-03-01T00:00:00.000Z", "endAt": "2026-03-31T23:59:59.999Z"},
                            "monthlyServiceUsage": {"ACTOR_COMPUTE_UNITS": {"quantity": 3}},
                            "dailyServiceUsages": [
                                {"date": "2026-03-01", "serviceUsage": {}, "totalUsageCreditsUsd": 0.5},
                                {"date": "2026-03-02", "serviceUsage": {}, "totalUsageCreditsUsd": 1.5},
                            ],
                            "totalUsageCreditsUsdBeforeVolumeDiscount": 2.5,
                            "totalUsageCreditsUsdAfterVolumeDiscount": 2.0,
                        }
                    }
                )
            ],
        )

        assert [row["date"] for row in result.rows] == ["2026-03-01", "2026-03-02"]
        assert [row["totalUsageCreditsUsd"] for row in result.rows] == [0.5, 1.5]
        assert result.rows[0]["usageCycleStartAt"] == "2026-03-01T00:00:00.000Z"
        assert result.rows[0]["usageCycleEndAt"] == "2026-03-31T23:59:59.999Z"
        assert result.rows[0]["totalUsageCreditsUsdAfterVolumeDiscount"] == 2.0
        # A single object endpoint has no cursor, so nothing is checkpointed.
        assert len(result.requests) == 1
        assert result.saved_states == []

    @pytest.mark.parametrize(
        "endpoint, path, unnamed",
        [
            (ACTOR_TASKS_ENDPOINT, "/v2/actor-tasks", None),
            (ACTOR_BUILDS_ENDPOINT, "/v2/actor-builds", None),
            # Without `unnamed`, the default queues that runs crawl from are left out.
            (REQUEST_QUEUES_ENDPOINT, "/v2/request-queues", "true"),
        ],
    )
    @patch.object(apify_dataset, "PAGE_SIZE", 2)
    def test_account_lists_page_as_full_refresh(self, endpoint: str, path: str, unnamed: str | None) -> None:
        result = _driver().run(
            endpoint,
            [_platform_page([{"id": "a"}, {"id": "b"}], total=3), _platform_page([{"id": "c"}], total=3)],
            incremental_field="createdAt",
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        assert [row["id"] for row in result.rows] == ["a", "b", "c"]
        assert result.paths == [path, path]
        assert result.params("offset") == ["0", "2"]
        assert result.params("unnamed") == [unnamed, unnamed]
        # No server-side time filter exists, so a stored watermark must not leak into the request.
        assert all(set(query) <= {"offset", "limit", "unnamed"} for query in result.queries)
        assert result.saved_states == [ApifyResumeConfig(offset=2)]

    @pytest.mark.parametrize(
        "field_statistics, expected_rows",
        [
            (
                {"price": {"min": 59, "max": 89, "nullCount": 0, "emptyCount": 1}, "name": {"nullCount": 122}},
                [
                    {"field": "price", "min": 59, "max": 89, "nullCount": 0, "emptyCount": 1},
                    {"field": "name", "nullCount": 122},
                ],
            ),
            # The Actor declares no fields schema.
            (None, []),
            ({}, []),
            ({"broken": None, "ok": {"min": 1}}, [{"field": "ok", "min": 1}]),
        ],
    )
    def test_dataset_statistics_becomes_one_row_per_field(
        self, field_statistics: dict[str, Any] | None, expected_rows: list[dict[str, Any]]
    ) -> None:
        driver = SourceDriver(ApifyDatasetSource(), ApifyDatasetSourceConfig(api_token="tok", dataset_id="me~my/ds"))
        result = driver.run(
            DATASET_STATISTICS_ENDPOINT, [ScriptedResponse(json={"data": {"fieldStatistics": field_statistics}})]
        )

        assert result.raised is None
        assert result.rows == expected_rows
        # The dataset id stays one path segment, as for dataset_items.
        assert result.paths == ["/v2/datasets/me~my%2Fds/statistics"]
        assert result.saved_states == []
