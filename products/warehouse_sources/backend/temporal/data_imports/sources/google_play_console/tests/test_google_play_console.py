import datetime as dt
import functools
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

import jwt
import requests
import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.google_play_console import google_play_console
from products.warehouse_sources.backend.temporal.data_imports.sources.google_play_console.google_play_console import (
    DEFAULT_TOKEN_URI,
    JWT_BEARER_GRANT,
    PLAY_REPORTING_SCOPE,
    GooglePlayConsoleAuthError,
    GooglePlayConsoleClient,
    GooglePlayConsoleResumeConfig,
    ServiceAccountKey,
    _batch_by_date,
    _coerce_datetime,
    _dimension_value,
    _interval_params,
    _iter_list_rows,
    _iter_metric_set_rows,
    _list_row_to_dict,
    _metric_row_to_dict,
    _metric_value,
    _normalize_private_key,
    google_play_console_source,
    parse_package_names,
    resolve_history_start,
    resolve_package_names,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_play_console.settings import (
    ENDPOINTS,
    LIST_ENDPOINTS,
    METRIC_SETS,
    PRIMARY_KEYS,
)

MODULE = google_play_console.__name__
TODAY = dt.date(2024, 3, 31)


@functools.cache
def _rsa_key_pair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def _key(private_key: str | None = None) -> ServiceAccountKey:
    return ServiceAccountKey(
        client_email="reporting@example.iam.gserviceaccount.com",
        private_key=private_key if private_key is not None else _rsa_key_pair()[0],
        private_key_id="key-1",
        token_uri=DEFAULT_TOKEN_URI,
    )


def _response(status_code: int, payload: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.text = text
    response.json.return_value = payload if payload is not None else {}
    if not response.ok:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} Client Error: for url: https://playdeveloperreporting.googleapis.com", response=response
        )
    return response


def _token_response() -> mock.MagicMock:
    return _response(200, {"access_token": "ya29.token", "expires_in": 3600})


def _client(session: mock.MagicMock, private_key: str | None = None) -> GooglePlayConsoleClient:
    with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
        return GooglePlayConsoleClient(_key(private_key), "v1beta1", structlog.get_logger())


