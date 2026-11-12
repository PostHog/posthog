import gzip
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import patch

import responses
from requests.exceptions import HTTPError

from products.warehouse_sources.sources.sdk import RESTClientRetryableError
from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.sources.speedcurve._config import SpeedcurveSourceConfig
from products.warehouse_sources.sources.speedcurve.settings import RUM_EXPORT_COLUMNS
from products.warehouse_sources.sources.speedcurve.source import SpeedcurveSource
from products.warehouse_sources.sources.speedcurve.speedcurve import (
    AUTH_ERROR,
    PERMISSION_ERROR,
    SpeedcurveResumeConfig,
    validate_credentials,
)

NOW = datetime(2026, 6, 15, tzinfo=UTC)
BASE_URL = "https://api.speedcurve.com/v1/"


@pytest.fixture(autouse=True)
def fixed_clock() -> Iterator[Any]:
    with patch("products.warehouse_sources.sources.speedcurve.speedcurve.datetime", wraps=datetime) as clock:
        clock.now.return_value = NOW
        yield clock


def _run(
    endpoint: str,
    script: Script,
    resume_state: SpeedcurveResumeConfig | None = None,
    **inputs: Any,
) -> DriveResult:
    config = SpeedcurveSourceConfig(api_key="fake-key")
    return SourceDriver(SpeedcurveSource(), config).run(endpoint, script, resume_state=resume_state, **inputs)


@pytest.mark.parametrize(
    ("endpoint", "body", "expected"),
    [
        ("sites", {"sites": [{"site_id": 1, "name": "Example"}]}, [{"site_id": 1, "name": "Example"}]),
        ("notes", {"notes": [{"note_id": 2, "note": "New layout"}]}, [{"note_id": 2, "note": "New layout"}]),
        ("budgets", {"budgets": [{"budget_id": 3, "status": "over"}]}, [{"budget_id": 3, "status": "over"}]),
        (
            "urls",
            {
                "sites": [
                    {"site_id": 1, "urls": [{"url_id": 4, "url": "https://example.com"}]},
                    {"site_id": 2, "urls": [{"url_id": 4, "url": "https://example.org"}]},
                    {"site_id": 3, "urls": []},
                ]
            },
            [
                {"site_id": 1, "url_id": 4, "url": "https://example.com"},
                {"site_id": 2, "url_id": 4, "url": "https://example.org"},
            ],
        ),
    ],
)
def test_single_page_rows_and_auth(endpoint: str, body: dict[str, Any], expected: list[dict[str, Any]]) -> None:
    result = _run(endpoint, [ScriptedResponse(json=body)])

    assert result.rows == expected
    assert len(result.requests) == 1
    request = result.requests[0]
    assert request.path == f"/v1/{endpoint}"
    assert request.headers["authorization"] == "Basic ZmFrZS1rZXk6eA=="
    assert dict(request.query) == {}
    if endpoint == "urls":
        assert result.response is not None
        primary_keys = result.response.primary_keys or []
        assert len({tuple(row[key] for key in primary_keys) for row in expected}) == 2


@pytest.mark.parametrize("endpoint", ["tests", "deploys"])
def test_pagination_and_resume_checkpoint(endpoint: str) -> None:
    selector = "data" if endpoint == "tests" else "deploys"
    key = "test_id" if endpoint == "tests" else "deploy_id"
    script: list[ScriptedResponse] = []
    for page in (1, 2):
        body: dict[str, Any] = {selector: [{key: page, "timestamp": int(NOW.timestamp()) - page}]}
        if endpoint == "tests":
            body["meta"] = {"last_page": 2}
        script.append(ScriptedResponse(json=body))
    if endpoint == "deploys":
        script.append(ScriptedResponse(json={selector: []}))

    result = _run(endpoint, script)

    assert [row[key] for row in result.rows] == [1, 2]
    query_params = [dict(request.query) for request in result.requests]
    assert [params["page"] for params in query_params] == (
        [("1",), ("2",)] if endpoint == "tests" else [("1",), ("2",), ("3",)]
    )
    assert all(params["per_page"] == ("100",) for params in query_params)
    assert all(params["end_timestamp"] == (str(int(NOW.timestamp())),) for params in query_params)
    assert [checkpoint.page for checkpoint in result.saved_states] == ([2] if endpoint == "tests" else [2, 3])
    assert all(checkpoint.end_timestamp == int(NOW.timestamp()) for checkpoint in result.saved_states)
    assert result.response is not None
    assert result.response.sort_mode == "desc"
    # The run itself leaves the checkpoint in place; only `on_complete` clears it.
    assert result.final_state == result.saved_states[-1]
    assert result.completed_state is None


