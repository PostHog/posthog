import json
import datetime as dt
from collections.abc import Iterable
from typing import Any, cast

import pytest
import time_machine
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.singular.settings import HISTORY_DAYS, LOOKUPS
from products.warehouse_sources.backend.temporal.data_imports.sources.singular.singular import (
    ACCESS_ERROR,
    AUTH_ERROR,
    CREATE_MAX_ATTEMPTS,
    QUOTA_ERROR,
    REPORT_FAILED_ERROR,
    REPORT_POLL_MAX_ATTEMPTS,
    REQUEST_ERROR,
    SingularNonRetryableError,
    SingularReportQuery,
    SingularResumeConfig,
    SingularRetryableError,
    parse_field_list,
    report_rows,
    report_start_date,
    singular_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.singular.source import SingularSource

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.singular.singular"
_API_KEY = "sk-invented-key"
_DOWNLOAD_URL = "https://reports.example.com/files/report.json?Signature=invented-signature"
_NOW = "2026-06-30T12:00:00Z"
_QUERY = SingularReportQuery(dimensions=("app", "source"), metrics=("adn_cost",))


def _response(status: int = 200, value: Any = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = status < 400
    body = {"status": 0 if status < 400 else status, "substatus": 0, "value": value}
    resp.json.return_value = body
    resp.text = json.dumps(body)
    return resp


def _file_response(rows: Any, status: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = status < 400
    resp.json.return_value = rows
    return resp


def _wire(
    mock_session: mock.MagicMock,
    rows_by_day: dict[str, list[dict[str, Any]]] | None = None,
    poll_statuses: list[str] | None = None,
    create_responses: list[mock.MagicMock] | None = None,
) -> list[dict[str, str]]:
    created: list[dict[str, str]] = []
    statuses = list(poll_statuses or ["DONE"])
    queued = list(create_responses or [])
    polled_day: list[str] = []

    def post(url: str, **kwargs: Any) -> mock.MagicMock:
        if queued:
            response = queued.pop(0)
            if not response.ok:
                return response
        created.append(kwargs["data"])
        return _response(value={"report_id": kwargs["data"]["start_date"]})

    def get(url: str, **kwargs: Any) -> mock.MagicMock:
        if url.endswith("/get_report_status"):
            polled_day.append(kwargs["params"]["report_id"])
            status = statuses.pop(0) if len(statuses) > 1 else statuses[0]
            return _response(
                value={
                    "status": status,
                    "report_id": polled_day[-1],
                    "download_url": _DOWNLOAD_URL if status == "DONE" else None,
                }
            )
        return _file_response({"value": {"results": (rows_by_day or {}).get(polled_day[-1], [])}})

    mock_session.return_value.post.side_effect = post
    mock_session.return_value.get.side_effect = get
    return created


def _resume_manager(state: SingularResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = state is not None
    manager.load_state.return_value = state
    return manager


def _report_batches(
    manager: mock.MagicMock | None = None, last_value: Any = None, query: SingularReportQuery = _QUERY
) -> list[list[dict[str, Any]]]:
    response = singular_source(
        api_key=_API_KEY,
        api_version="v2.0",
        endpoint="daily_report",
        query=query,
        logger=mock.MagicMock(),
        resumable_source_manager=manager or _resume_manager(),
        db_incremental_field_last_value=last_value,
    )
    return list(cast(Iterable[list[dict[str, Any]]], response.items()))


@mock.patch(f"{_MODULE}.time.sleep")
@mock.patch(f"{_MODULE}.make_tracked_session")
class TestDailyReport:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel(_NOW, tick=False):
            yield

    def test_requests_one_report_per_day_in_date_order(self, mock_session, _sleep):
        created = _wire(
            mock_session,
            rows_by_day={
                "2026-06-28": [{"app": "Invented App", "source": "Example Ads", "adn_cost": 1.5}],
                "2026-06-30": [{"app": "Invented App", "source": "Example Ads", "adn_cost": 2.5}],
            },
        )
        manager = _resume_manager()

        batches = _report_batches(manager, last_value="2026-06-28")

        assert [(body["start_date"], body["end_date"]) for body in created] == [
            ("2026-06-28", "2026-06-28"),
            ("2026-06-29", "2026-06-29"),
            ("2026-06-30", "2026-06-30"),
        ]
        assert created[0] == {
            "dimensions": "app,source",
            "metrics": "adn_cost",
            "start_date": "2026-06-28",
            "end_date": "2026-06-28",
            "time_breakdown": "day",
            "format": "json",
        }
        assert [row["date"] for batch in batches for row in batch] == [dt.date(2026, 6, 28), dt.date(2026, 6, 30)]
        assert [call.args[0].next_date for call in manager.save_state.call_args_list] == [
            "2026-06-29",
            "2026-06-30",
            "2026-07-01",
        ]

    def test_api_key_travels_in_a_header_and_never_in_a_url(self, mock_session, _sleep):
        _wire(mock_session)

        _report_batches(last_value="2026-06-30")

        assert mock_session.call_args_list[0].kwargs["headers"] == {"Authorization": _API_KEY}
        session = mock_session.return_value
        for call in [*session.post.call_args_list, *session.get.call_args_list]:
            assert _API_KEY not in call.args[0]
            assert _API_KEY not in json.dumps(call.kwargs.get("params") or {})

    def test_cohort_fields_are_sent_only_when_set(self, mock_session, _sleep):
        created = _wire(mock_session)
        query = SingularReportQuery(
            dimensions=("app",), metrics=("adn_cost",), cohort_metrics=("revenue",), cohort_periods=("7d", "30d")
        )

        _report_batches(last_value="2026-06-30", query=query)

        assert created[0]["cohort_metrics"] == "revenue"
        assert created[0]["cohort_periods"] == "7d,30d"

    def test_retried_run_continues_from_the_saved_day(self, mock_session, _sleep):
        created = _wire(mock_session)

        _report_batches(_resume_manager(SingularResumeConfig(next_date="2026-06-29")), last_value="2026-06-01")

        assert [body["start_date"] for body in created] == ["2026-06-29", "2026-06-30"]

    def test_polls_until_done_and_reaches_a_safe_point_on_each_wait(self, mock_session, sleep):
        _wire(
            mock_session,
            rows_by_day={"2026-06-30": [{"app": "Invented App", "source": "Example Ads"}]},
            poll_statuses=["QUEUED", "STARTED", "DONE"],
        )
        manager = _resume_manager()

        batches = _report_batches(manager, last_value="2026-06-30")

        assert len(batches) == 1
        assert sleep.call_count == 2
        assert manager.safe_point.call_count == 2

    def test_report_that_never_finishes_stops_after_the_polling_budget(self, mock_session, _sleep):
        _wire(mock_session, poll_statuses=["STARTED"])

        with pytest.raises(SingularRetryableError, match="still STARTED"):
            _report_batches(last_value="2026-06-30")

        polls = [c for c in mock_session.return_value.get.call_args_list if c.args[0].endswith("/get_report_status")]
        assert len(polls) == REPORT_POLL_MAX_ATTEMPTS

    def test_failed_report_is_non_retryable_and_keeps_singulars_reason(self, mock_session, _sleep):
        _wire(mock_session, poll_statuses=["FAILED"])

        with pytest.raises(SingularNonRetryableError, match=REPORT_FAILED_ERROR) as raised:
            _report_batches(last_value="2026-06-30")

        assert "2026-06-30" in str(raised.value)
        assert error_message_matches(str(raised.value), SingularSource().get_non_retryable_errors())

    @pytest.mark.parametrize(
        "status, vendor_message, expected_prefix",
        [
            (401, "An invalid API Key was given.", AUTH_ERROR),
            (
                401,
                "The provided API key has been previously deactivated. Please contact your administrator.",
                AUTH_ERROR,
            ),
            (403, "The provided API key does not have permissions to view the field: adn_cost", ACCESS_ERROR),
            (400, "The request contains invalid dimensions: not_a_dimension", REQUEST_ERROR),
            (400, "The request contains invalid metrics: not_a_metric", REQUEST_ERROR),
            (400, "We could not find cohort periods for the following cohort metrics: revenue.", REQUEST_ERROR),
        ],
    )
    def test_rejected_report_request_is_non_retryable_and_quotes_singular(
        self, mock_session, _sleep, status, vendor_message, expected_prefix
    ):
        _wire(mock_session, create_responses=[_response(status, vendor_message)])

        with pytest.raises(SingularNonRetryableError) as raised:
            _report_batches(last_value="2026-06-30")

        message = str(raised.value)
        assert message.startswith(expected_prefix)
        assert vendor_message in message
        assert error_message_matches(message, SingularSource().get_non_retryable_errors())
        assert mock_session.return_value.post.call_count == 1

    @pytest.mark.parametrize(
        "status, vendor_message, expected_error",
        [
            (429, "Too many requests. Only 10 requests per second is currently allowed.", SingularNonRetryableError),
            (500, "The request has failed due to an internal error.", SingularRetryableError),
        ],
    )
    def test_throttled_or_failing_report_request_stops_after_bounded_retries(
        self, mock_session, _sleep, status, vendor_message, expected_error
    ):
        _wire(mock_session, create_responses=[_response(status, vendor_message)] * CREATE_MAX_ATTEMPTS)

        with pytest.raises(expected_error) as raised:
            _report_batches(last_value="2026-06-30")

        assert mock_session.return_value.post.call_count == CREATE_MAX_ATTEMPTS
        source = SingularSource()
        assert error_message_matches(str(raised.value), source.get_non_retryable_errors()) is (status == 429)
        assert error_message_matches(str(raised.value), source.get_retryable_errors()) is (status != 429)
        if status == 429:
            assert str(raised.value).startswith(QUOTA_ERROR)
            assert vendor_message in str(raised.value)

    def test_success_status_with_a_non_json_body_is_retryable(self, mock_session, _sleep):
        page = _response()
        page.json.side_effect = ValueError("not JSON")
        mock_session.return_value.post.side_effect = None
        mock_session.return_value.post.return_value = page

        with pytest.raises(SingularRetryableError) as raised:
            _report_batches(last_value="2026-06-30")

        source = SingularSource()
        assert error_message_matches(str(raised.value), source.get_retryable_errors())
        assert not error_message_matches(str(raised.value), source.get_non_retryable_errors())

    def test_report_request_recovers_from_a_short_throttle(self, mock_session, _sleep):
        created = _wire(mock_session, create_responses=[_response(429, "Too many requests."), _response(500)])

        _report_batches(last_value="2026-06-30")

        assert [body["start_date"] for body in created] == ["2026-06-30"]

    def test_failed_download_does_not_leak_the_presigned_url(self, mock_session, _sleep):
        _wire(mock_session)
        status_get = mock_session.return_value.get.side_effect

        def get(url: str, **kwargs: Any) -> mock.MagicMock:
            return _file_response(None, status=403) if url == _DOWNLOAD_URL else status_get(url, **kwargs)

        mock_session.return_value.get.side_effect = get

        with pytest.raises(SingularRetryableError) as raised:
            _report_batches(last_value="2026-06-30")

        assert "invented-signature" not in str(raised.value)
        assert not error_message_matches(str(raised.value), SingularSource().get_non_retryable_errors())


class TestReportShaping:
    @pytest.mark.parametrize(
        "last_value, history_start, expected",
        [
            ("2026-06-23", None, dt.date(2026, 6, 23)),
            (dt.date(2026, 6, 23), None, dt.date(2026, 6, 23)),
            (dt.datetime(2026, 6, 23, 8, 0, tzinfo=dt.UTC), None, dt.date(2026, 6, 23)),
            ("2026-06-23", dt.datetime(2026, 1, 1, tzinfo=dt.UTC), dt.date(2026, 6, 23)),
            (None, dt.datetime(2026, 5, 2, 9, 30, tzinfo=dt.UTC), dt.date(2026, 5, 2)),
            (None, None, dt.date(2026, 6, 30) - dt.timedelta(days=HISTORY_DAYS)),
        ],
    )
    def test_report_start_date(self, last_value, history_start, expected):
        assert report_start_date(dt.date(2026, 6, 30), last_value, history_start) == expected

    @pytest.mark.parametrize(
        "body",
        [
            [{"app": "Invented App"}],
            {"results": [{"app": "Invented App"}]},
            {"status": 0, "substatus": 0, "value": {"results": [{"app": "Invented App"}]}},
        ],
    )
    def test_report_rows_accepts_each_known_file_shape(self, body):
        assert report_rows(body) == [{"app": "Invented App"}]

    @pytest.mark.parametrize("body", [{"value": "not rows"}, {"value": {"rows": []}}, "text", None])
    def test_report_rows_rejects_an_unrecognized_file(self, body):
        with pytest.raises(ValueError):
            report_rows(body)

    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, ("app", "source")),
            ("  ", ("app", "source")),
            (" os , country_field,,os ", ("os", "country_field")),
        ],
    )
    def test_parse_field_list(self, value, expected):
        assert parse_field_list(value, ("app", "source")) == expected

    def test_report_primary_key_is_the_date_plus_the_chosen_dimensions(self):
        response = singular_source(
            api_key=_API_KEY,
            api_version="v2.0",
            endpoint="daily_report",
            query=SingularReportQuery(dimensions=("app", "os", "invented_custom_dimension_id"), metrics=("adn_cost",)),
            logger=mock.MagicMock(),
            resumable_source_manager=_resume_manager(),
        )

        assert response.primary_keys == ["date", "app", "os", "invented_custom_dimension_id"]


@mock.patch(f"{_MODULE}.make_tracked_session")
class TestLookups:
    @pytest.mark.parametrize(
        "endpoint, value, expected_rows",
        [
            (
                "custom_dimensions",
                {"custom_dimensions": [{"display_name": "Channel", "id": "invented-dimension-1"}]},
                [[{"display_name": "Channel", "id": "invented-dimension-1"}]],
            ),
            (
                "cohort_metrics",
                {"metrics": [{"display_name": "Revenue", "name": "revenue"}], "periods": ["7d", "30d"]},
                [[{"display_name": "Revenue", "name": "revenue"}]],
            ),
            (
                "conversion_metrics",
                {"metrics": [{"display_name": "Sign up", "name": "invented-event-1"}]},
                [[{"display_name": "Sign up", "name": "invented-event-1"}]],
            ),
            ("custom_dimensions", {"custom_dimensions": []}, []),
        ],
    )
    def test_lookup_reads_its_list_from_one_request(self, mock_session, endpoint, value, expected_rows):
        mock_session.return_value.get.return_value = _response(value=value)

        response = singular_source(
            api_key=_API_KEY,
            api_version="v2.0",
            endpoint=endpoint,
            query=_QUERY,
            logger=mock.MagicMock(),
            resumable_source_manager=_resume_manager(),
        )

        assert list(cast(Iterable[Any], response.items())) == expected_rows
        assert response.primary_keys == [LOOKUPS[endpoint].primary_key]
        mock_session.return_value.get.assert_called_once()
        assert mock_session.return_value.get.call_args.args[0] == f"https://api.singular.net{LOOKUPS[endpoint].path}"


@mock.patch(f"{_MODULE}.make_tracked_session")
class TestValidateCredentials:
    @pytest.mark.parametrize(
        "response, expected_valid, expected_message_part",
        [
            (_response(value={"custom_dimensions": []}), True, None),
            (_response(401, "An invalid API Key was given."), False, AUTH_ERROR),
            (_response(403, "The request is denied access. Please contact your administrator."), False, ACCESS_ERROR),
            (requests.ConnectionError("connection refused"), False, "Could not reach Singular"),
        ],
    )
    def test_validate_credentials(self, mock_session, response, expected_valid, expected_message_part):
        mock_session.return_value.get.side_effect = [response]

        is_valid, message = validate_credentials(_API_KEY, "v2.0")

        assert is_valid is expected_valid
        if expected_message_part is None:
            assert message is None
        else:
            assert message is not None and expected_message_part in message
