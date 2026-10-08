from collections.abc import Iterable
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

import responses
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_meraki.cisco_meraki import (
    CiscoMerakiResumeConfig,
    cisco_meraki_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_meraki.settings import (
    AUTH_ERROR,
    NOT_FOUND_ERROR,
    ORGANIZATION_ERROR,
    PERMISSION_ERROR,
    REGION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_meraki.source import CiscoMerakiSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ciscomeraki import (
    CiscoMerakiSourceConfig,
)

BASE_URL = "https://api.meraki.com/api/v1/organizations/123456"


def make_config(**overrides: str) -> CiscoMerakiSourceConfig:
    return CiscoMerakiSourceConfig.from_dict(
        {"api_key": "fake-meraki-key", "organization_id": "123456", "region": "global", **overrides}
    )


def make_manager(resume: CiscoMerakiResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def rows(response: SourceResponse) -> list[dict[str, Any]]:
    return [row for page in cast(Iterable[list[dict[str, Any]]], response.items()) for row in page]


@pytest.mark.parametrize(
    ("endpoint", "path", "key", "page_size"),
    [
        ("networks", "networks", "id", 1000),
        ("devices", "devices", "serial", 1000),
        ("inventory_devices", "inventory/devices", "serial", 1000),
        ("uplink_statuses", "uplinks/statuses", "serial", 1000),
        ("assurance_alerts", "assurance/alerts", "id", 300),
    ],
)
@responses.activate
def test_full_refresh_pagination_and_auth(endpoint: str, path: str, key: str, page_size: int) -> None:
    next_url = f"{BASE_URL}/{path}?perPage={page_size}&startingAfter=next-token"
    responses.get(
        f"{BASE_URL}/{path}",
        json=[{key: "first"}],
        headers={"Link": f'<{next_url}>; rel="next", <{BASE_URL}/{path}>; rel="prev"'},
    )
    responses.get(next_url, json=[{key: "second"}], headers={"Link": f'<{BASE_URL}/{path}>; rel="prev"'})
    manager = make_manager()
    inputs = MagicMock(spec=SourceInputs)
    inputs.schema_name = endpoint
    inputs.team_id = 1
    inputs.job_id = "job"
    inputs.api_version = None
    inputs.should_use_incremental_field = False
    inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
    response = CiscoMerakiSource().source_for_pipeline(make_config(), manager, inputs)

    assert rows(response) == [{key: "first"}, {key: "second"}]
    assert response.primary_keys == [key]
    assert len(responses.calls) == 2
    assert parse_qs(urlsplit(responses.calls[0].request.url).query) == {"perPage": [str(page_size)]}
    assert responses.calls[1].request.url == next_url
    assert all(call.request.headers["X-Cisco-Meraki-API-Key"] == "fake-meraki-key" for call in responses.calls)
    assert [call.args[0] for call in manager.save_state.call_args_list] == [
        CiscoMerakiResumeConfig(next_url=next_url),
        CiscoMerakiResumeConfig(completed=True),
    ]
    manager.clear_state.assert_not_called()
    assert response.on_complete is not None
    response.on_complete()
    manager.clear_state.assert_called_once()


@pytest.mark.parametrize("empty", [False, True])
@responses.activate
def test_resume_starts_at_saved_page_and_marks_terminal_page(empty: bool) -> None:
    next_url = f"{BASE_URL}/networks?perPage=1000&startingAfter=saved-token"
    expected = [] if empty else [{"id": "last"}]
    responses.get(next_url, json=expected)
    manager = make_manager(CiscoMerakiResumeConfig(next_url=next_url))
    result = cisco_meraki_source(make_config(), "networks", "v1", 1, "job", manager)

    assert rows(result) == expected
    assert len(responses.calls) == 1
    assert responses.calls[0].request.url == next_url
    manager.save_state.assert_called_once_with(CiscoMerakiResumeConfig(completed=True))


@responses.activate
def test_completed_resume_does_not_repeat_terminal_page() -> None:
    manager = make_manager(CiscoMerakiResumeConfig(completed=True))
    result = cisco_meraki_source(make_config(), "networks", "v1", 1, "job", manager)

    assert rows(result) == []
    assert len(responses.calls) == 0
    assert result.on_complete is not None
    result.on_complete()
    manager.clear_state.assert_called_once()


@pytest.mark.parametrize(
    ("region", "host"),
    [
        ("global", "api.meraki.com"),
        ("canada", "api.meraki.ca"),
        ("china", "api.meraki.cn"),
        ("india", "api.meraki.in"),
        ("us_government", "api.gov-meraki.com"),
    ],
)
@responses.activate
def test_region_controls_probe_and_sync_hosts(region: str, host: str) -> None:
    base_url = f"https://{host}/api/v1/organizations/123456"
    responses.get(base_url, json={"id": "123456"})
    responses.get(f"{base_url}/networks", json=[{"id": "network"}])
    config = make_config(region=region)

    assert validate_credentials(config, "v1") == (True, None)
    result = cisco_meraki_source(config, "networks", "v1", 1, "job", make_manager())
    assert rows(result) == [{"id": "network"}]
    assert all(urlsplit(call.request.url).hostname == host for call in responses.calls)


@responses.activate
def test_auth_survives_meraki_shard_redirect() -> None:
    shard_url = "https://n123.meraki.com/api/v1/organizations/123456/networks"
    responses.get(f"{BASE_URL}/networks", status=308, headers={"Location": shard_url})
    responses.get(shard_url, json=[{"id": "network"}])

    result = cisco_meraki_source(make_config(), "networks", "v1", 1, "job", make_manager())

    assert rows(result) == [{"id": "network"}]
    assert responses.calls[-1].request.headers["X-Cisco-Meraki-API-Key"] == "fake-meraki-key"


@pytest.mark.parametrize(
    "location",
    [
        "https://example.com/steal",
        "http://api.meraki.com/steal",
        "https://api.meraki.com:8443/steal",
    ],
)
@responses.activate
def test_redirect_rejects_unapproved_destination(location: str) -> None:
    responses.get(f"{BASE_URL}/networks", status=308, headers={"Location": location})
    result = cisco_meraki_source(make_config(), "networks", "v1", 1, "job", make_manager())

    with pytest.raises(ValueError, match="unapproved destination"):
        rows(result)

    assert len(responses.calls) == 1


@responses.activate
def test_pagination_rejects_unapproved_destination() -> None:
    responses.get(
        f"{BASE_URL}/networks",
        json=[{"id": "first"}],
        headers={"Link": '<https://example.com/steal>; rel="next"'},
    )
    result = cisco_meraki_source(make_config(), "networks", "v1", 1, "job", make_manager())

    with pytest.raises(ValueError, match="unapproved destination"):
        rows(result)

    assert len(responses.calls) == 1


@responses.activate
def test_resume_rejects_unapproved_destination() -> None:
    manager = make_manager(CiscoMerakiResumeConfig(next_url="https://example.com/steal"))
    result = cisco_meraki_source(make_config(), "networks", "v1", 1, "job", manager)

    with pytest.raises(ValueError, match="unapproved destination"):
        rows(result)

    assert len(responses.calls) == 0


@pytest.mark.parametrize(
    ("status", "schema", "expected"),
    [
        (200, None, (True, None)),
        (200, "networks", (True, None)),
        (401, None, (False, AUTH_ERROR)),
        (403, None, (True, None)),
        (403, "networks", (False, PERMISSION_ERROR)),
        (404, None, (False, NOT_FOUND_ERROR)),
    ],
)
@responses.activate
def test_credential_status_mapping(status: int, schema: str | None, expected: tuple[bool, str | None]) -> None:
    url = f"{BASE_URL}/networks" if schema else BASE_URL
    body = [{"id": "network"}] if schema else {"id": "123456"}
    responses.get(
        url, status=status, json=body if status == 200 else {"errors": ["No valid authentication method found"]}
    )

    assert validate_credentials(make_config(), "v1", schema) == expected
    assert len(responses.calls) == 1
    request = responses.calls[0].request
    assert request.headers["X-Cisco-Meraki-API-Key"] == "fake-meraki-key"
    assert parse_qs(urlsplit(request.url).query) == ({"perPage": ["4"]} if schema else {})


@pytest.mark.parametrize(("status", "message"), [(401, AUTH_ERROR), (403, PERMISSION_ERROR), (404, NOT_FOUND_ERROR)])
@responses.activate
def test_sync_auth_errors_are_not_retried(status: int, message: str) -> None:
    responses.get(f"{BASE_URL}/networks", status=status, json={"errors": ["No valid authentication method found"]})
    result = cisco_meraki_source(make_config(), "networks", "v1", 1, "job", make_manager())

    with pytest.raises(HTTPError) as error:
        rows(result)

    matches = [
        value
        for pattern, value in CiscoMerakiSource().get_non_retryable_errors().items()
        if pattern in str(error.value)
    ]
    assert matches == [message]
    assert len(responses.calls) == 1


@pytest.mark.parametrize("status", [429, 500, 503])
@responses.activate
def test_transient_probe_failure_does_not_reject_credentials(status: int) -> None:
    responses.get(BASE_URL, status=status, json={"errors": ["Try again"]}, headers={"Retry-After": "0"})

    with patch.object(cast(Any, RESTClient._send_request).retry, "sleep"), pytest.raises(RESTClientRetryableError):
        validate_credentials(make_config(), "v1")

    assert len(responses.calls) > 1


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"region": "https://example.com"}, REGION_ERROR),
        ({"organization_id": "../other"}, ORGANIZATION_ERROR),
        ({"organization_id": "123?key=value"}, ORGANIZATION_ERROR),
        ({"organization_id": ""}, ORGANIZATION_ERROR),
    ],
)
@responses.activate
def test_invalid_connection_input_sends_no_request(overrides: dict[str, str], message: str) -> None:
    config = make_config(**overrides)
    assert validate_credentials(config, "v1") == (False, message)
    with pytest.raises(ValueError, match=message):
        cisco_meraki_source(config, "networks", "v1", 1, "job", make_manager())
    assert len(responses.calls) == 0


@responses.activate
def test_unknown_table_fails_before_network_access() -> None:
    with pytest.raises(UnknownResourceError):
        cisco_meraki_source(make_config(), "unknown", "v1", 1, "job", make_manager())
    with pytest.raises(UnknownResourceError):
        validate_credentials(make_config(), "v1", "unknown")
    assert len(responses.calls) == 0