class FakeResumableSourceManager(ResumableSourceManager[GooglePlayConsoleResumeConfig]):
    def __init__(self, state: GooglePlayConsoleResumeConfig | None = None) -> None:
        self.saved: list[GooglePlayConsoleResumeConfig] = []
        self._state = state

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> GooglePlayConsoleResumeConfig | None:
        return self._state

    def save_state(self, data: GooglePlayConsoleResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self._state = None


def _manager(state: GooglePlayConsoleResumeConfig | None = None) -> FakeResumableSourceManager:
    return FakeResumableSourceManager(state)


def _metric_row(day: dt.date, version: int, rate: str, dimension: str = "versionCode") -> dict[str, Any]:
    return {
        "startTime": {"year": day.year, "month": day.month, "day": day.day},
        "endTime": {"year": day.year, "month": day.month, "day": day.day + 1},
        "dimensions": [{"dimension": dimension, "int64Value": str(version), "valueLabel": f"v{version}"}],
        "metrics": [{"metric": "crashRate", "decimalValue": {"value": rate}}],
    }


def _freshness(day: dt.date) -> dict[str, Any]:
    return {
        "freshnessInfo": {
            "freshnesses": [
                {"aggregationPeriod": "HOURLY", "latestEndTime": {"year": 2024, "month": 3, "day": 30, "hours": 5}},
                {
                    "aggregationPeriod": "DAILY",
                    "latestEndTime": {"year": day.year, "month": day.month, "day": day.day},
                },
            ]
        }
    }


@pytest.mark.parametrize(
    "raw,expected_start",
    [
        ("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----", "-----BEGIN PRIVATE KEY-----\nabc"),
        ("-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----", "-----BEGIN PRIVATE KEY-----\nabc"),
    ],
)
def test_normalize_private_key_restores_newlines(raw: str, expected_start: str) -> None:
    normalized = _normalize_private_key(raw)
    assert normalized.startswith(expected_start)
    assert normalized.endswith("\n")
    assert "\\n" not in normalized


def test_mints_a_signed_service_account_assertion() -> None:
    session = mock.MagicMock()
    session.post.return_value = _token_response()
    session.request.return_value = _response(200, {"apps": []})
    client = _client(session)

    client.request("GET", "apps:search")

    assert session.post.call_args.args[0] == DEFAULT_TOKEN_URI
    posted = session.post.call_args.kwargs["data"]
    assert posted["grant_type"] == JWT_BEARER_GRANT

    claims = jwt.decode(posted["assertion"], _rsa_key_pair()[1], algorithms=["RS256"], audience=DEFAULT_TOKEN_URI)
    assert claims["iss"] == "reporting@example.iam.gserviceaccount.com"
    assert claims["scope"] == PLAY_REPORTING_SCOPE
    assert claims["exp"] - claims["iat"] == 3600
    assert jwt.get_unverified_header(posted["assertion"])["kid"] == "key-1"
    assert session.request.call_args.kwargs["headers"]["Authorization"] == "Bearer ya29.token"


def test_ignores_the_uploaded_token_uri_and_posts_to_google() -> None:
    session = mock.MagicMock()
    session.post.return_value = _token_response()
    session.request.return_value = _response(200, {"apps": []})
    malicious_key = ServiceAccountKey(
        client_email="reporting@example.iam.gserviceaccount.com",
        private_key=_rsa_key_pair()[0],
        private_key_id="key-1",
        token_uri="http://169.254.169.254/latest/meta-data/",
    )
    with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
        client = GooglePlayConsoleClient(malicious_key, "v1beta1", structlog.get_logger())

    client.request("GET", "apps:search")

    assert session.post.call_args.args[0] == DEFAULT_TOKEN_URI
    claims = jwt.decode(
        session.post.call_args.kwargs["data"]["assertion"],
        _rsa_key_pair()[1],
        algorithms=["RS256"],
        audience=DEFAULT_TOKEN_URI,
    )
    assert claims["aud"] == DEFAULT_TOKEN_URI


def test_reuses_the_access_token_until_it_expires() -> None:
    session = mock.MagicMock()
    session.post.return_value = _token_response()
    session.request.return_value = _response(200, {"apps": []})
    client = _client(session)

    client.request("GET", "apps:search")
    client.request("GET", "apps:search")

    assert session.post.call_count == 1


def test_remints_the_access_token_when_a_request_comes_back_unauthorized() -> None:
    session = mock.MagicMock()
    session.post.return_value = _token_response()
    session.request.side_effect = [_response(401, text="expired"), _response(200, {"apps": [{"packageName": "a"}]})]
    client = _client(session)

    assert client.request("GET", "apps:search") == {"apps": [{"packageName": "a"}]}
    assert session.post.call_count == 2
    assert session.request.call_count == 2


def test_raises_a_permanent_error_when_google_rejects_the_key() -> None:
    session = mock.MagicMock()
    session.post.return_value = _response(400, {"error": "invalid_grant"}, text="invalid_grant")
    client = _client(session)

    with pytest.raises(GooglePlayConsoleAuthError, match="Google rejected the service account key"):
        client.request("GET", "apps:search")


def test_raises_a_permanent_error_when_the_key_cannot_sign() -> None:
    session = mock.MagicMock()
    client = _client(session, private_key="not-a-pem-key")

    with pytest.raises(GooglePlayConsoleAuthError, match="Could not sign a token"):
        client.request("GET", "apps:search")


def test_non_2xx_api_responses_raise_for_status() -> None:
    session = mock.MagicMock()
    session.post.return_value = _token_response()
    session.request.return_value = _response(403, text="forbidden")
    client = _client(session)

    with pytest.raises(requests.HTTPError):
        client.request("GET", "apps/com.example/anomalies")


def test_list_apps_follows_pagination() -> None:
    session = mock.MagicMock()
    session.post.return_value = _token_response()
    session.request.side_effect = [
        _response(200, {"apps": [{"packageName": "com.b"}], "nextPageToken": "t1"}),
        _response(200, {"apps": [{"packageName": "com.a"}]}),
    ]
    client = _client(session)

    assert [app["packageName"] for app in client.list_apps()] == ["com.b", "com.a"]
    assert session.request.call_args_list[1].kwargs["params"]["pageToken"] == "t1"


def test_latest_available_date_converts_the_exclusive_freshness_bound_to_an_inclusive_day() -> None:
    # Play documents `latestEndTime` as already being the exclusive bound ready to reuse as
    # `timelineSpec.endTime` (one day past the last day with data) — not the last day itself.
    session = mock.MagicMock()
    session.post.return_value = _token_response()
    session.request.return_value = _response(200, _freshness(dt.date(2024, 3, 10)))
    client = _client(session)

    assert client.latest_available_date("com.example.app", "crashRateMetricSet") == dt.date(2024, 3, 9)


@pytest.mark.parametrize(
    "dimension,expected",
    [
        ({"dimension": "versionCode", "int64Value": "1234"}, 1234),
        ({"dimension": "versionCode", "int64Value": "not-a-number"}, None),
        ({"dimension": "reportType", "stringValue": "CRASH"}, "CRASH"),
        ({"dimension": "startType", "valueLabel": "Cold start"}, "Cold start"),
        ({"dimension": "startType"}, None),
    ],
)
def test_dimension_value_coercion(dimension: dict[str, Any], expected: Any) -> None:
    assert _dimension_value(dimension) == expected


@pytest.mark.parametrize(
    "metric,expected",
    [
        ({"metric": "crashRate", "decimalValue": {"value": "0.0125"}}, 0.0125),
        ({"metric": "distinctUsers", "int64Value": "42"}, 42.0),
        ({"metric": "crashRate", "doubleValue": 0.5}, 0.5),
        ({"metric": "crashRate", "decimalValue": {"value": "nonsense"}}, None),
        ({"metric": "crashRate"}, None),
    ],
)
def test_metric_value_is_always_a_float_or_null(metric: dict[str, Any], expected: Any) -> None:
    assert _metric_value(metric) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (
            {"year": 2024, "month": 3, "day": 2, "hours": 4, "minutes": 5, "seconds": 6},
            dt.datetime(2024, 3, 2, 4, 5, 6),
        ),
        ({"year": 2024, "month": 3, "day": 2}, dt.datetime(2024, 3, 2)),
        ("2024-03-02T04:05:06Z", dt.datetime(2024, 3, 2, 4, 5, 6)),
        ("2024-03-02T06:05:06+02:00", dt.datetime(2024, 3, 2, 4, 5, 6)),
        ("not a timestamp", None),
        ({"month": 3, "day": 2}, None),
        (None, None),
    ],
)
def test_timestamps_normalize_to_naive_utc(value: Any, expected: dt.datetime | None) -> None:
    assert _coerce_datetime(value) == expected