@pytest.mark.parametrize("endpoint", ["tests", "deploys"])
def test_resume_preserves_range_when_clock_and_watermark_change(endpoint: str) -> None:
    saved = SpeedcurveResumeConfig(page=4, start_timestamp=1751000000, end_timestamp=1752000000)
    selector = "data" if endpoint == "tests" else "deploys"

    result = _run(
        endpoint,
        [ScriptedResponse(json={selector: []})],
        resume_state=saved,
        should_use_incremental_field=True,
        db_incremental_field_last_value=1780000000,
    )

    assert result.rows == []
    assert dict(result.requests[0].query) == {
        "page": ("4",),
        "per_page": ("100",),
        "start_timestamp": ("1751000000",),
        "end_timestamp": ("1752000000",),
    }
    assert result.saved_states == []


@responses.activate
def test_validation_uses_one_cheap_request() -> None:
    responses.get(BASE_URL + "sites", json={"sites": []})
    assert validate_credentials("fake-key", "v1") == (True, None)
    assert len(responses.calls) == 1
    request = responses.calls[0].request
    assert parse_qs(urlsplit(request.url).query) == {"median": ["0"]}
    assert request.headers["Authorization"] == "Basic ZmFrZS1rZXk6eA=="


@pytest.mark.parametrize("endpoint", ["sites", "rum_export"])
@pytest.mark.parametrize(("status", "expected_message"), [(401, AUTH_ERROR), (403, PERMISSION_ERROR)])
def test_sync_auth_errors_map_to_the_actionable_message(endpoint: str, status: int, expected_message: str) -> None:
    result = _run(endpoint, [ScriptedResponse(status=status, json={"status": "error", "message": "denied"})])

    assert isinstance(result.raised, HTTPError)
    mapped = [
        value
        for pattern, value in SpeedcurveSource().get_non_retryable_errors().items()
        if pattern in str(result.raised)
    ]
    assert mapped == [expected_message]
    assert len(result.requests) == 1


@responses.activate
@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_errors_retry_without_becoming_invalid_credentials(status: int) -> None:
    responses.get(BASE_URL + "sites", status=status, json={"message": "Unavailable"}, headers={"Retry-After": "0"})
    with pytest.raises(RESTClientRetryableError):
        validate_credentials("fake-key", "v1")
    assert len(responses.calls) == 5


@responses.activate
def test_other_client_errors_propagate() -> None:
    responses.get(BASE_URL + "sites", status=422, json={"message": "Parameters are not valid."})
    with pytest.raises(HTTPError):
        validate_credentials("fake-key", "v1")
    assert len(responses.calls) == 1


@pytest.mark.parametrize("endpoint", ["sites", "urls", "tests", "deploys", "notes", "budgets"])
def test_missing_collection_does_not_silently_empty_table(endpoint: str) -> None:
    result = _run(endpoint, [ScriptedResponse(json={"unexpected": []})])

    assert isinstance(result.raised, ValueError)
    assert "selector" in str(result.raised)


def _rum_line(page_id: int, epoch: int, **values: str) -> str:
    fields = [""] * len(RUM_EXPORT_COLUMNS)
    names = [name for name, _ in RUM_EXPORT_COLUMNS]
    fields[names.index("page_id")] = str(page_id)
    fields[names.index("epoch")] = str(epoch)
    for name, value in values.items():
        fields[names.index(name)] = value
    return "^".join(fields)


def _rum_vendor(files: dict[str, bytes], compress: bool = True) -> Callable[[RecordedRequest], ScriptedResponse]:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/v1/lux/export":
            date = request.param("date")
            return ScriptedResponse(json={"download_url": f"https://exports.example.com/{date}.gz?X-Amz-Signature=abc"})
        date = request.path.strip("/").removesuffix(".gz")
        if date not in files:
            return ScriptedResponse(status=403, body=b"<Error><Code>AccessDenied</Code></Error>")
        return ScriptedResponse(body=gzip.compress(files[date]) if compress else files[date])

    return respond


JUNE_12 = int(datetime(2026, 6, 12, 10, tzinfo=UTC).timestamp())
JUNE_13 = int(datetime(2026, 6, 13, 10, tzinfo=UTC).timestamp())


