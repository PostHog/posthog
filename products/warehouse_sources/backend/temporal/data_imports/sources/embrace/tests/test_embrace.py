import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Literal, cast
from urllib.parse import parse_qs, urlparse

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from requests import PreparedRequest, Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.embrace.embrace import (
    EmbraceClient,
    EmbraceResumeConfig,
    embrace_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.embrace.source import EmbraceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.embrace import (
    EmbraceSourceConfig,
)

NOW = datetime(2026, 1, 31, 12, 30, tzinfo=UTC)
END = int(datetime(2026, 1, 31, 11, tzinfo=UTC).timestamp())


@pytest.fixture
def config() -> EmbraceSourceConfig:
    return EmbraceSourceConfig(api_token="test-token", app_id="example-app", region="default")


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


def response(request: PreparedRequest, body: object, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = {200: "OK", 401: "Unauthorized", 403: "Forbidden", 400: "Bad Request"}.get(status, "Error")
    result.url = request.url or ""
    result.request = request
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    return result


def matrix(series: list[dict[str, object]]) -> dict[str, object]:
    return {"status": "success", "data": {"resultType": "matrix", "result": series}}


@pytest.mark.parametrize(
    ("region", "host", "endpoint", "metric"),
    [
        ("default", "api.embrace.io", "sessions", "hourly_sessions_total"),
        ("us", "api-us1.embrace.io", "crashes", "hourly_crashes_total"),
        ("eu", "api-eu1.embrace.io", "network_4xx", "hourly_network4xx_total"),
        ("eu", "api-eu1.embrace.io", "network_5xx", "hourly_network5xx_total"),
    ],
)
def test_query_request_and_series_identity(
    region: Literal["default", "us", "eu"], host: str, endpoint: str, metric: str
) -> None:
    config = EmbraceSourceConfig(api_token="test-token", app_id='app"\\name', region=region)
    labels = {"__name__": metric, "app_id": config.app_id, "device_model": "example-device"}
    series: list[dict[str, object]] = [
        {"metric": labels, "values": [[END - 3600, "1"], [END, "2"]]},
        {"metric": dict(reversed(list(labels.items()))), "values": [[END - 7200, "3"]]},
        {"metric": {**labels, "device_model": "another-device"}, "values": [[END, "4"]]},
    ]
    with patch(
        "requests.sessions.Session.send", side_effect=lambda request, **kwargs: response(request, matrix(series))
    ) as send:
        rows = EmbraceClient(config, 1, "test-job", "v1").query(endpoint, END - 7200, END)
    send.assert_called_once()
    request = send.call_args.args[0]
    assert request.headers["Authorization"] == "Bearer test-token"
    assert request.url.startswith(f"https://{host}/metrics/api/v1/query_range?")
    assert parse_qs(urlparse(request.url).query) == {
        "query": [metric + "{app_id=" + json.dumps(config.app_id) + "}"],
        "start": [str(END - 7200)],
        "end": [str(END)],
        "step": ["3600"],
    }
    assert [row["value"] for row in rows] == [2.0, 4.0, 1.0, 3.0]
    assert rows[0]["series_id"] == rows[2]["series_id"] == rows[3]["series_id"]
    assert rows[0]["series_id"] != rows[1]["series_id"]
    assert rows[0]["labels"] == labels
    assert rows[0]["timestamp"] == datetime.fromtimestamp(END, UTC)


@pytest.mark.parametrize("value", ["NaN", "+Inf", "-Inf"])
def test_non_finite_samples(config: EmbraceSourceConfig, value: str) -> None:
    body = matrix([{"metric": {"app_id": "example-app"}, "values": [[END, value]]}])
    with patch("requests.sessions.Session.send", side_effect=lambda request, **kwargs: response(request, body)):
        rows = EmbraceClient(config, 1, "test-job", "v1").query("sessions", END, END)
    assert rows[0]["value"] is None


@pytest.mark.parametrize("incremental", [True, False])
@time_machine.travel(NOW, tick=False)
def test_windows_full_refresh_and_incremental(
    config: EmbraceSourceConfig, manager: MagicMock, incremental: bool
) -> None:
    inputs = MagicMock(spec=SourceInputs)
    inputs.schema_name = "sessions"
    inputs.team_id = 1
    inputs.job_id = "test-job"
    inputs.api_version = "v1"
    inputs.should_use_incremental_field = incremental
    inputs.db_incremental_field_last_value = datetime.fromtimestamp(END - 25 * 3600, UTC)

    def send_page(request: PreparedRequest, **kwargs: object) -> Response:
        params = parse_qs(urlparse(request.url or "").query)
        timestamp = int(params["end"][0])
        body = matrix([{"metric": {"app_id": "example-app"}, "values": [[timestamp, "7"]]}])
        return response(request, body)

    with patch("requests.sessions.Session.send", side_effect=send_page) as send:
        resource = EmbraceSource().source_for_pipeline(config, manager, inputs)
        batches = list(cast(Iterable[Any], resource.items()))
    assert resource.sort_mode == "desc"
    assert send.call_count == (2 if incremental else 30)
    params = [parse_qs(urlparse(call.args[0].url).query) for call in send.call_args_list]
    assert int(params[0]["end"][0]) == END
    for newer, older in zip(params, params[1:]):
        assert int(newer["start"][0]) - int(older["end"][0]) == 3600
    expected_start = END - (26 if incremental else 719) * 3600
    assert int(params[-1]["start"][0]) == expected_start
    assert all(int(page["end"][0]) - int(page["start"][0]) <= 23 * 3600 for page in params)
    assert len(batches) == send.call_count
    assert manager.save_state.call_args.args[0] == EmbraceResumeConfig(start=expected_start, end=expected_start - 3600)
    manager.clear_state.assert_not_called()
    assert resource.on_complete is not None
    resource.on_complete()
    manager.clear_state.assert_called_once()


@time_machine.travel(NOW, tick=False)
def test_resume_keeps_original_bounds_and_checks_empty_windows(config: EmbraceSourceConfig, manager: MagicMock) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = EmbraceResumeConfig(start=END - 25 * 3600, end=END - 3600)
    with patch(
        "requests.sessions.Session.send", side_effect=lambda request, **kwargs: response(request, matrix([]))
    ) as send:
        resource = embrace_source(config, "sessions", 1, "test-job", manager, None, "v1")
        assert list(cast(Iterable[Any], resource.items())) == []
    assert send.call_count == 2
    params = [parse_qs(urlparse(call.args[0].url).query) for call in send.call_args_list]
    assert params[0]["end"] == [str(END - 3600)]
    assert params[-1]["start"] == [str(END - 25 * 3600)]
    assert params[-1]["end"] == [str(END - 25 * 3600)]
    assert manager.safe_point.call_count == 2
    assert manager.save_state.call_count == 2


@pytest.mark.parametrize("last_value", ["2020-01-01T00:00:00Z", datetime(2020, 1, 1), datetime(2020, 1, 1, tzinfo=UTC)])
@time_machine.travel(NOW, tick=False)
def test_old_watermark_is_bounded(config: EmbraceSourceConfig, manager: MagicMock, last_value: datetime | str) -> None:
    with patch(
        "requests.sessions.Session.send", side_effect=lambda request, **kwargs: response(request, matrix([]))
    ) as send:
        resource = embrace_source(config, "sessions", 1, "test-job", manager, last_value, "v1")
        assert list(cast(Iterable[Any], resource.items())) == []
    assert send.call_count == 30
    assert manager.save_state.call_args.args[0].start == END - 719 * 3600


@time_machine.travel(NOW, tick=False)
def test_checkpoint_does_not_skip_failed_window(config: EmbraceSourceConfig, manager: MagicMock) -> None:
    calls = 0

    def send_page(request: PreparedRequest, **kwargs: object) -> Response:
        nonlocal calls
        calls += 1
        return response(request, matrix([]), status=200 if calls == 1 else 400)

    with patch("requests.sessions.Session.send", side_effect=send_page):
        resource = embrace_source(config, "sessions", 1, "test-job", manager, None, "v1")
        with pytest.raises(HTTPError):
            list(cast(Iterable[Any], resource.items()))
    manager.save_state.assert_called_once_with(EmbraceResumeConfig(start=END - 719 * 3600, end=END - 24 * 3600))
    manager.clear_state.assert_not_called()


@pytest.mark.parametrize(("status", "message"), [(401, "rejected the API token"), (403, "denied access")])
@time_machine.travel(NOW, tick=False)
def test_auth_errors(config: EmbraceSourceConfig, status: int, message: str) -> None:
    with patch(
        "requests.sessions.Session.send", side_effect=lambda request, **kwargs: response(request, {}, status)
    ) as send:
        valid, error = validate_credentials(config, 1, "sessions", "v1")
        assert not valid
        assert error is not None and message in error
        send.assert_called_once()
        with pytest.raises(HTTPError) as raised:
            EmbraceClient(config, 1, "test-job", "v1").query("sessions", END, END)
    assert any(pattern in str(raised.value) for pattern in EmbraceSource().get_non_retryable_errors())


@time_machine.travel(NOW, tick=False)
def test_validation_accepts_no_samples_and_uses_one_point(config: EmbraceSourceConfig) -> None:
    with patch(
        "requests.sessions.Session.send", side_effect=lambda request, **kwargs: response(request, matrix([]))
    ) as send:
        assert validate_credentials(config, 1, "sessions", "v1") == (True, None)
    send.assert_called_once()
    params = parse_qs(urlparse(send.call_args.args[0].url).query)
    assert params["start"] == params["end"] == [str(END)]


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_statuses_remain_retryable(config: EmbraceSourceConfig, status: int) -> None:
    with (
        patch("requests.sessions.Session.send", side_effect=lambda request, **kwargs: response(request, {}, status)),
        patch.object(RESTClient, "_send_request", cast(Any, RESTClient._send_request).__wrapped__),
        pytest.raises(RESTClientRetryableError),
    ):
        validate_credentials(config, 1, "sessions", "v1")


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"status": "error", "error": "query failed"}, "incomplete metrics query"),
        ({**matrix([]), "warnings": ["partial results"]}, "incomplete metrics query"),
        ({"status": "success", "data": {"resultType": "vector", "result": []}}, "unexpected metrics format"),
    ],
)
def test_query_errors_do_not_become_empty_success(
    config: EmbraceSourceConfig, body: dict[str, object], message: str
) -> None:
    with patch("requests.sessions.Session.send", side_effect=lambda request, **kwargs: response(request, body)):
        with pytest.raises(ValueError, match=message):
            EmbraceClient(config, 1, "test-job", "v1").query("sessions", END, END)


@pytest.mark.parametrize(
    ("region", "app_id", "endpoint", "version", "message"),
    [
        ("invalid", "example-app", "sessions", "v1", "Invalid Embrace region"),
        ("default", " ", "sessions", "v1", "Enter your Embrace app ID"),
        ("default", "example-app", "unknown", "v1", "Unknown Embrace table"),
        ("default", "example-app", "sessions", "v2", "Unsupported Embrace API version"),
    ],
)
def test_invalid_config_does_not_send_credentials(
    region: str, app_id: str, endpoint: str, version: str, message: str
) -> None:
    config = EmbraceSourceConfig(api_token="test-token", app_id=app_id, region=cast(Any, region))
    with patch("requests.sessions.Session.send") as send:
        valid, error = validate_credentials(config, 1, endpoint, version)
    assert not valid
    assert error is not None and message in error
    send.assert_not_called()