def test_metric_row_keeps_the_primary_key_columns_when_play_omits_a_dimension() -> None:
    row = _metric_row_to_dict(
        {
            "startTime": {"year": 2024, "month": 3, "day": 2},
            "endTime": {"year": 2024, "month": 3, "day": 3},
            "dimensions": [],
            "metrics": [{"metric": "slowStartRate", "decimalValue": {"value": "0.01"}}],
        },
        "com.example.app",
        METRIC_SETS["slow_start_rate"],
    )

    assert row["app"] == "com.example.app"
    assert row["date"] == dt.date(2024, 3, 2)
    assert row["startTime"] == dt.datetime(2024, 3, 2)
    assert row["endTime"] == dt.datetime(2024, 3, 3)
    assert row["startType"] is None
    assert row["versionCode"] is None
    assert row["slowStartRate"] == 0.01
    # Requested metrics are always columns, even when the row carries no value for them.
    assert row["distinctUsers"] is None


def test_metric_row_keeps_the_dimension_label_alongside_its_value() -> None:
    row = _metric_row_to_dict(
        _metric_row(dt.date(2024, 3, 2), 45, "0.02"), "com.example.app", METRIC_SETS["crash_rate"]
    )

    assert row["versionCode"] == 45
    assert row["versionCodeLabel"] == "v45"


