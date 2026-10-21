from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.cloudzero import (
    CloudzeroResumeConfig,
    _rolling_incremental_start_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.source import CloudzeroSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudzero import (
    CloudzeroSourceConfig,
)


class TestRollingIncrementalStartDate:
    @parameterized.expand(
        [
            ("datetime", datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC), "2026-01-08T12:00:00+00:00"),
            ("date", date(2026, 1, 15), "2026-01-08T00:00:00+00:00"),
            ("iso_string", "2026-01-15T12:00:00+00:00", "2026-01-08T12:00:00+00:00"),
            ("naive_datetime", datetime(2026, 1, 15, 12, 0, 0), "2026-01-08T12:00:00+00:00"),
        ]
    )
    def test_rolls_back_by_restatement_window(self, _name: str, value: Any, expected: str) -> None:
        # CloudZero can restate historical costs, so the incremental start_date must roll back
        # a fixed window rather than resuming exactly where the last sync left off.
        assert _rolling_incremental_start_date(value) == expected


def _costs_page(next_cursor: str | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "costs": rows,
        "pagination": {
            "page_count": 1,
            "item_count": len(rows),
            "total_count": len(rows),
            "cursor": {
                "next_cursor": next_cursor,
                "previous_cursor": None,
                "has_next": next_cursor is not None,
                "has_previous": False,
            },
        },
    }


def _list_page(data_key: str, next_cursor: str | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        data_key: rows,
        "pagination": {
            "cursor": {
                "next_cursor": next_cursor,
                "has_next": next_cursor is not None,
            },
        },
    }


class TestCloudzeroSourceTransport:
    """End-to-end behaviour of ``CloudzeroSource`` via ``rest_api_resource``."""

    @staticmethod
    def _driver(*, group_by: str | None = None) -> SourceDriver:
        return SourceDriver(CloudzeroSource(), CloudzeroSourceConfig(api_key="test-key", group_by=group_by))

    @parameterized.expand(
        [
            ("Budgets", "/v2/budgets", {"expand": ["current"]}, _list_page("budgets", None, [{"id": "b-1"}])),
            ("Dimensions", "/v2/billing/dimensions", {"include_hidden": "true"}, {"dimensions": [{"id": "service"}]}),
            ("Insights", "/v2/insights", {}, _list_page("insights", None, [{"id": "i-1"}])),
            # This endpoint answers with a bare array, so it carries no envelope key to select on.
            ("RecommendationTypes", "/v2/optimize/recommendation_types", {}, [{"id": "CIR-AWS-00216"}]),
            (
                "Recommendations",
                "/v2/optimize/recommendations",
                {"limit": 1000},
                _list_page("recommendations", None, [{"recommendation_id": "r-1"}]),
            ),
        ]
    )
    def test_list_endpoint_reads_its_own_path_params_and_envelope(
        self, endpoint: str, path: str, expected_params: dict[str, Any], body: Any
    ) -> None:
        result = self._driver().run(endpoint, [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.requests[0].origin == "https://api.cloudzero.com"
        assert result.paths == [path]
        assert result.queries == [
            {
                key: tuple(str(value) for value in values) if isinstance(values, list) else (str(values),)
                for key, values in expected_params.items()
            }
        ]
        assert len(result.rows) == 1

    @parameterized.expand(
        [
            ("Budgets", "budgets"),
            ("Insights", "insights"),
            ("Recommendations", "recommendations"),
        ]
    )
    def test_paginated_list_endpoint_follows_the_cursor(self, endpoint: str, data_key: str) -> None:
        # Without the cursor paginator these endpoints would sync only their first page.
        result = self._driver().run(
            endpoint,
            [
                ScriptedResponse(json=_list_page(data_key, "cursor-1", [{"id": "1"}])),
                ScriptedResponse(json=_list_page(data_key, None, [{"id": "2"}])),
            ],
        )

        assert result.raised is None
        assert result.params("cursor") == [None, "cursor-1"]
        assert len(result.rows) == 2

    def test_costs_resume_seeds_paginator_with_saved_cursor(self) -> None:
        result = self._driver().run(
            "Costs",
            [ScriptedResponse(json=_costs_page(None, [{"usage_date": "2025-01-04T00:00:00+00:00", "cost": 4.0}]))],
            resume_state=CloudzeroResumeConfig(next_cursor="cursor-resumed"),
        )

        assert result.raised is None
        assert result.params("cursor") == ["cursor-resumed"]

    def test_incremental_rolls_start_date_back_from_watermark(self) -> None:
        result = self._driver().run(
            "Costs",
            [ScriptedResponse(json=_costs_page(None, [{"usage_date": "2026-01-15T00:00:00+00:00", "cost": 5.0}]))],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-15T00:00:00+00:00",
        )

        assert result.raised is None
        assert result.requests[0].param("start_date") == "2026-01-08T00:00:00+00:00"

    def test_group_by_sent_as_repeated_query_param(self) -> None:
        result = self._driver(group_by="service,account").run(
            "Costs",
            [
                ScriptedResponse(
                    json=_costs_page(None, [{"usage_date": "2025-01-05T00:00:00+00:00", "service": "ec2", "cost": 5.0}])
                )
            ],
        )

        assert result.raised is None
        assert result.requests[0].query["group_by"] == ("service", "account")


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, (True, None)),
        ]
    )
    def test_status_code_maps_to_validity(
        self, _name: str, status_code: int, expected: tuple[bool, str | None]
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("test-key") == expected
        assert network.requests_log
        assert {request.path for request in network.requests_log} == {"/v2/billing/dimensions"}
        assert all(request.headers["authorization"] == "test-key" for request in network.requests_log)
