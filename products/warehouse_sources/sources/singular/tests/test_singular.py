import json
import datetime as dt
from collections.abc import Callable, Iterable
from typing import Any, cast
from urllib.parse import parse_qsl

import pytest
import time_machine
from unittest import mock

from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    error_message_matches,
    scripted_network,
)
from products.warehouse_sources.sources.singular._config import SingularSourceConfig
from products.warehouse_sources.sources.singular.settings import (
    AD_MONETIZATION_REPORT,
    FIXED_REPORTS,
    HISTORY_DAYS,
    LOOKUPS,
    SKADNETWORK_RAW_REPORT,
    SKADNETWORK_REPORT,
)
from products.warehouse_sources.sources.singular.singular import (
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
    report_rows,
    report_start_date,
    singular_source,
    validate_credentials,
)
from products.warehouse_sources.sources.singular.source import SingularSource

_MODULE = "products.warehouse_sources.sources.singular.singular"
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


def _envelope(status: int = 200, value: Any = None) -> ScriptedResponse:
    return ScriptedResponse(
        status=status, json={"status": 0 if status < 400 else status, "substatus": 0, "value": value}
    )


def _script(
    rows_by_day: dict[str, list[dict[str, Any]]] | None = None,
    poll_statuses: list[str] | None = None,
    create_responses: list[ScriptedResponse] | None = None,
    download_response: ScriptedResponse | None = None,
) -> tuple[Callable[[RecordedRequest], ScriptedResponse], list[dict[str, str]]]:
    created: list[dict[str, str]] = []
    statuses = list(poll_statuses or ["DONE"])
    queued = list(create_responses or [])
    polled_day: list[str] = []

    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.method == "POST":
            if queued:
                response = queued.pop(0)
                if response.status >= 400:
                    return response
            body = dict(parse_qsl((request.body or b"").decode()))
            created.append(body)
            return _envelope(value={"report_id": body["start_date"]})
        if request.path.endswith("/get_report_status"):
            polled_day.append(request.param("report_id") or "")
            status = statuses.pop(0) if len(statuses) > 1 else statuses[0]
            return _envelope(
                value={
                    "status": status,
                    "report_id": polled_day[-1],
                    "download_url": _DOWNLOAD_URL if status == "DONE" else None,
                }
            )
        if download_response is not None:
            return download_response
        return ScriptedResponse(json={"value": {"results": (rows_by_day or {}).get(polled_day[-1], [])}})

    return respond, created


def _run_report(
    script: Callable[[RecordedRequest], ScriptedResponse],
    last_value: Any = None,
    query: SingularReportQuery = _QUERY,
    resume_state: SingularResumeConfig | None = None,
) -> DriveResult:
    config = SingularSourceConfig(
        api_key=_API_KEY,
        dimensions=",".join(query.dimensions),
        metrics=",".join(query.metrics),
        cohort_metrics=",".join(query.cohort_metrics) or None,
        cohort_periods=",".join(query.cohort_periods) or None,
    )
    return SourceDriver(SingularSource(), config).run(
        "daily_report",
        script,
        resume_state=resume_state,
        incremental_field="date" if last_value is not None else None,
        db_incremental_field_last_value=last_value,
    )


def _raised(result: DriveResult, expected: type[BaseException]) -> BaseException:
    assert isinstance(result.raised, expected), result.raised
    return result.raised


def _post_count(result: DriveResult) -> int:
    return len([request for request in result.requests if request.method == "POST"])


def _poll_count(result: DriveResult) -> int:
    return len([path for path in result.paths if path.endswith("/get_report_status")])


@pytest.fixture
def _frozen_clock():
    with time_machine.travel(_NOW, tick=False):
        yield