def test_window_rows_leave_in_date_order_one_day_per_batch() -> None:
    rows: list[dict[str, Any]] = [
        {"date": dt.date(2024, 3, 3), "versionCode": 1},
        {"date": dt.date(2024, 3, 1), "versionCode": 1},
        {"date": dt.date(2024, 3, 3), "versionCode": 2},
        {"date": None, "versionCode": 3},
    ]

    batches = _batch_by_date(rows)

    assert [{row["date"] for row in batch} for batch in batches] == [
        {dt.date(2024, 3, 1)},
        {dt.date(2024, 3, 3)},
        {None},
    ]


def test_metric_set_windows_the_timeline_and_stops_at_the_freshness_date() -> None:
    endpoint = METRIC_SETS["crash_rate"]
    manager = _manager()
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def request(method: str, path: str, params: Any = None, body: Any = None) -> dict[str, Any]:
        calls.append((method, path, body))
        if path.endswith(":query"):
            return {"rows": [_metric_row(dt.date(2024, 3, 5), 12, "0.01")]}
        return _freshness(dt.date(2024, 3, 10))

    with mock.patch.object(GooglePlayConsoleClient, "request", side_effect=request):
        client = _client(mock.MagicMock())
        batches = list(
            _iter_metric_set_rows(
                client=client,
                endpoint=endpoint,
                package_names=["com.example.app"],
                history_start=dt.date(2024, 3, 1),
                manager=manager,
                resume=None,
            )
        )

    assert len(batches) == 1
    query_bodies = [body for method, path, body in calls if path.endswith(":query")]
    assert len(query_bodies) == 1
    timeline = query_bodies[0]["timelineSpec"] if query_bodies[0] else {}
    assert timeline["aggregationPeriod"] == "DAILY"
    assert timeline["startTime"] == {"year": 2024, "month": 3, "day": 1}
    # `_freshness` reports latestEndTime 2024-03-10, already Play's exclusive bound, so it is
    # requested as-is rather than being pushed a further day out.
    assert timeline["endTime"] == {"year": 2024, "month": 3, "day": 10}
    assert cast("dict[str, Any]", query_bodies[0])["dimensions"] == ["versionCode"]
    assert manager.saved == [GooglePlayConsoleResumeConfig(app="com.example.app", date="2024-03-10")]


def test_metric_set_skips_an_app_without_freshness() -> None:
    manager = _manager()
    calls: list[str] = []

    def request(method: str, path: str, params: Any = None, body: Any = None) -> dict[str, Any]:
        calls.append(path)
        # Empty freshness — the app has no queryable data for this metric set.
        return {}

    with mock.patch.object(GooglePlayConsoleClient, "request", side_effect=request):
        client = _client(mock.MagicMock())
        batches = list(
            _iter_metric_set_rows(
                client=client,
                endpoint=METRIC_SETS["anr_rate"],
                package_names=["com.example.app"],
                history_start=dt.date(2024, 3, 20),
                manager=manager,
                resume=None,
            )
        )

    # No freshness means no queryable data: the app is skipped rather than queried with a guessed
    # window Google rejects as an invalid timeframe. No `:query` is issued and nothing is yielded.
    assert batches == []
    assert not any(path.endswith(":query") for path in calls)


