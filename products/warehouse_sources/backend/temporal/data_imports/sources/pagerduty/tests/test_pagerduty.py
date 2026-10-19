from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pagerduty import (
    PagerDutySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.pagerduty import (
    PAGE_SIZE,
    PagerDutyResumeConfig,
    _format_incremental_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.source import PagerDutySource


def _driver() -> SourceDriver:
    return SourceDriver(PagerDutySource(), PagerDutySourceConfig(api_token="tok"))


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            (date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestPagination:
    def test_empty_page_stops_iteration(self) -> None:
        # more=True but no items — a missing/empty envelope must stop rather than loop forever.
        result = _driver().run("incidents", [ScriptedResponse(json={"incidents": [], "more": True})])

        assert result.raised is None
        assert result.rows == []
        assert result.params("offset") == ["0"]

    def test_stops_before_crossing_max_offset(self) -> None:
        # PagerDuty 400s when offset + limit exceeds 10000. Full pages that always report more=True
        # must stop before requesting offset=10000 (the first page whose offset+limit would exceed).
        # Always more=True — only the offset ceiling can stop it.
        result = _driver().run("incidents", always(ScriptedResponse(json={"incidents": [{"id": "x"}], "more": True})))

        offsets = result.params("offset")
        assert result.raised is None
        assert offsets[0] == "0"
        assert offsets[-1] == "9900"
        assert "10000" not in offsets


class TestResume:
    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "incidents",
            [ScriptedResponse(json={"incidents": [{"id": "x"}], "more": False})],
            resume_state=PagerDutyResumeConfig(offset=PAGE_SIZE),
        )

        assert result.raised is None
        assert result.params("offset") == [str(PAGE_SIZE)]


class TestIncremental:
    def test_incremental_endpoint_sends_since_and_sort(self) -> None:
        result = _driver().run(
            "incidents",
            [ScriptedResponse(json={"incidents": [{"id": "1"}], "more": False})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("sort_by") == ["created_at:asc"]
        assert result.params("since") == ["2026-01-01T00:00:00+00:00"]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_ok,expected_status",
        [
            (200, True, 200),
            (401, False, 401),
            (403, False, 403),
            (500, False, 500),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_ok: bool, expected_status: int) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            ok, status, _error = validate_credentials("tok")

        assert ok is expected_ok
        assert status == expected_status
        assert {request.path for request in network.requests_log} == {"/users"}

    def test_transport_failure_returns_zero_status(self) -> None:
        with scripted_network(always(ConnectionError("no network"))) as network:
            ok, status, error = validate_credentials("tok")

        assert ok is False
        assert status == 0
        assert error is not None
        assert {request.path for request in network.requests_log} == {"/users"}


class TestPlanGatedEndpoints:
    @pytest.mark.parametrize(
        "endpoint,status_code,body,feature",
        [
            # The statuses PagerDuty answers on an account whose plan lacks the feature. The 402
            # body keeps PagerDuty's documented error code 2014, which the client appends to the
            # raised message as "api error: code=2014".
            ("teams", 402, {"error": {"code": 2014, "message": "Required abilities are unavailable"}}, "teams"),
            ("priorities", 404, {"error": {"message": "Not Found"}}, "incident priorities"),
        ],
    )
    def test_plan_gated_endpoint_syncs_no_rows_and_warns(
        self, endpoint: str, status_code: int, body: dict[str, Any], feature: str
    ) -> None:
        logger = MagicMock()
        result = _driver().run(endpoint, [ScriptedResponse(status=status_code, json=body)], logger=logger)

        assert result.raised is None
        assert result.rows == []
        assert result.paths == [f"/{endpoint}"]
        warning = logger.warning.call_args.args[0]
        assert f"does not include {feature}" in warning
        assert f"the {endpoint} table synced no rows" in warning

    def test_ungated_endpoint_still_fails_on_404(self) -> None:
        # Only endpoints declaring a plan-gated feature swallow a 404; elsewhere it is a real
        # failure the sync must surface.
        result = _driver().run("users", [ScriptedResponse(status=404, json={"error": {"message": "boom"}})])

        assert isinstance(result.raised, HTTPError)
        assert result.paths == ["/users"]

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_plan_gated_endpoint_still_fails_on_other_statuses(self, status_code: int) -> None:
        # Only 402 and 404 mean "your plan does not include this"; a credential problem on a gated
        # endpoint must still fail rather than be reported as an empty table.
        logger = MagicMock()
        result = _driver().run(
            "teams", [ScriptedResponse(status=status_code, json={"error": {"message": "boom"}})], logger=logger
        )

        assert isinstance(result.raised, HTTPError)
        assert result.paths == ["/teams"]
        logger.warning.assert_not_called()

    @pytest.mark.parametrize(
        "endpoint,wrong_status",
        [
            # teams is plan-gated at 402, not 404; priorities is plan-gated at 404, not 402. The
            # gated status is endpoint-specific, so the other status on that same endpoint is a
            # genuine failure and must still raise rather than being read as "plan lacks it".
            ("teams", 404),
            ("priorities", 402),
        ],
    )
    def test_plan_gated_endpoint_fails_on_the_other_endpoints_gated_status(
        self, endpoint: str, wrong_status: int
    ) -> None:
        logger = MagicMock()
        result = _driver().run(
            endpoint, [ScriptedResponse(status=wrong_status, json={"error": {"message": "boom"}})], logger=logger
        )

        assert isinstance(result.raised, HTTPError)
        assert result.paths == [f"/{endpoint}"]
        logger.warning.assert_not_called()