@pytest.mark.usefixtures("_frozen_clock")
class TestDailyReport:
    def test_api_key_travels_in_a_header_and_never_in_a_url(self):
        script, _ = _script()

        result = _run_report(script, last_value="2026-06-30")

        assert result.session_options[0]["headers"] == {"Authorization": _API_KEY}
        assert result.requests[0].headers["authorization"] == _API_KEY
        for request in result.requests:
            assert _API_KEY not in request.url
            assert _API_KEY not in (request.body or b"").decode()

    def test_cohort_fields_are_sent_only_when_set(self):
        script, created = _script()
        query = SingularReportQuery(
            dimensions=("app",), metrics=("adn_cost",), cohort_metrics=("revenue",), cohort_periods=("7d", "30d")
        )

        _run_report(script, last_value="2026-06-30", query=query)

        assert created[0]["cohort_metrics"] == "revenue"
        assert created[0]["cohort_periods"] == "7d,30d"

    def test_retried_run_continues_from_the_saved_day(self):
        script, created = _script()

        _run_report(script, last_value="2026-06-01", resume_state=SingularResumeConfig(next_date="2026-06-29"))

        assert [body["start_date"] for body in created] == ["2026-06-29", "2026-06-30"]

    def test_report_that_never_finishes_stops_after_the_polling_budget(self):
        script, _ = _script(poll_statuses=["STARTED"])

        result = _run_report(script, last_value="2026-06-30")

        error = _raised(result, SingularRetryableError)
        assert "still STARTED" in str(error)
        assert _poll_count(result) == REPORT_POLL_MAX_ATTEMPTS

    def test_failed_report_is_non_retryable_and_keeps_singulars_reason(self):
        script, _ = _script(poll_statuses=["FAILED"])

        result = _run_report(script, last_value="2026-06-30")

        error = _raised(result, SingularNonRetryableError)
        assert REPORT_FAILED_ERROR in str(error)
        assert "2026-06-30" in str(error)
        assert error_message_matches(str(error), SingularSource().get_non_retryable_errors())

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
        self, status, vendor_message, expected_prefix
    ):
        script, _ = _script(create_responses=[_envelope(status, vendor_message)])

        result = _run_report(script, last_value="2026-06-30")

        message = str(_raised(result, SingularNonRetryableError))
        assert message.startswith(expected_prefix)
        assert vendor_message in message
        assert error_message_matches(message, SingularSource().get_non_retryable_errors())
        assert _post_count(result) == 1

    @pytest.mark.parametrize(
        "status, vendor_message, expected_error",
        [
            (429, "Too many requests. Only 10 requests per second is currently allowed.", SingularNonRetryableError),
            (500, "The request has failed due to an internal error.", SingularRetryableError),
        ],
    )
    def test_throttled_or_failing_report_request_stops_after_bounded_retries(
        self, status, vendor_message, expected_error
    ):
        script, _ = _script(create_responses=[_envelope(status, vendor_message)] * CREATE_MAX_ATTEMPTS)

        result = _run_report(script, last_value="2026-06-30")

        error = _raised(result, expected_error)
        assert _post_count(result) == CREATE_MAX_ATTEMPTS
        source = SingularSource()
        assert error_message_matches(str(error), source.get_non_retryable_errors()) is (status == 429)
        assert error_message_matches(str(error), source.get_retryable_errors()) is (status != 429)
        if status == 429:
            assert str(error).startswith(QUOTA_ERROR)
            assert vendor_message in str(error)

    def test_success_status_with_a_non_json_body_is_retryable(self):
        result = _run_report(always(ScriptedResponse(body=b"<html>maintenance</html>")), last_value="2026-06-30")

        error = _raised(result, SingularRetryableError)
        source = SingularSource()
        assert error_message_matches(str(error), source.get_retryable_errors())
        assert not error_message_matches(str(error), source.get_non_retryable_errors())

    def test_report_request_recovers_from_a_short_throttle(self):
        script, created = _script(create_responses=[_envelope(429, "Too many requests."), _envelope(500)])

        _run_report(script, last_value="2026-06-30")

        assert [body["start_date"] for body in created] == ["2026-06-30"]

    def test_failed_download_does_not_leak_the_presigned_url(self):
        script, _ = _script(download_response=ScriptedResponse(status=403))

        result = _run_report(script, last_value="2026-06-30")

        error = _raised(result, SingularRetryableError)
        assert "invented-signature" not in str(error)
        assert not error_message_matches(str(error), SingularSource().get_non_retryable_errors())