def test_metric_set_query_follows_pagination_until_the_token_runs_out() -> None:
    manager = _manager()
    payloads: list[dict[str, Any]] = [
        {"rows": [_metric_row(dt.date(2024, 3, 1), 1, "0.01")], "nextPageToken": "page-2"},
        {"rows": [_metric_row(dt.date(2024, 3, 2), 1, "0.02")]},
    ]
    bodies: list[dict[str, Any] | None] = []

    def request(method: str, path: str, params: Any = None, body: Any = None) -> dict[str, Any]:
        if not path.endswith(":query"):
            return _freshness(dt.date(2024, 3, 2))
        bodies.append(body)
        return payloads.pop(0)

    with mock.patch.object(GooglePlayConsoleClient, "request", side_effect=request):
        client = _client(mock.MagicMock())
        batches = list(
            _iter_metric_set_rows(
                client=client,
                endpoint=METRIC_SETS["crash_rate"],
                package_names=["com.example.app"],
                history_start=dt.date(2024, 3, 1),
                manager=manager,
                resume=None,
            )
        )

    assert len(bodies) == 2
    assert bodies[1] is not None and bodies[1]["pageToken"] == "page-2"
    assert [batch[0]["date"] for batch in batches] == [dt.date(2024, 3, 1), dt.date(2024, 3, 2)]


def test_metric_set_resume_skips_finished_apps_and_restarts_at_the_saved_window() -> None:
    manager = _manager(GooglePlayConsoleResumeConfig(app="com.b", date="2024-03-05"))
    queried: list[tuple[str, dict[str, int]]] = []

    def request(method: str, path: str, params: Any = None, body: Any = None) -> dict[str, Any]:
        if path.endswith(":query"):
            queried.append((path, body["timelineSpec"]["startTime"] if body else {}))
            return {"rows": []}
        return _freshness(dt.date(2024, 3, 6))

    with mock.patch.object(GooglePlayConsoleClient, "request", side_effect=request):
        client = _client(mock.MagicMock())
        list(
            _iter_metric_set_rows(
                client=client,
                endpoint=METRIC_SETS["crash_rate"],
                package_names=["com.a", "com.b", "com.c"],
                history_start=dt.date(2024, 3, 1),
                manager=manager,
                resume=GooglePlayConsoleResumeConfig(app="com.b", date="2024-03-05"),
            )
        )

    # com.a was finished before the interruption; com.b picks up at the saved date and com.c
    # starts from the beginning of the history window.
    assert [(path.split("/")[1], start) for path, start in queried] == [
        ("com.b", {"year": 2024, "month": 3, "day": 5}),
        ("com.c", {"year": 2024, "month": 3, "day": 1}),
    ]


def test_apps_endpoint_paginates_and_checkpoints_each_page() -> None:
    endpoint = LIST_ENDPOINTS["apps"]
    manager = _manager()
    payloads: list[dict[str, Any]] = [
        {"apps": [{"packageName": "com.a"}], "nextPageToken": "p2"},
        {"apps": [{"packageName": "com.b"}]},
    ]

    with mock.patch.object(GooglePlayConsoleClient, "request", side_effect=lambda *a, **kw: payloads.pop(0)):
        client = _client(mock.MagicMock())
        batches = list(
            _iter_list_rows(
                client=client,
                endpoint=endpoint,
                package_names=[],
                history_start=dt.date(2024, 3, 1),
                manager=manager,
                resume=None,
            )
        )

    assert [row["packageName"] for batch in batches for row in batch] == ["com.a", "com.b"]
    assert [state.page_token for state in manager.saved] == ["p2", None]
    # The app catalog is not per-app, so no package name is stamped onto its rows.
    assert "app" not in batches[0][0]


