from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rippling import (
    RipplingSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rippling.rippling import (
    PAGE_SIZE,
    RipplingResumeConfig,
    _absolutize_next_url,
    _build_params,
    _format_filter_timestamp,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rippling.settings import RIPPLING_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.rippling.source import RipplingSource


def _response(items: list[dict[str, Any]], next_link: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"results": items, "next_link": next_link})


def _driver() -> SourceDriver:
    return SourceDriver(RipplingSource(), RipplingSourceConfig(api_token="token"))


class TestFormatFilterTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 10, 1, 3, 4, 5, tzinfo=UTC), "2024-10-01T03:04:05"),
            (datetime(2024, 10, 1, 3, 4, 5), "2024-10-01T03:04:05"),
            (date(2024, 10, 1), "2024-10-01T00:00:00"),
            ("2024-10-01T00:00:00", "2024-10-01T00:00:00"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_filter_timestamp(value) == expected


class TestBuildParams:
    @pytest.mark.parametrize(
        "endpoint, should_use_incremental_field, incremental_field, expected_filter, expected_order_by",
        [
            ("workers", True, "updated_at", "updated_at ge 2024-10-01T00:00:00", "updated_at"),
            ("workers", True, "created_at", "created_at ge 2024-10-01T00:00:00", "created_at"),
            ("workers", False, None, None, "created_at"),
            ("time_entries", True, None, "updated_at ge 2024-10-01T00:00:00", "updated_at"),
            ("time_entries", False, None, None, "created_at"),
            # No server-side time filter exists, so a stray incremental flag must not send one.
            ("leave_requests", True, "updated_at", None, "created_at"),
            ("payroll_runs", True, None, None, "check_date"),
            ("payroll_runs", False, None, None, "check_date"),
            # The payouts list rejects OData filters and accepts no order_by.
            ("variable_compensation_payouts", True, "updated_at", None, None),
            ("variable_compensation_payouts", False, None, None, None),
        ],
    )
    def test_request_params(
        self, endpoint, should_use_incremental_field, incremental_field, expected_filter, expected_order_by
    ):
        params = _build_params(
            RIPPLING_ENDPOINTS[endpoint],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=datetime(2024, 10, 1, tzinfo=UTC),
            incremental_field=incremental_field,
        )

        assert params.get("filter") == expected_filter
        assert params.get("order_by") == expected_order_by
        assert params["limit"] == PAGE_SIZE


class TestAbsolutizeNextUrl:
    @pytest.mark.parametrize(
        "next_link",
        [
            "https://attacker.example/workers",
            "//attacker.example/workers",
            "http://rest.ripplingapis.com/workers",
            "https://rest.ripplingapis.com.attacker.example/workers",
        ],
    )
    def test_rejects_off_domain_links(self, next_link):
        with pytest.raises(ValueError):
            _absolutize_next_url(next_link)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            # A valid token without the companies.read scope still 403s; only 401
            # means the token itself is bad.
            (403, True),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code, expected):
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            assert validate_credentials("token") is expected


class TestGetRows:
    def test_absolute_next_link_used_as_is(self):
        absolute = "https://rest.ripplingapis.com/workers?cursor=xyz"

        result = _driver().run("workers", [_response([{"id": "1"}], next_link=absolute), _response([])])

        assert result.urls[1] == absolute

    def test_resumes_from_saved_state(self):
        resume_url = "https://rest.ripplingapis.com/workers?cursor=resume"

        result = _driver().run(
            "workers", [_response([{"id": "9"}])], resume_state=RipplingResumeConfig(next_url=resume_url)
        )

        assert result.urls[0] == resume_url

    def test_off_domain_next_link_raises(self):
        result = _driver().run("workers", [_response([{"id": "1"}], next_link="https://attacker.example/workers")])

        assert isinstance(result.raised, ValueError)
        assert "off-domain" in str(result.raised)


class TestWorkerPayrollRecordsFanout:
    def test_walks_every_run_and_page_and_stamps_run_id(self):
        script = route(
            {
                "/payroll-runs": [
                    _response([{"id": "run-1"}], next_link="/payroll-runs?cursor=p2"),
                    _response([{"id": "run-2"}]),
                ],
                "/payroll-runs/run-1/worker-payroll-records": [
                    _response(
                        [{"id": "rec-1", "worker_id": "w-1"}],
                        next_link="/payroll-runs/run-1/worker-payroll-records?cursor=c2",
                    ),
                    _response([{"id": "rec-2", "worker_id": "w-2", "run_id": "run-1"}]),
                ],
                "/payroll-runs/run-2/worker-payroll-records": [
                    _response([{"id": "rec-1", "worker_id": "w-1"}]),
                ],
            }
        )

        result = _driver().run("worker_payroll_records", script)

        assert result.raised is None
        assert [(row["run_id"], row["id"]) for row in result.rows] == [
            ("run-1", "rec-1"),
            ("run-1", "rec-2"),
            ("run-2", "rec-1"),
        ]
        assert not any("_payroll_runs_id" in row for row in result.rows)
        parent_queries = [q for q, path in zip(result.queries, result.paths) if path == "/payroll-runs"]
        child_queries = [q for q, path in zip(result.queries, result.paths) if path != "/payroll-runs"]
        assert parent_queries[0]["order_by"] == ("check_date",)
        assert all("order_by" not in q for q in child_queries)

    def test_resume_skips_completed_runs_and_continues_the_current_one(self):
        resume = RipplingResumeConfig(
            fanout_state={
                "completed": ["/payroll-runs/run-1/worker-payroll-records"],
                "current": "/payroll-runs/run-2/worker-payroll-records",
                "child_state": {
                    "next_url": "https://rest.ripplingapis.com/payroll-runs/run-2/worker-payroll-records?cursor=c9"
                },
            }
        )
        script = route(
            {
                "/payroll-runs": [_response([{"id": "run-1"}, {"id": "run-2"}])],
                "/payroll-runs/run-2/worker-payroll-records": [_response([{"id": "rec-9", "worker_id": "w-9"}])],
            }
        )

        result = _driver().run("worker_payroll_records", script, resume_state=resume)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["rec-9"]
        assert result.urls[-1] == "https://rest.ripplingapis.com/payroll-runs/run-2/worker-payroll-records?cursor=c9"
