import json
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import validate_incremental_sync
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.tenjin import tenjin
from products.warehouse_sources.backend.temporal.data_imports.sources.tenjin.settings import TENJIN_REPORTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tenjin.tenjin import (
    LOOKBACK_DAYS,
    MAX_HISTORY_DAYS,
    TENJIN_BASE_URL,
    TenjinCredentialsError,
    TenjinResumeConfig,
    TenjinRetryableError,
    resolve_start_date,
    tenjin_source,
    validate_credentials,
)

TODAY = date(2026, 6, 30)

_TRACKED_SESSION_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client"
    ".make_tracked_session"
)


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _report_page(rows: list[dict[str, Any]], next_url: str | None = None) -> Response:
    links: dict[str, str] = {"self": f"{TENJIN_BASE_URL}/reports/spend"}
    if next_url:
        links["next"] = next_url
    return _make_http_response(
        {
            "data": [{"type": "report", "attributes": row} for row in rows],
            "links": links,
            "meta": {"count": len(rows)},
        }
    )


def _params(url: str, params: dict[str, Any]) -> dict[str, str]:
    from_url = {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}
    return {**from_url, **{key: str(value) for key, value in params.items()}}


def _drive(
    responses: list[Response],
    endpoint: str = "app_report",
    manager: Any = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> tuple[Any, list[dict[str, str]], list[list[dict[str, Any]]]]:
    """Drive ``tenjin_source`` with a mocked HTTP session.

    Returns ``(manager, sent, batches)`` where ``sent`` holds the effective query params of each
    request (merged from the request URL and params, since the paginator moves them between the
    two), captured at send-time because the Request object is mutated in place between pages.
    """
    if manager is None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

    sent: list[dict[str, str]] = []
    response_iter = iter(responses)

    def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
        sent.append(_params(request.url, dict(request.params or {})))
        return next(response_iter)

    with (
        patch(_TRACKED_SESSION_PATH) as MockSession,
        mock.patch.object(tenjin, "_today", return_value=TODAY),
    ):
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.side_effect = lambda req: req
        mock_session.send.side_effect = fake_send

        response = tenjin_source(
            api_key="test-key",
            endpoint=endpoint,
            team_id=123,
            job_id="test_job",
            resumable_source_manager=manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
        )
        batches = list(cast(Iterable[Any], response.items()))
    return manager, sent, batches


class TestResolveStartDate:
    def test_full_refresh_starts_at_the_history_cap(self) -> None:
        assert resolve_start_date(False, None, TODAY) == TODAY - timedelta(days=MAX_HISTORY_DAYS)

    def test_incremental_rewinds_the_watermark_by_the_lookback(self) -> None:
        # Tenjin restates recent days (late SKAN postbacks, cost corrections), so an incremental
        # run must re-read a trailing window.
        assert resolve_start_date(True, "2026-06-20", TODAY) == date(2026, 6, 20) - timedelta(days=LOOKBACK_DAYS)

    def test_incremental_without_watermark_falls_back_to_full_history(self) -> None:
        assert resolve_start_date(True, None, TODAY) == TODAY - timedelta(days=MAX_HISTORY_DAYS)

    def test_unparseable_watermark_falls_back_to_full_history(self) -> None:
        assert resolve_start_date(True, "not-a-date", TODAY) == TODAY - timedelta(days=MAX_HISTORY_DAYS)

    def test_watermark_older_than_the_history_cap_is_clamped(self) -> None:
        assert resolve_start_date(True, "2010-01-01", TODAY) == TODAY - timedelta(days=MAX_HISTORY_DAYS)

    def test_future_watermark_is_clamped_to_today(self) -> None:
        # A watermark ahead of today would otherwise produce an inverted date range.
        assert resolve_start_date(True, "2030-01-01", TODAY) == TODAY


class TestRequestShaping:
    def test_full_refresh_requests_full_history(self) -> None:
        _, sent, _ = _drive([_report_page([{"date": "2026-06-30", "app_id": "a1"}])])

        assert sent[0]["start_date"] == (TODAY - timedelta(days=MAX_HISTORY_DAYS)).isoformat()
        assert sent[0]["end_date"] == TODAY.isoformat()

    def test_incremental_requests_only_the_watermark_range(self) -> None:
        _, sent, _ = _drive(
            [_report_page([{"date": "2026-06-28", "app_id": "a1"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-06-28",
        )

        assert sent[0]["start_date"] == "2026-06-21"
        assert sent[0]["end_date"] == "2026-06-30"

    @parameterized.expand([(name,) for name in TENJIN_REPORTS])
    def test_every_report_is_requested_at_daily_granularity(self, endpoint: str) -> None:
        # Rows carry no `date` at totals-daily granularity, which would break the primary key,
        # the partition key, and the incremental cursor at once.
        _, sent, _ = _drive([_report_page([{"date": "2026-06-30"}])], endpoint=endpoint)

        assert sent[0]["granularity"] == "daily"
        assert sent[0]["group_by"] == TENJIN_REPORTS[endpoint].group_by
        assert sent[0]["metrics"] == TENJIN_REPORTS[endpoint].metrics


class TestPaginationAndResume:
    def test_rows_are_flattened_report_attributes(self) -> None:
        # The pipeline must receive the flat attributes dict, not the JSON:API wrapper, so the
        # primary key columns (`date`, `app_id`, ...) exist at the row root for the Delta merge.
        row = {"date": "2026-06-30", "app_id": "a1", "spend": 12.5}
        _, _, batches = _drive([_report_page([row])])

        assert batches == [[row]]

    def test_follows_next_link_then_terminates(self) -> None:
        next_url = f"{TENJIN_BASE_URL}/reports/spend?group_by=app&page=2&per_page=1000"
        _, sent, batches = _drive(
            [
                _report_page([{"date": "2026-06-29", "app_id": "a1"}], next_url=next_url),
                _report_page([{"date": "2026-06-30", "app_id": "a1"}]),
            ]
        )

        assert len(batches) == 2
        assert len(sent) == 2
        assert sent[1]["page"] == "2"

    def test_saves_next_url_after_each_non_terminal_page(self) -> None:
        next_url = f"{TENJIN_BASE_URL}/reports/spend?group_by=app&page=2&per_page=1000"
        manager, _, _ = _drive(
            [
                _report_page([{"date": "2026-06-29", "app_id": "a1"}], next_url=next_url),
                _report_page([{"date": "2026-06-30", "app_id": "a1"}]),
            ]
        )

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [TenjinResumeConfig(next_url=next_url)]

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager, _, _ = _drive([_report_page([{"date": "2026-06-30", "app_id": "a1"}])])

        manager.save_state.assert_not_called()

    def test_resume_starts_at_the_saved_next_url(self) -> None:
        saved_url = f"{TENJIN_BASE_URL}/reports/spend?group_by=app&page=7&per_page=1000"
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = TenjinResumeConfig(next_url=saved_url)

        _, sent, _ = _drive([_report_page([{"date": "2026-06-30", "app_id": "a1"}])], manager=manager)

        assert len(sent) == 1
        assert sent[0]["page"] == "7"


class TestTenjinSourceResponse:
    def test_unknown_report_raises(self) -> None:
        with pytest.raises(ValueError):
            tenjin_source(
                api_key="test-key",
                endpoint="nope",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=MagicMock(spec=ResumableSourceManager),
                db_incremental_field_last_value=None,
            )

    @parameterized.expand([(name,) for name in TENJIN_REPORTS])
    def test_source_response_supports_incremental_sync(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        with mock.patch.object(tenjin, "_today", return_value=TODAY):
            response = tenjin_source(
                api_key="test-key",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=None,
            )

        # Tenjin documents no row order for report responses, so the watermark must only be
        # persisted at successful job end; asc mode would checkpoint a misleading per-batch max.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date"]
        assert not response.has_duplicate_primary_keys
        validate_incremental_sync(True, response)


class TestValidateCredentials:
    def _validate(self, response: Response) -> bool:
        session = MagicMock()
        session.get.return_value = response
        with (
            mock.patch.object(tenjin, "make_tracked_session", return_value=session),
            mock.patch.object(tenjin, "_today", return_value=TODAY),
        ):
            return validate_credentials("token")

    def test_success(self) -> None:
        assert self._validate(_make_http_response({"data": []})) is True

    def test_probe_is_one_day_and_one_row(self) -> None:
        session = MagicMock()
        session.get.return_value = _make_http_response({"data": []})
        with (
            mock.patch.object(tenjin, "make_tracked_session", return_value=session),
            mock.patch.object(tenjin, "_today", return_value=TODAY),
        ):
            validate_credentials("token")

        params = {key: values[0] for key, values in parse_qs(urlparse(session.get.call_args.args[0]).query).items()}
        assert params["start_date"] == params["end_date"] == TODAY.isoformat()
        assert params["per_page"] == "1"

    @parameterized.expand([(429,), (500,), (503,)])
    def test_throttle_and_5xx_are_retryable(self, status: int) -> None:
        with pytest.raises(TenjinRetryableError):
            self._validate(_make_http_response({}, status_code=status))

    @parameterized.expand(
        [
            # Verified against the live API: a missing/unrecognized token returns 401 with
            # {"error":"Unauthorized. Invalid access token provided."}; a token Tenjin can't
            # decode returns 403 with {"error":"AuthHandler::DecodeError"}.
            (401, {"error": "Unauthorized. Invalid access token provided."}),
            (403, {"error": "AuthHandler::DecodeError"}),
        ]
    )
    def test_rejections_are_credential_errors_naming_the_required_permission(
        self, status: int, body: dict[str, Any]
    ) -> None:
        with pytest.raises(TenjinCredentialsError) as exc:
            self._validate(_make_http_response(body, status_code=status))
        assert "Reporting Metrics API permission" in str(exc.value)

    def test_unexpected_status_does_not_blame_the_token(self) -> None:
        with pytest.raises(TenjinCredentialsError) as exc:
            self._validate(_make_http_response({}, status_code=418))
        assert "unexpected response (HTTP 418)" in str(exc.value)

    def test_transport_errors_propagate(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch.object(tenjin, "make_tracked_session", return_value=session):
            with pytest.raises(requests.ConnectionError):
                validate_credentials("token")
