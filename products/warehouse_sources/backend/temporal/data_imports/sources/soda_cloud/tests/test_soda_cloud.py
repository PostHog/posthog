import json
from base64 import b64encode
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Literal, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import ConnectionError, HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sodacloud import (
    SodaCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.soda_cloud.settings import (
    AUTH_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.soda_cloud.soda_cloud import SodaCloudResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.soda_cloud.source import SodaCloudSource


@pytest.fixture
def config() -> SodaCloudSourceConfig:
    return SodaCloudSourceConfig(api_key_id="fake-key-id", api_key_secret="fake-key-secret", region="eu")


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="datasets",
        schema_id="schema-test",
        source_id="source-test",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-test",
        logger=MagicMock(),
        reset_pipeline=False,
    )


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


def response_items(source_response: SourceResponse) -> Iterable[Any]:
    return cast(Iterable[Any], source_response.items())


def response(rows: list[dict[str, object]], total_pages: int = 1, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = {401: "Unauthorized", 403: "Forbidden"}.get(status, "Test response")
    result.url = "https://cloud.soda.io/api/v1/datasets"
    result.headers["Content-Type"] = "application/json"
    result._content = json.dumps({"content": rows, "totalPages": total_pages}).encode()
    return result


@pytest.mark.parametrize("region,host", [("eu", "cloud.soda.io"), ("us", "cloud.us.soda.io")])
@pytest.mark.parametrize("endpoint", ["datasets", "checks", "incidents"])
def test_paginated_requests_and_checkpoint(
    config: SodaCloudSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    region: Literal["eu", "us"],
    host: str,
    endpoint: str,
) -> None:
    config.region = region
    inputs.schema_name = endpoint
    rows: list[dict[str, object]] = [{"id": "row-one"}, {"id": "row-two"}]
    with patch("requests.sessions.Session.send", side_effect=[response(rows[:1], 2), response(rows[1:], 2)]) as send:
        source_response = SodaCloudSource().source_for_pipeline(config, manager, inputs)
        pages = iter(response_items(source_response))
        assert next(pages) == rows[:1]
        assert list(pages) == [rows[1:]]

    assert send.call_count == 2
    expected_auth = "Basic " + b64encode(b"fake-key-id:fake-key-secret").decode()
    for page, call in enumerate(send.call_args_list):
        request = call.args[0]
        assert request.method == "GET"
        assert urlsplit(request.url).netloc == host
        assert urlsplit(request.url).path == f"/api/v1/{endpoint}"
        assert parse_qs(urlsplit(request.url).query) == {"size": ["100"], "page": [str(page)]}
        assert request.headers["Authorization"] == expected_auth
        assert call.kwargs["allow_redirects"] is False
    manager.save_state.assert_called_once_with(SodaCloudResumeConfig(page=1))


@pytest.mark.parametrize("total_pages", [0, 3])
def test_empty_page_stops(
    config: SodaCloudSourceConfig, inputs: SourceInputs, manager: MagicMock, total_pages: int
) -> None:
    with patch("requests.sessions.Session.send", return_value=response([], total_pages)) as send:
        pages = list(response_items(SodaCloudSource().source_for_pipeline(config, manager, inputs)))
    assert not [row for page in pages for row in page]
    send.assert_called_once()
    manager.save_state.assert_not_called()


@pytest.mark.parametrize(
    "endpoint,incremental,watermark,expected_from",
    [
        ("datasets", True, None, None),
        ("datasets", True, datetime(2026, 1, 2, tzinfo=UTC), "2026-01-02T00:00:00+00:00"),
        ("datasets", True, "2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z"),
        ("datasets", False, "2026-01-02T00:00:00Z", None),
        ("checks", True, "2026-01-02T00:00:00Z", None),
        ("incidents", True, "2026-01-02T00:00:00Z", None),
    ],
)
def test_incremental_filter(
    config: SodaCloudSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    endpoint: str,
    incremental: bool,
    watermark: datetime | str | None,
    expected_from: str | None,
) -> None:
    inputs.schema_name = endpoint
    inputs.should_use_incremental_field = incremental
    inputs.db_incremental_field_last_value = watermark
    with patch("requests.sessions.Session.send", return_value=response([{"id": "row-one"}])) as send:
        source_response = SodaCloudSource().source_for_pipeline(config, manager, inputs)
        assert list(response_items(source_response)) == [[{"id": "row-one"}]]
    params = parse_qs(urlsplit(send.call_args.args[0].url).query)
    assert params.get("from") == ([expected_from] if expected_from else None)
    if endpoint == "datasets" and incremental:
        assert source_response.sort_mode == "desc"


@pytest.mark.parametrize("original_from", [None, "2026-01-01T00:00:00Z"])
def test_resume_retains_original_filter(
    config: SodaCloudSourceConfig, inputs: SourceInputs, manager: MagicMock, original_from: str | None
) -> None:
    inputs.should_use_incremental_field = True
    inputs.db_incremental_field_last_value = "2026-01-10T00:00:00Z"
    manager.can_resume.return_value = True
    manager.load_state.return_value = SodaCloudResumeConfig(page=4, from_datetime=original_from)
    with patch("requests.sessions.Session.send", return_value=response([{"id": "row-five"}], 5)) as send:
        assert list(response_items(SodaCloudSource().source_for_pipeline(config, manager, inputs))) == [
            [{"id": "row-five"}]
        ]
    params = parse_qs(urlsplit(send.call_args.args[0].url).query)
    assert params["page"] == ["4"]
    assert params.get("from") == ([original_from] if original_from else None)
    send.assert_called_once()
    manager.save_state.assert_not_called()


@pytest.mark.parametrize("status,message", [(401, AUTH_ERROR), (403, PERMISSION_ERROR)])
def test_sync_error_matches_non_retryable_message(
    config: SodaCloudSourceConfig, inputs: SourceInputs, manager: MagicMock, status: int, message: str
) -> None:
    source = SodaCloudSource()
    with patch("requests.sessions.Session.send", return_value=response([], status=status)) as send:
        with pytest.raises(HTTPError) as error:
            list(response_items(source.source_for_pipeline(config, manager, inputs)))
    send.assert_called_once()
    assert message in [value for key, value in source.get_non_retryable_errors().items() if key in str(error.value)]


@pytest.mark.parametrize(
    "status,expected",
    [
        (200, (True, None)),
        (401, (False, AUTH_ERROR)),
        (403, (False, PERMISSION_ERROR)),
        (429, (False, "Could not validate the Soda Cloud API keys. Try again later.")),
        (500, (False, "Could not validate the Soda Cloud API keys. Try again later.")),
        (302, (False, "Could not validate the Soda Cloud API keys. Try again later.")),
    ],
)
def test_credential_probe(config: SodaCloudSourceConfig, status: int, expected: tuple[bool, str | None]) -> None:
    config.region = "us"
    with patch("requests.sessions.Session.send", return_value=response([], status=status)) as send:
        assert SodaCloudSource().validate_credentials(config, team_id=1) == expected
    send.assert_called_once()
    request = send.call_args.args[0]
    assert urlsplit(request.url).netloc == "cloud.us.soda.io"
    assert parse_qs(urlsplit(request.url).query) == {"page": ["0"], "size": ["10"]}
    assert request.headers["Authorization"] == "Basic " + b64encode(b"fake-key-id:fake-key-secret").decode()
    assert send.call_args.kwargs["timeout"] == (10, 30)
    assert send.call_args.kwargs["allow_redirects"] is False


def test_connection_error_does_not_expose_credentials(config: SodaCloudSourceConfig) -> None:
    with patch("requests.sessions.Session.send", side_effect=ConnectionError(config.api_key_secret)):
        valid, message = SodaCloudSource().validate_credentials(config, team_id=1)
    assert not valid
    assert message == "Could not connect to Soda Cloud. Check the region and try again."


@pytest.mark.parametrize("region", ["", "https://example.com", "EU", "localhost"])
def test_invalid_region_never_sends_credentials(
    config: SodaCloudSourceConfig, inputs: SourceInputs, manager: MagicMock, region: str
) -> None:
    config.region = cast(Literal["eu", "us"], region)
    with patch("requests.sessions.Session.send") as send:
        valid, message = SodaCloudSource().validate_credentials(config, team_id=1)
        assert not valid
        assert message == "Select Europe or United States as the Soda Cloud region."
        with pytest.raises(ValueError, match="Select Europe"):
            SodaCloudSource().source_for_pipeline(config, manager, inputs)
    send.assert_not_called()


def test_invalid_endpoint_never_makes_request(
    config: SodaCloudSourceConfig, inputs: SourceInputs, manager: MagicMock
) -> None:
    inputs.schema_name = "../secrets"
    with patch("requests.sessions.Session.send") as send:
        with pytest.raises(ValueError, match="Unsupported Soda Cloud table"):
            SodaCloudSource().source_for_pipeline(config, manager, inputs)
    send.assert_not_called()
