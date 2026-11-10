from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, cast

import pytest

import requests

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network
from products.warehouse_sources.sources.surveysparrow._config import SurveySparrowSourceConfig
from products.warehouse_sources.sources.surveysparrow.source import SurveySparrowSource
from products.warehouse_sources.sources.surveysparrow.surveysparrow import (
    SurveySparrowResumeConfig,
    _format_cutoff,
    _format_datetime_cutoff,
    validate_credentials,
)

BASE_URL = "https://api.surveysparrow.com"


def _page(
    items: list[dict[str, Any]] | None, *, has_next_page: bool | None = None, status_code: int = 200
) -> ScriptedResponse:
    body: dict[str, Any] = {"data": items or []}
    if has_next_page is not None:
        body["has_next_page"] = has_next_page
    return ScriptedResponse(status=status_code, json=body)


def _raw(body: Any, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


def _driver() -> SourceDriver:
    return SourceDriver(SurveySparrowSource(), SurveySparrowSourceConfig(access_token="token", data_center="us"))


class TestFormatCutoff:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04"),
            (date(2026, 3, 4), "2026-03-04"),
            ("2026-03-04", "2026-03-04"),
        ],
    )
    def test_floors_watermark_to_day(self, value: object, expected: str) -> None:
        assert _format_cutoff(value) == expected


class TestFormatDatetimeCutoff:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-03T02:58:14"),
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=timezone(timedelta(hours=5))), "2026-03-02T21:58:14"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-03T02:58:14"),
            (date(2026, 3, 4), "2026-03-03T00:00:00"),
            ("2026-03-04T02:58:14", "2026-03-04T02:58:14"),
        ],
    )
    def test_converts_to_utc_with_one_day_overlap(self, value: object, expected: str) -> None:
        assert _format_datetime_cutoff(value) == expected


class TestTopLevel:
    def test_paginates_and_checkpoints_next_page(self) -> None:
        result = _driver().run(
            "surveys",
            [
                _page([{"id": 1}], has_next_page=True),
                _page([{"id": 2}], has_next_page=False),
            ],
        )

        assert [r["id"] for r in result.rows] == [1, 2]
        assert result.params("page") == ["1", "2"]
        assert result.params("limit") == ["100", "100"]
        # Checkpoint once, pointing at the NEXT page (page 2); the last page saves nothing.
        assert [s.paginator_state for s in result.saved_states] == [{"page": 2}]

    def test_empty_page_terminates_despite_stale_flag(self) -> None:
        result = _driver().run("surveys", [_page([], has_next_page=True)])

        assert result.rows == []
        assert len(result.requests) == 1


class TestFanout:
    def test_incremental_cutoff_applied_to_children_but_not_survey_enumeration(self) -> None:
        result = _driver().run(
            "responses",
            [
                _page([{"id": 10}], has_next_page=False),
                _page([{"id": 1}], has_next_page=False),
            ],
            incremental_field="completed_time",
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )

        assert result.requests[0].param("date.gte") is None  # survey enumeration
        child = next(request for request in result.requests if "/v3/responses" in request.path)
        assert child.param("date.gte") == "2026-01-02"

    @pytest.mark.parametrize("endpoint", ["questions", "channels"])
    def test_child_is_scoped_by_survey_id_and_rows_carry_it(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [
                _page([{"id": 10}, {"id": 20}], has_next_page=False),
                _page([{"id": 1}], has_next_page=False),
                _page([{"id": 1}], has_next_page=False),
            ],
        )

        child_requests = [request for request in result.requests if f"/v3/{endpoint}" in request.path]
        assert [request.param("survey_id") for request in child_requests] == ["10", "20"]
        assert [(r["survey_id"], r["id"]) for r in result.rows] == [(10, 1), (20, 1)]


class TestIncrementalRequestShaping:
    @pytest.mark.parametrize(
        "incremental, expected_cutoff",
        [
            (True, "2026-01-01T03:04:05"),
            (False, None),
        ],
    )
    def test_tickets_send_updated_date_cutoff_only_when_incremental(
        self, incremental: bool, expected_cutoff: str | None
    ) -> None:
        kwargs: dict[str, Any] = (
            {
                "incremental_field": "updated_at",
                "db_incremental_field_last_value": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            }
            if incremental
            else {}
        )
        result = _driver().run("tickets", [_page([{"id": 1}], has_next_page=False)], **kwargs)

        assert [r["id"] for r in result.rows] == [1]
        assert result.params("updated_date.gte") == [expected_cutoff]
        assert result.params("limit") == ["100"]

    @pytest.mark.parametrize(
        "endpoint, expected_sort_mode",
        [
            # Requested with order=ASC on completed_time.
            ("responses", "asc"),
            # /v3/tickets has no sort param, so the order is unknown.
            ("tickets", None),
        ],
    )
    def test_sort_mode_matches_request_order(self, endpoint: str, expected_sort_mode: str | None) -> None:
        result = _driver().run(endpoint, always(_page([], has_next_page=False)))

        assert result.response is not None
        assert result.response.sort_mode == expected_sort_mode


class TestRetry:
    @pytest.mark.parametrize("status_code", [429, 500, 502, 503])
    def test_retryable_statuses_exhaust_then_raise(self, status_code) -> None:
        result = _driver().run("surveys", always(_page([], has_next_page=False, status_code=status_code)))

        assert result.raised is not None
        assert len(result.requests) == 5

    def test_client_error_is_not_retried(self) -> None:
        result = _driver().run("surveys", [_page([], has_next_page=False, status_code=401)])

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_ok",
        [
            (200, True),
        ],
    )
    def test_status_mapping(self, status_code, expected_ok) -> None:
        with scripted_network(always(_raw({}, status_code=status_code))) as network:
            ok, error = validate_credentials("token", BASE_URL)

        assert ok is expected_ok
        if not ok:
            assert error
        assert network.requests_log[0].url == f"{BASE_URL}/v3/surveys"

    def test_token_is_declared_redactable(self) -> None:
        with scripted_network([_raw({})]) as network:
            validate_credentials("secret-token", BASE_URL)

        assert network.session_options[0].get("redact_values") == ("secret-token",)


class TestResumeConfigCompatibility:
    def test_legacy_saved_state_still_parses(self) -> None:
        # A checkpoint written by the pre-framework code must still deserialize via dataclass(**saved).
        cfg = SurveySparrowResumeConfig(**cast("dict[str, Any]", {"page": 4, "remaining_survey_ids": [20]}))
        assert cfg.page == 4
        assert cfg.remaining_survey_ids == [20]
        assert cfg.paginator_state is None
        assert cfg.fanout_state is None