@pytest.mark.parametrize("compress", [True, False])
def test_rum_export_reads_each_daily_file_and_skips_missing_days(compress: bool) -> None:
    june_12 = "\r\n".join(
        [
            _rum_line(11, JUNE_12, page_label="Home", cumulative_layout_shift="0.12", beacon_type="main"),
            # A row with fewer columns than documented, then one with a column SpeedCurve added later.
            "12^999^" + str(JUNE_12),
            _rum_line(13, JUNE_12, device_memory="not-a-number") + "^extra",
            "",
        ]
    ).encode()
    files = {"20260612": june_12}

    result = _run(
        "rum_export",
        _rum_vendor(files, compress),
        should_use_incremental_field=True,
        db_incremental_field_last_value=int(datetime(2026, 6, 10, 23, tzinfo=UTC).timestamp()),
    )

    assert result.raised is None
    export_requests = [request for request in result.requests if request.path == "/v1/lux/export"]
    assert [request.param("date") for request in export_requests] == ["20260611", "20260612", "20260613"]
    assert all(request.headers["authorization"] == "Basic ZmFrZS1rZXk6eA==" for request in export_requests)
    file_requests = [request for request in result.requests if request.path.endswith(".gz")]
    assert len(file_requests) == 3
    assert all("authorization" not in request.headers for request in file_requests)

    assert [(row["export_date"], row["export_row"], row["page_id"]) for row in result.rows] == [
        ("2026-06-12", 0, 11),
        ("2026-06-12", 1, 12),
        ("2026-06-12", 2, 13),
    ]
    first, short, extended = result.rows
    assert first["epoch"] == JUNE_12
    assert first["page_label"] == "Home"
    assert first["cumulative_layout_shift"] == 0.12
    assert first["beacon_type"] == "main"
    assert first["hostname"] is None
    assert short["session_id"] == 999
    assert short["beacon_type"] is None
    assert extended["device_memory"] is None
    assert extended[f"column_{len(RUM_EXPORT_COLUMNS)}"] == "extra"

    day_starts = [int(datetime(2026, 6, day, tzinfo=UTC).timestamp()) for day in (11, 12, 13)]
    assert [(state.start_timestamp, state.row_offset) for state in result.saved_states] == [
        (day_starts[0], 0),
        (day_starts[1], 0),
        (day_starts[1], 3),
        (day_starts[2], 0),
    ]
    assert all(state.end_timestamp == day_starts[2] for state in result.saved_states)
    assert result.response is not None
    assert result.response.sort_mode is None
    assert result.completed_state is None


@pytest.mark.parametrize(
    ("now", "watermark", "expected_dates"),
    [
        # Before 06:00 UTC the previous day's file may not be published yet.
        (datetime(2026, 6, 15, 5, 59, tzinfo=UTC), JUNE_12, ["20260613"]),
        (datetime(2026, 6, 15, 6, tzinfo=UTC), JUNE_12, ["20260613", "20260614"]),
        (datetime(2026, 6, 15, 6, tzinfo=UTC), JUNE_13 + 86400, []),
    ],
)
def test_rum_export_incremental_window(
    fixed_clock: Any, now: datetime, watermark: int, expected_dates: list[str]
) -> None:
    fixed_clock.now.return_value = now

    result = _run(
        "rum_export",
        _rum_vendor({}),
        should_use_incremental_field=True,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert [request.param("date") for request in result.requests if request.path == "/v1/lux/export"] == expected_dates


def test_rum_export_full_refresh_reads_the_history_window() -> None:
    result = _run("rum_export", _rum_vendor({}))

    dates = [request.param("date") for request in result.requests if request.path == "/v1/lux/export"]
    assert (dates[0], dates[-1], len(dates)) == ("20260515", "20260613", 30)


def test_rum_export_resumes_inside_a_day_and_keeps_the_saved_range() -> None:
    lines = [_rum_line(page_id, JUNE_12) for page_id in (1, 2, 3)]
    saved = SpeedcurveResumeConfig(
        page=1,
        start_timestamp=int(datetime(2026, 6, 12, tzinfo=UTC).timestamp()),
        end_timestamp=int(datetime(2026, 6, 12, tzinfo=UTC).timestamp()),
        row_offset=2,
    )

    result = _run(
        "rum_export",
        _rum_vendor({"20260612": "\n".join(lines).encode()}),
        resume_state=saved,
        should_use_incremental_field=True,
        db_incremental_field_last_value=JUNE_13 + 86400 * 30,
    )

    assert [(row["export_row"], row["page_id"]) for row in result.rows] == [(2, 3)]
    assert [request.param("date") for request in result.requests if request.path == "/v1/lux/export"] == ["20260612"]


def test_rum_export_without_download_url_fails() -> None:
    result = _run("rum_export", [ScriptedResponse(json={})])

    assert isinstance(result.raised, ValueError)
    assert "download_url" in str(result.raised)