@mock.patch(f"{_MODULE}.time.sleep")
@mock.patch(f"{_MODULE}.make_tracked_session")
@pytest.mark.usefixtures("_frozen_clock")
def test_polls_until_done_and_reaches_a_safe_point_on_each_wait(mock_session, sleep):
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

    @pytest.mark.parametrize("body", [{"value": "not rows"}, {"value": {"rows": []}}, "text", None])
    def test_report_rows_rejects_an_unrecognized_file(self, body):
        with pytest.raises(ValueError):
            report_rows(body)


def _run_fixed_report(
    endpoint: str, script: Callable[[RecordedRequest], ScriptedResponse], last_value: str
) -> DriveResult:
    # The daily_report settings must not leak into the fixed reports.
    config = SingularSourceConfig(api_key=_API_KEY, dimensions="invented_dimension", metrics="invented_metric")
    return SourceDriver(SingularSource(), config).run(
        endpoint, script, incremental_field="date", db_incremental_field_last_value=last_value
    )


@pytest.mark.usefixtures("_frozen_clock")
class TestFixedReports:
    @pytest.mark.parametrize(
        "endpoint, path",
        [
            (SKADNETWORK_REPORT, "create_async_skadnetwork_report"),
            (SKADNETWORK_RAW_REPORT, "create_async_skadnetwork_raw_report"),
        ],
    )
    def test_skadnetwork_report_creates_one_report_per_day_with_its_own_fields(self, endpoint, path):
        report = FIXED_REPORTS[endpoint]
        script, created = _script(rows_by_day={"2026-06-30": [{"app": "Invented App", "skan_installs": 3}]})

        result = _run_fixed_report(endpoint, script, last_value="2026-06-29")

        assert result.raised is None
        assert [request.path for request in result.requests if request.method == "POST"] == [f"/api/v2.0/{path}"] * 2
        assert [body["start_date"] for body in created] == ["2026-06-29", "2026-06-30"]
        for body in created:
            assert body["end_date"] == body["start_date"]
            assert body["dimensions"] == ",".join(report.dimensions)
            assert body["metrics"] == ",".join(report.metrics)
            assert body["time_breakdown"] == "day"
            assert body["skadnetwork_date_type"] == "skan_postback_date"
        assert result.response is not None
        assert result.response.primary_keys == ["date", *report.dimensions]
        assert result.saved_states[-1] == SingularResumeConfig(next_date="2026-07-01")

    def test_ad_monetization_report_reads_each_day_with_one_get_and_commits_empty_days(self):
        report = FIXED_REPORTS[AD_MONETIZATION_REPORT]

        def respond(request: RecordedRequest) -> ScriptedResponse:
            rows = [{"app": "Invented App", "ad_revenue": 1.5}] if request.param("start_date") == "2026-06-30" else []
            return _envelope(value={"results": rows})

        result = _run_fixed_report(AD_MONETIZATION_REPORT, respond, last_value="2026-06-27")

        assert result.raised is None
        days = ["2026-06-27", "2026-06-28", "2026-06-29", "2026-06-30"]
        assert result.paths == ["/api/v2.0/admonetization/reporting"] * len(days)
        assert result.params("start_date") == days
        assert result.params("end_date") == days
        assert result.params("time_breakdown") == ["day"] * len(days)
        assert result.params("metrics") == [",".join(report.metrics)] * len(days)
        assert result.params("skadnetwork_date_type") == [None] * len(days)
        # Each empty day reaches a safe point, so its cursor commits without a yield.
        assert result.committed_states == [
            SingularResumeConfig(next_date=day) for day in ("2026-06-28", "2026-06-29", "2026-06-30")
        ]
        assert result.saved_states[-1] == SingularResumeConfig(next_date="2026-07-01")

    @pytest.mark.parametrize(
        "row, expected",
        [
            (
                {"app": "Invented App", "source": None, "ad_revenue": 1.5},
                {
                    "app": "Invented App",
                    "source": "",
                    "os": "",
                    "ad_country": "",
                    "ad_type_name": "",
                    "ad_revenue": 1.5,
                    "date": dt.date(2026, 6, 30),
                },
            ),
            (
                {
                    "app": "Invented App",
                    "source": "Example Network",
                    "os": "iOS",
                    "ad_country": "USA",
                    "ad_type_name": "Banner",
                    "ad_revenue": None,
                },
                {
                    "app": "Invented App",
                    "source": "Example Network",
                    "os": "iOS",
                    "ad_country": "USA",
                    "ad_type_name": "Banner",
                    "ad_revenue": None,
                    "date": dt.date(2026, 6, 30),
                },
            ),
        ],
    )
    def test_report_rows_get_the_date_and_no_null_key_dimension(self, row, expected):
        result = _run_fixed_report(
            AD_MONETIZATION_REPORT, always(_envelope(value={"results": [row]})), last_value="2026-06-30"
        )

        assert result.rows == [expected]

    def test_skadnetwork_report_on_an_account_without_skadnetwork_is_non_retryable(self):
        vendor_message = "There is no SKAdNetwork data configured."
        script, _ = _script(create_responses=[_envelope(400, vendor_message)])

        result = _run_fixed_report(SKADNETWORK_REPORT, script, last_value="2026-06-30")

        message = str(_raised(result, SingularNonRetryableError))
        assert message.startswith(REQUEST_ERROR)
        assert vendor_message in message
        assert error_message_matches(message, SingularSource().get_non_retryable_errors())