def test_error_reports_walk_one_day_at_a_time_with_an_interval_filter() -> None:
    endpoint = LIST_ENDPOINTS["error_reports"]
    manager = _manager()
    seen_params: list[dict[str, Any]] = []

    def request(method: str, path: str, params: Any = None, body: Any = None) -> dict[str, Any]:
        seen_params.append(params or {})
        return {"errorReports": [{"name": f"{path}/report-{len(seen_params)}", "eventTime": "2024-03-30T01:02:03Z"}]}

    with (
        mock.patch(f"{MODULE}._today", return_value=TODAY),
        mock.patch.object(GooglePlayConsoleClient, "request", side_effect=request),
    ):
        client = _client(mock.MagicMock())
        batches = list(
            _iter_list_rows(
                client=client,
                endpoint=endpoint,
                package_names=["com.example.app"],
                history_start=dt.date(2024, 3, 30),
                manager=manager,
                resume=None,
            )
        )

    assert len(seen_params) == 2  # 2024-03-30 and 2024-03-31
    assert seen_params[0]["interval.startTime.day"] == "30"
    assert seen_params[0]["interval.endTime.day"] == "31"
    assert seen_params[0]["interval.startTime.timeZone.id"] == "UTC"
    assert batches[0][0]["app"] == "com.example.app"
    assert batches[0][0]["eventTime"] == dt.datetime(2024, 3, 30, 1, 2, 3)
    assert [state.date for state in manager.saved] == ["2024-03-31", "2024-04-01"]


def test_error_reports_resume_continues_inside_the_interrupted_day() -> None:
    endpoint = LIST_ENDPOINTS["error_reports"]
    resume = GooglePlayConsoleResumeConfig(app="com.example.app", date="2024-03-31", page_token="mid-day")
    manager = _manager(resume)
    seen_params: list[dict[str, Any]] = []

    def request(method: str, path: str, params: Any = None, body: Any = None) -> dict[str, Any]:
        seen_params.append(params or {})
        return {"errorReports": []}

    with (
        mock.patch(f"{MODULE}._today", return_value=TODAY),
        mock.patch.object(GooglePlayConsoleClient, "request", side_effect=request),
    ):
        client = _client(mock.MagicMock())
        list(
            _iter_list_rows(
                client=client,
                endpoint=endpoint,
                package_names=["com.example.app"],
                history_start=dt.date(2024, 3, 1),
                manager=manager,
                resume=resume,
            )
        )

    assert len(seen_params) == 1
    assert seen_params[0]["pageToken"] == "mid-day"
    assert seen_params[0]["interval.startTime.day"] == "31"


def test_error_issues_request_one_trailing_window_per_app() -> None:
    endpoint = LIST_ENDPOINTS["error_issues"]
    manager = _manager()
    calls: list[tuple[str, dict[str, Any]]] = []

    def request(method: str, path: str, params: Any = None, body: Any = None) -> dict[str, Any]:
        calls.append((path, params or {}))
        return {
            "errorIssues": [
                {"name": f"{path}/issue-1", "lastErrorReportTime": {"year": 2024, "month": 3, "day": 20, "hours": 7}}
            ]
        }

    with (
        mock.patch(f"{MODULE}._today", return_value=TODAY),
        mock.patch.object(GooglePlayConsoleClient, "request", side_effect=request),
    ):
        client = _client(mock.MagicMock())
        batches = list(
            _iter_list_rows(
                client=client,
                endpoint=endpoint,
                package_names=["com.a", "com.b"],
                history_start=dt.date(2024, 3, 1),
                manager=manager,
                resume=None,
            )
        )

    assert [path for path, _ in calls] == ["apps/com.a/errorIssues:search", "apps/com.b/errorIssues:search"]
    assert calls[0][1]["interval.startTime.day"] == "1"
    assert calls[0][1]["interval.endTime.day"] == "1"  # exclusive end: 2024-04-01
    assert calls[0][1]["interval.endTime.month"] == "4"
    assert batches[0][0]["lastErrorReportTime"] == dt.datetime(2024, 3, 20, 7)
    assert batches[0][0]["app"] == "com.a"


