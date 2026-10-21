import datetime as dt
import functools
from typing import Any
from urllib.parse import parse_qsl

import pytest
from unittest import mock

import jwt
import requests
import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googleplayconsole import (
    GooglePlayConsoleKeyFileConfig,
    GooglePlayConsoleSourceConfig,
)
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
    _list_row_to_dict,
    _metric_row_to_dict,
    _metric_value,
    _normalize_private_key,
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
    RELEASE_FILTER_OPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_play_console.source import (
    GooglePlayConsoleSource,
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


TOKEN = ScriptedResponse(json={"access_token": "ya29.token", "expires_in": 3600})


def _driver(package_names: str | None = "com.example.app") -> SourceDriver:
    key = _key()
    config = GooglePlayConsoleSourceConfig(
        key_file=GooglePlayConsoleKeyFileConfig(
            client_email=key.client_email,
            private_key=key.private_key,
            private_key_id=key.private_key_id or "",
            token_uri=key.token_uri or DEFAULT_TOKEN_URI,
        ),
        app_package_names=package_names,
    )
    return SourceDriver(GooglePlayConsoleSource(), config)


def _run(
    schema_name: str,
    responses: list[ScriptedResponse],
    *,
    package_names: str | None = "com.example.app",
    resume_state: GooglePlayConsoleResumeConfig | None = None,
    **inputs: Any,
) -> DriveResult:
    return _driver(package_names).run(schema_name, [TOKEN, *responses], resume_state=resume_state, **inputs)


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
    with scripted_network([TOKEN, ScriptedResponse(json={"apps": []})]) as network:
        client = GooglePlayConsoleClient(_key(), "v1beta1", structlog.get_logger())
        client.request("GET", "apps:search")

    assert network.requests_log[0].url == DEFAULT_TOKEN_URI
    posted = dict(parse_qsl((network.requests_log[0].body or b"").decode()))
    assert posted["grant_type"] == JWT_BEARER_GRANT

    claims = jwt.decode(posted["assertion"], _rsa_key_pair()[1], algorithms=["RS256"], audience=DEFAULT_TOKEN_URI)
    assert claims["iss"] == "reporting@example.iam.gserviceaccount.com"
    assert claims["scope"] == PLAY_REPORTING_SCOPE
    assert claims["exp"] - claims["iat"] == 3600
    assert jwt.get_unverified_header(posted["assertion"])["kid"] == "key-1"
    assert network.requests_log[1].headers["authorization"] == "Bearer ya29.token"


def test_ignores_the_uploaded_token_uri_and_posts_to_google() -> None:
    malicious_key = ServiceAccountKey(
        client_email="reporting@example.iam.gserviceaccount.com",
        private_key=_rsa_key_pair()[0],
        private_key_id="key-1",
        token_uri="http://169.254.169.254/latest/meta-data/",
    )
    with scripted_network([TOKEN, ScriptedResponse(json={"apps": []})]) as network:
        client = GooglePlayConsoleClient(malicious_key, "v1beta1", structlog.get_logger())
        client.request("GET", "apps:search")

    assert network.requests_log[0].url == DEFAULT_TOKEN_URI
    posted = dict(parse_qsl((network.requests_log[0].body or b"").decode()))
    claims = jwt.decode(
        posted["assertion"],
        _rsa_key_pair()[1],
        algorithms=["RS256"],
        audience=DEFAULT_TOKEN_URI,
    )
    assert claims["aud"] == DEFAULT_TOKEN_URI


def test_reuses_the_access_token_until_it_expires() -> None:
    with scripted_network([TOKEN, ScriptedResponse(json={"apps": []}), ScriptedResponse(json={"apps": []})]) as network:
        client = GooglePlayConsoleClient(_key(), "v1beta1", structlog.get_logger())
        client.request("GET", "apps:search")
        client.request("GET", "apps:search")

    assert [request.path for request in network.requests_log] == [
        "/token",
        "/v1beta1/apps:search",
        "/v1beta1/apps:search",
    ]


def test_remints_the_access_token_when_a_request_comes_back_unauthorized() -> None:
    with scripted_network(
        [
            TOKEN,
            ScriptedResponse(status=401, body=b"expired"),
            TOKEN,
            ScriptedResponse(json={"apps": [{"packageName": "a"}]}),
        ]
    ) as network:
        client = GooglePlayConsoleClient(_key(), "v1beta1", structlog.get_logger())
        assert client.request("GET", "apps:search") == {"apps": [{"packageName": "a"}]}

    assert [request.path for request in network.requests_log] == [
        "/token",
        "/v1beta1/apps:search",
        "/token",
        "/v1beta1/apps:search",
    ]


def test_raises_a_permanent_error_when_google_rejects_the_key() -> None:
    with scripted_network([ScriptedResponse(status=400, body=b"invalid_grant")]):
        client = GooglePlayConsoleClient(_key(), "v1beta1", structlog.get_logger())
        with pytest.raises(GooglePlayConsoleAuthError, match="Google rejected the service account key"):
            client.request("GET", "apps:search")


def test_raises_a_permanent_error_when_the_key_cannot_sign() -> None:
    with scripted_network([]) as network:
        client = GooglePlayConsoleClient(_key(private_key="not-a-pem-key"), "v1beta1", structlog.get_logger())
        with pytest.raises(GooglePlayConsoleAuthError, match="Could not sign a token"):
            client.request("GET", "apps:search")

    assert network.requests_log == []


def test_non_2xx_api_responses_raise_for_status() -> None:
    with scripted_network([TOKEN, ScriptedResponse(status=403, body=b"forbidden")]):
        client = GooglePlayConsoleClient(_key(), "v1beta1", structlog.get_logger())
        with pytest.raises(requests.HTTPError):
            client.request("GET", "apps/com.example/anomalies")


def test_list_apps_follows_pagination() -> None:
    with scripted_network(
        [
            TOKEN,
            ScriptedResponse(json={"apps": [{"packageName": "com.b"}], "nextPageToken": "t1"}),
            ScriptedResponse(json={"apps": [{"packageName": "com.a"}]}),
        ]
    ) as network:
        client = GooglePlayConsoleClient(_key(), "v1beta1", structlog.get_logger())
        assert [app["packageName"] for app in client.list_apps()] == ["com.b", "com.a"]

    assert network.requests_log[2].param("pageToken") == "t1"


def test_latest_available_date_converts_the_exclusive_freshness_bound_to_an_inclusive_day() -> None:
    # Play documents `latestEndTime` as already being the exclusive bound ready to reuse as
    # `timelineSpec.endTime` (one day past the last day with data) — not the last day itself.
    with scripted_network([TOKEN, ScriptedResponse(json=_freshness(dt.date(2024, 3, 10)))]):
        client = GooglePlayConsoleClient(_key(), "v1beta1", structlog.get_logger())
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
    with mock.patch(f"{MODULE}._today", return_value=TODAY):
        result = _run(
            "crash_rate",
            [
                ScriptedResponse(json=_freshness(dt.date(2024, 3, 10))),
                ScriptedResponse(json={"rows": [_metric_row(dt.date(2024, 3, 5), 12, "0.01")]}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=dt.date(2024, 3, 1),
        )

    assert result.raised is None
    assert len(result.items) == 1
    assert result.paths[1:] == [
        "/v1beta1/apps/com.example.app/crashRateMetricSet",
        "/v1beta1/apps/com.example.app/crashRateMetricSet:query",
    ]
    body = result.requests[2].json()
    timeline = body["timelineSpec"]
    assert timeline["aggregationPeriod"] == "DAILY"
    assert timeline["startTime"] == {"year": 2024, "month": 3, "day": 1}
    # `_freshness` reports latestEndTime 2024-03-10, already Play's exclusive bound, so it is
    # requested as-is rather than being pushed a further day out.
    assert timeline["endTime"] == {"year": 2024, "month": 3, "day": 10}
    assert body["dimensions"] == ["versionCode"]
    assert result.saved_states == [GooglePlayConsoleResumeConfig(app="com.example.app", date="2024-03-10")]


def test_a_wider_metric_set_asks_play_for_the_extra_dimension() -> None:
    with mock.patch(f"{MODULE}._today", return_value=TODAY):
        result = _run(
            "crash_rate_by_device_model",
            [
                ScriptedResponse(json=_freshness(dt.date(2024, 3, 10))),
                ScriptedResponse(json={"rows": [_metric_row(dt.date(2024, 3, 5), 12, "0.01")]}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=dt.date(2024, 3, 1),
        )

    assert result.raised is None
    body = result.requests[2].json()
    assert body["dimensions"] == ["versionCode", "deviceModel"]
    assert body["metrics"] == list(METRIC_SETS["crash_rate"].metrics)


def test_a_wider_metric_set_row_carries_its_extra_dimension_column() -> None:
    row = _metric_row_to_dict(
        {
            "startTime": {"year": 2024, "month": 3, "day": 2},
            "endTime": {"year": 2024, "month": 3, "day": 3},
            "dimensions": [{"dimension": "deviceModel", "stringValue": "Pixel 8", "valueLabel": "Google Pixel 8"}],
            "metrics": [],
        },
        "com.example.app",
        METRIC_SETS["crash_rate_by_device_model"],
    )

    assert row["deviceModel"] == "Pixel 8"
    assert row["deviceModelLabel"] == "Google Pixel 8"
    assert row["versionCode"] is None


def test_metric_set_skips_an_app_without_freshness() -> None:
    # Empty freshness — the app has no queryable data for this metric set.
    result = _run("anr_rate", [ScriptedResponse(json={})])

    # No freshness means no queryable data: the app is skipped rather than queried with a guessed
    # window Google rejects as an invalid timeframe. No `:query` is issued and nothing is yielded.
    assert result.raised is None
    assert result.rows == []
    assert not any(path.endswith(":query") for path in result.paths)


def test_metric_set_skips_an_app_denied_a_games_only_metric_set() -> None:
    def answer(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/token":
            return TOKEN
        if request.path.endswith(":query"):
            return ScriptedResponse(json={"rows": [_metric_row(dt.date(2024, 3, 5), 12, "0.01")]})
        if "/com.fintech.app/" in request.path:
            return ScriptedResponse(status=403, body=b"slowRenderingRateMetricSet resource is only accessible to games")
        return ScriptedResponse(json=_freshness(dt.date(2024, 3, 10)))

    with mock.patch(f"{MODULE}._today", return_value=TODAY):
        result = _driver("com.fintech.app, com.game.app").run(
            "slow_rendering_rate",
            answer,
            should_use_incremental_field=True,
            db_incremental_field_last_value=dt.date(2024, 3, 1),
        )

    # The non-game app can never have this metric set, so it is skipped instead of failing the
    # sync with a 403 the error classifier reads as missing permissions. The game still syncs.
    assert result.raised is None
    assert [path for path in result.paths if path.endswith(":query")] == [
        "/v1beta1/apps/com.game.app/slowRenderingRateMetricSet:query"
    ]
    assert len(result.items) == 1


def test_metric_set_reraises_a_403_that_is_not_the_games_restriction() -> None:
    result = _run("slow_rendering_rate", [ScriptedResponse(status=403, body=b"The caller does not have permission")])

    assert isinstance(result.raised, requests.HTTPError)


def test_metric_set_query_follows_pagination_until_the_token_runs_out() -> None:
    with mock.patch(f"{MODULE}._today", return_value=TODAY):
        result = _run(
            "crash_rate",
            [
                ScriptedResponse(json=_freshness(dt.date(2024, 3, 2))),
                ScriptedResponse(
                    json={"rows": [_metric_row(dt.date(2024, 3, 1), 1, "0.01")], "nextPageToken": "page-2"}
                ),
                ScriptedResponse(json={"rows": [_metric_row(dt.date(2024, 3, 2), 1, "0.02")]}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=dt.date(2024, 3, 1),
        )

    assert result.raised is None
    assert result.requests[3].json()["pageToken"] == "page-2"
    assert [batch[0]["date"] for batch in result.items] == [dt.date(2024, 3, 1), dt.date(2024, 3, 2)]


def test_metric_set_resume_skips_finished_apps_and_restarts_at_the_saved_window() -> None:
    def answer(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/token":
            return TOKEN
        if request.path.endswith(":query"):
            return ScriptedResponse(json={"rows": []})
        return ScriptedResponse(json=_freshness(dt.date(2024, 3, 6)))

    with mock.patch(f"{MODULE}._today", return_value=TODAY):
        result = _driver("com.a, com.b, com.c").run(
            "crash_rate",
            answer,
            resume_state=GooglePlayConsoleResumeConfig(app="com.b", date="2024-03-05"),
            should_use_incremental_field=True,
            db_incremental_field_last_value=dt.date(2024, 3, 1),
        )

    # com.a was finished before the interruption; com.b picks up at the saved date and com.c
    # starts from the beginning of the history window.
    assert result.raised is None
    assert [
        (request.path.split("/")[3], request.json()["timelineSpec"]["startTime"])
        for request in result.requests
        if request.path.endswith(":query")
    ] == [
        ("com.b", {"year": 2024, "month": 3, "day": 5}),
        ("com.c", {"year": 2024, "month": 3, "day": 1}),
    ]


def test_apps_endpoint_paginates_and_checkpoints_each_page() -> None:
    result = _run(
        "apps",
        [
            ScriptedResponse(json={"apps": [{"packageName": "com.a"}], "nextPageToken": "p2"}),
            ScriptedResponse(json={"apps": [{"packageName": "com.b"}]}),
        ],
    )

    assert result.raised is None
    assert [row["packageName"] for row in result.rows] == ["com.a", "com.b"]
    assert [state.page_token for state in result.saved_states] == ["p2", None]
    assert result.params("pageToken") == [None, None, "p2"]
    # The app catalog is not per-app, so no package name is stamped onto its rows.
    assert "app" not in result.rows[0]


def test_error_reports_walk_one_day_at_a_time_with_an_interval_filter() -> None:
    with mock.patch(f"{MODULE}._today", return_value=TODAY):
        result = _run(
            "error_reports",
            [
                ScriptedResponse(json={"errorReports": [{"name": "report-1", "eventTime": "2024-03-30T01:02:03Z"}]}),
                ScriptedResponse(json={"errorReports": [{"name": "report-2", "eventTime": "2024-03-30T01:02:03Z"}]}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=dt.date(2024, 3, 30),
        )

    assert result.raised is None
    assert len(result.requests) == 3  # Token, 2024-03-30 and 2024-03-31.
    assert result.requests[1].param("interval.startTime.day") == "30"
    assert result.requests[1].param("interval.endTime.day") == "31"
    assert result.requests[1].param("interval.startTime.timeZone.id") == "UTC"
    assert result.rows[0]["app"] == "com.example.app"
    assert result.rows[0]["eventTime"] == dt.datetime(2024, 3, 30, 1, 2, 3)
    assert [state.date for state in result.saved_states] == ["2024-03-31", "2024-04-01"]


def test_error_reports_resume_continues_inside_the_interrupted_day() -> None:
    resume = GooglePlayConsoleResumeConfig(app="com.example.app", date="2024-03-31", page_token="mid-day")
    with mock.patch(f"{MODULE}._today", return_value=TODAY):
        result = _run(
            "error_reports",
            [ScriptedResponse(json={"errorReports": []})],
            resume_state=resume,
            should_use_incremental_field=True,
            db_incremental_field_last_value=dt.date(2024, 3, 1),
        )

    assert result.raised is None
    assert len(result.requests) == 2
    assert result.requests[1].param("pageToken") == "mid-day"
    assert result.requests[1].param("interval.startTime.day") == "31"


def test_error_issues_request_one_trailing_window_per_app() -> None:
    answer = ScriptedResponse(
        json={
            "errorIssues": [
                {"name": "issue-1", "lastErrorReportTime": {"year": 2024, "month": 3, "day": 20, "hours": 7}}
            ]
        }
    )
    with mock.patch(f"{MODULE}._today", return_value=TODAY):
        result = _run(
            "error_issues",
            [answer, answer],
            package_names="com.a, com.b",
            should_use_incremental_field=True,
            db_incremental_field_last_value=dt.date(2024, 3, 1),
        )

    assert result.raised is None
    assert result.paths[1:] == ["/v1beta1/apps/com.a/errorIssues:search", "/v1beta1/apps/com.b/errorIssues:search"]
    assert result.requests[1].param("interval.startTime.day") == "1"
    assert result.requests[1].param("interval.endTime.day") == "1"  # exclusive end: 2024-04-01
    assert result.requests[1].param("interval.endTime.month") == "4"
    assert result.rows[0]["lastErrorReportTime"] == dt.datetime(2024, 3, 20, 7)
    assert result.rows[0]["app"] == "com.a"


def test_anomalies_send_no_time_filter() -> None:
    result = _run("anomalies", [ScriptedResponse(json={"anomalies": [{"name": "anomaly-1"}]})], package_names="com.a")

    assert result.raised is None
    assert result.queries[1] == {"pageSize": ("100",)}


def test_release_filter_options_flatten_per_version_code_and_resume_past_finished_apps() -> None:
    result = _run(
        RELEASE_FILTER_OPTIONS,
        [
            ScriptedResponse(
                json={
                    "tracks": [
                        {
                            "displayName": "Production",
                            "type": "PRODUCTION",
                            "servingReleases": [{"displayName": "2.1.0", "versionCodes": ["210", "211"]}],
                        },
                        {
                            "displayName": "Internal testing",
                            "type": "INTERNAL",
                            "servingReleases": [{"displayName": "2.2.0-rc1", "versionCodes": ["220"]}],
                        },
                    ]
                }
            ),
            ScriptedResponse(json={}),
        ],
        package_names="com.a, com.b, com.c",
        resume_state=GooglePlayConsoleResumeConfig(app="com.b"),
    )

    assert result.raised is None
    assert result.paths[1:] == [
        "/v1beta1/apps/com.b:fetchReleaseFilterOptions",
        "/v1beta1/apps/com.c:fetchReleaseFilterOptions",
    ]
    assert [
        (row["app"], row["track"], row["trackType"], row["release"], row["versionCode"]) for row in result.rows
    ] == [
        ("com.b", "Production", "PRODUCTION", "2.1.0", 210),
        ("com.b", "Production", "PRODUCTION", "2.1.0", 211),
        ("com.b", "Internal testing", "INTERNAL", "2.2.0-rc1", 220),
    ]
    assert result.saved_states == [GooglePlayConsoleResumeConfig(app="com.c")]


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
    apps = [{"packageName": "com.b"}, {"packageName": "com.a"}, {"displayName": "no package"}]
    with scripted_network([TOKEN, ScriptedResponse(json={"apps": apps})]):
        client = GooglePlayConsoleClient(_key(), "v1beta1", structlog.get_logger())
        assert resolve_package_names(client, ()) == ["com.a", "com.b"]


def test_resolve_package_names_uses_the_configured_list_without_calling_the_api() -> None:
    with scripted_network([]) as network:
        client = GooglePlayConsoleClient(_key(), "v1beta1", structlog.get_logger())
        assert resolve_package_names(client, ("com.b", "com.a")) == ["com.a", "com.b"]
    assert network.requests_log == []


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
    def answer(request: RecordedRequest) -> ScriptedResponse:
        return TOKEN if request.path == "/token" else ScriptedResponse(status=status, body=b"denied")

    with scripted_network(answer):
        is_valid, message = validate_credentials(_key(), "v1beta1")

    assert is_valid is False
    assert message is not None and expected_fragment in message


def test_validate_credentials_reports_a_rejected_key() -> None:
    with scripted_network([ScriptedResponse(status=400, body=b"invalid_grant")]):
        is_valid, message = validate_credentials(_key(), "v1beta1")

    assert is_valid is False
    assert message is not None and "Google rejected the service account key" in message


def test_validate_credentials_succeeds_when_the_apps_call_works() -> None:
    with scripted_network([TOKEN, ScriptedResponse(json={"apps": [{"packageName": "com.a"}]})]):
        assert validate_credentials(_key(), "v1beta1") == (True, None)


@pytest.mark.parametrize("resource_name", ENDPOINTS)
def test_source_response_shape_per_endpoint(resource_name: str) -> None:
    result = _driver().run(resource_name, [])
    response = result.response

    assert response is not None
    assert response.name == resource_name
    assert response.primary_keys == PRIMARY_KEYS[resource_name]
    assert response.sort_mode == (None if resource_name == RELEASE_FILTER_OPTIONS else "asc")
    if resource_name in METRIC_SETS:
        assert response.partition_keys == ["date"]
        assert response.partition_mode == "datetime"
    elif resource_name == "error_reports":
        assert response.partition_keys == ["eventTime"]
    else:
        assert response.partition_mode is None


def test_metric_set_source_streams_rows_for_the_incremental_window() -> None:
    with mock.patch(f"{MODULE}._today", return_value=TODAY):
        result = _run(
            "crash_rate",
            [
                ScriptedResponse(json=_freshness(dt.date(2024, 3, 30))),
                ScriptedResponse(json={"rows": [_metric_row(dt.date(2024, 3, 29), 7, "0.03")]}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=dt.date(2024, 3, 29),
        )

    # The window starts at the stored watermark rather than the full history window.
    assert result.raised is None
    assert [row["date"] for row in result.rows] == [dt.date(2024, 3, 29)]
    # `_freshness` reports latestEndTime 2024-03-30, already Play's exclusive bound, so the
    # window closes out at 2024-03-29 and the checkpoint moves to the day after.
    assert result.saved_states[-1].date == "2024-03-30"


@pytest.mark.parametrize(
    "resource_name,expected_start",
    [
        # The vitals rate metric sets keep the deep 180-day backfill.
        ("crash_rate", dt.date(2023, 10, 3)),
        # Error counts live on the short-retention error backend, which rejects a start that
        # far back with a 400, so the first sync begins inside the error history window.
        ("error_counts", dt.date(2024, 3, 1)),
    ],
)
def test_first_sync_history_window_depends_on_the_metric_set(resource_name: str, expected_start: dt.date) -> None:
    def answer(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/token":
            return TOKEN
        if request.path.endswith(":query"):
            return ScriptedResponse(json={"rows": []})
        return ScriptedResponse(json=_freshness(dt.date(2024, 3, 30)))

    with mock.patch(f"{MODULE}._today", return_value=TODAY):
        result = _driver().run(resource_name, answer)

    assert result.raised is None
    first_start = result.requests[2].json()["timelineSpec"]["startTime"]
    assert dt.date(first_start["year"], first_start["month"], first_start["day"]) == expected_start


def test_error_reports_always_carry_an_event_time_column() -> None:
    endpoint = LIST_ENDPOINTS["error_reports"]

    row = _list_row_to_dict({"name": "apps/com.a/errorReports/1"}, "com.a", endpoint)

    assert row["eventTime"] is None


def test_optional_timestamps_are_not_invented_when_absent() -> None:
    endpoint = LIST_ENDPOINTS["error_issues"]

    row = _list_row_to_dict({"name": "apps/com.a/errorIssues/1"}, "com.a", endpoint)

    assert "firstErrorReportTime" not in row