class TestFilters:
    @pytest.mark.parametrize(
        "value, expected_rows",
        [
            (
                {
                    "dimensions": [
                        {
                            "name": "os",
                            "display_name": "OS",
                            "values": [{"name": 4, "display_name": "Android"}, {"name": 1, "display_name": "iOS"}],
                        },
                        {
                            "name": "source",
                            "display_name": "Source",
                            "values": [{"name": "example_ads", "display_name": "Example Ads"}],
                        },
                    ]
                },
                [
                    {"dimension": "os", "dimension_display_name": "OS", "name": "4", "display_name": "Android"},
                    {"dimension": "os", "dimension_display_name": "OS", "name": "1", "display_name": "iOS"},
                    {
                        "dimension": "source",
                        "dimension_display_name": "Source",
                        "name": "example_ads",
                        "display_name": "Example Ads",
                    },
                ],
            ),
            ({"dimensions": [{"name": "app", "display_name": "App", "values": []}]}, []),
            ({"dimensions": []}, []),
            ({}, []),
        ],
    )
    def test_filters_has_one_row_per_dimension_value(self, value, expected_rows):
        result = SourceDriver(SingularSource(), SingularSourceConfig(api_key=_API_KEY)).run(
            "filters", [_envelope(value=value)]
        )

        assert result.raised is None
        assert result.rows == expected_rows
        assert result.urls == ["https://api.singular.net/api/v2.0/reporting/filters"]
        assert result.response is not None
        assert result.response.primary_keys == ["dimension", "name"]


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
    def test_lookup_reads_its_list_from_one_request(self, endpoint, value, expected_rows):
        result = SourceDriver(SingularSource(), SingularSourceConfig(api_key=_API_KEY)).run(
            endpoint, [_envelope(value=value)]
        )

        assert result.items == expected_rows
        assert result.response is not None
        assert result.response.primary_keys == [LOOKUPS[endpoint].primary_key]
        assert result.urls == [f"https://api.singular.net{LOOKUPS[endpoint].path}"]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "response, expected_valid, expected_message_part",
        [
            (_envelope(value={"custom_dimensions": []}), True, None),
        ],
    )
    def test_validate_credentials(self, response, expected_valid, expected_message_part):
        with scripted_network(always(response)):
            is_valid, message = validate_credentials(_API_KEY, "v2.0")

        assert is_valid is expected_valid
        if expected_message_part is None:
            assert message is None
        else:
            assert message is not None and expected_message_part in message