def test_anomalies_send_no_time_filter() -> None:
    manager = _manager()
    calls: list[dict[str, Any]] = []

    def request(method: str, path: str, params: Any = None, body: Any = None) -> dict[str, Any]:
        calls.append(params or {})
        return {"anomalies": [{"name": f"{path}/anomaly-1"}]}

    with mock.patch.object(GooglePlayConsoleClient, "request", side_effect=request):
        client = _client(mock.MagicMock())
        list(
            _iter_list_rows(
                client=client,
                endpoint=LIST_ENDPOINTS["anomalies"],
                package_names=["com.a"],
                history_start=dt.date(2024, 3, 1),
                manager=manager,
                resume=None,
            )
        )

    assert calls == [{"pageSize": 100}]


def test_interval_params_cover_both_bounds() -> None:
    params = _interval_params(dt.datetime(2024, 3, 1), dt.datetime(2024, 3, 2, 13, 14, 15))

    assert params["interval.startTime.year"] == "2024"
    assert params["interval.startTime.hours"] == "0"
    assert params["interval.endTime.hours"] == "13"
    assert params["interval.endTime.minutes"] == "14"
    assert params["interval.endTime.seconds"] == "15"


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ()),
        ("", ()),
        ("com.example.app", ("com.example.app",)),
        (" com.b , com.a ", ("com.a", "com.b")),
        ("com.a\ncom.b com.a", ("com.a", "com.b")),
    ],
)
def test_parse_package_names(raw: str | None, expected: tuple[str, ...]) -> None:
    assert parse_package_names(raw) == expected


def test_resolve_package_names_discovers_apps_when_none_are_configured() -> None:
    with mock.patch.object(
        GooglePlayConsoleClient,
        "list_apps",
        return_value=[{"packageName": "com.b"}, {"packageName": "com.a"}, {"displayName": "no package"}],
    ):
        client = _client(mock.MagicMock())
        assert resolve_package_names(client, ()) == ["com.a", "com.b"]


def test_resolve_package_names_uses_the_configured_list_without_calling_the_api() -> None:
    with mock.patch.object(GooglePlayConsoleClient, "list_apps") as list_apps:
        client = _client(mock.MagicMock())
        assert resolve_package_names(client, ("com.b", "com.a")) == ["com.a", "com.b"]
    list_apps.assert_not_called()


@pytest.mark.parametrize(
    "watermark,expected",
    [
        (None, dt.date(2024, 1, 1)),
        (dt.date(2024, 3, 10), dt.date(2024, 3, 10)),
        (dt.datetime(2024, 3, 10, 5, 0, 0), dt.date(2024, 3, 10)),
        ("2024-03-10", dt.date(2024, 3, 10)),
        ("2024-03-10T05:00:00", dt.date(2024, 3, 10)),
        # Older than the retained window, so it is floored.
        (dt.date(2020, 1, 1), dt.date(2024, 1, 1)),
        ("nonsense", dt.date(2024, 1, 1)),
    ],
)
def test_resolve_history_start(watermark: Any, expected: dt.date) -> None:
    assert resolve_history_start(TODAY, watermark, 90) == expected


@pytest.mark.parametrize(
    "status,expected_fragment",
    [
        (401, "upload a current JSON key"),
        (403, "Enable the Play Developer"),
        (404, "Enable the Play Developer"),
        (500, "Could not reach the Play Developer Reporting API"),
    ],
)
def test_validate_credentials_maps_status_codes_to_actionable_messages(status: int, expected_fragment: str) -> None:
    response = _response(status, text="denied")
    with mock.patch.object(
        GooglePlayConsoleClient,
        "list_apps",
        side_effect=requests.HTTPError("boom", response=response),
    ):
        is_valid, message = validate_credentials(_key(), "v1beta1")

    assert is_valid is False
    assert message is not None and expected_fragment in message


def test_validate_credentials_reports_a_rejected_key() -> None:
    with mock.patch.object(
        GooglePlayConsoleClient, "list_apps", side_effect=GooglePlayConsoleAuthError("Google rejected the key")
    ):
        assert validate_credentials(_key(), "v1beta1") == (False, "Google rejected the key")


def test_validate_credentials_succeeds_when_the_apps_call_works() -> None:
    with mock.patch.object(GooglePlayConsoleClient, "list_apps", return_value=[{"packageName": "com.a"}]):
        assert validate_credentials(_key(), "v1beta1") == (True, None)


@pytest.mark.parametrize("resource_name", ENDPOINTS)
def test_source_response_shape_per_endpoint(resource_name: str) -> None:
    response = google_play_console_source(
        key=_key(),
        package_names=("com.example.app",),
        resource_name=resource_name,
        api_version="v1beta1",
        resumable_source_manager=_manager(),
        logger=structlog.get_logger(),
    )

    assert response.name == resource_name
    assert response.primary_keys == PRIMARY_KEYS[resource_name]
    assert response.sort_mode == "asc"
    if resource_name in METRIC_SETS:
        assert response.partition_keys == ["date"]
        assert response.partition_mode == "datetime"
    elif resource_name == "error_reports":
        assert response.partition_keys == ["eventTime"]
    else:
        assert response.partition_mode is None


def test_source_response_rejects_an_unknown_endpoint() -> None:
    with pytest.raises(ValueError, match="Unknown Google Play Console endpoint"):
        google_play_console_source(
            key=_key(),
            package_names=(),
            resource_name="not_a_table",
            api_version="v1beta1",
            resumable_source_manager=_manager(),
            logger=structlog.get_logger(),
        )


def test_metric_set_source_streams_rows_for_the_incremental_window() -> None:
    manager = _manager()
    response = google_play_console_source(
        key=_key(),
        package_names=("com.example.app",),
        resource_name="crash_rate",
        api_version="v1beta1",
        resumable_source_manager=manager,
        logger=structlog.get_logger(),
        should_use_incremental_field=True,
        db_incremental_field_last_value=dt.date(2024, 3, 29),
    )

    def request(method: str, path: str, params: Any = None, body: Any = None) -> dict[str, Any]:
        if path.endswith(":query"):
            start = body["timelineSpec"]["startTime"] if body else {}
            return {"rows": [_metric_row(dt.date(start["year"], start["month"], start["day"]), 7, "0.03")]}
        return _freshness(dt.date(2024, 3, 30))

    with (
        mock.patch(f"{MODULE}._today", return_value=TODAY),
        mock.patch(f"{MODULE}.make_tracked_session", return_value=mock.MagicMock()),
        mock.patch.object(GooglePlayConsoleClient, "request", side_effect=request),
    ):
        batches = list(cast("Iterable[Any]", response.items()))

    # The window starts at the stored watermark rather than the full history window.
    assert [row["date"] for batch in batches for row in batch] == [dt.date(2024, 3, 29)]
    # `_freshness` reports latestEndTime 2024-03-30, already Play's exclusive bound, so the
    # window closes out at 2024-03-29 and the checkpoint moves to the day after.
    assert manager.saved[-1].date == "2024-03-30"


def test_error_reports_always_carry_an_event_time_column() -> None:
    endpoint = LIST_ENDPOINTS["error_reports"]

    row = _list_row_to_dict({"name": "apps/com.a/errorReports/1"}, "com.a", endpoint)

    assert row["eventTime"] is None


def test_optional_timestamps_are_not_invented_when_absent() -> None:
    endpoint = LIST_ENDPOINTS["error_issues"]

    row = _list_row_to_dict({"name": "apps/com.a/errorIssues/1"}, "com.a", endpoint)

    assert "firstErrorReportTime" not in row
