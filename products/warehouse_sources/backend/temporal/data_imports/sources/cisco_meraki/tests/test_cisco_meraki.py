from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
import time_machine
from unittest.mock import MagicMock

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
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ciscomeraki import (
    CiscoMerakiSourceConfig,
)

API_URL = "https://api.meraki.com/api/v1"
BASE_URL = f"{API_URL}/organizations/123456"


def make_config(**overrides: str) -> CiscoMerakiSourceConfig:
    return CiscoMerakiSourceConfig.from_dict(
        {"api_key": "fake-meraki-key", "organization_id": "123456", "region": "global", **overrides}
    )


def make_driver(**overrides: str) -> SourceDriver:
    return SourceDriver(CiscoMerakiSource(), make_config(**overrides))


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
        ("device_availabilities", "devices/availabilities", "serial", 1000),
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
def test_resume_starts_at_saved_page_and_marks_terminal_page(empty: bool) -> None:
    next_url = f"{BASE_URL}/networks?perPage=1000&startingAfter=saved-token"
    expected = [] if empty else [{"id": "last"}]
    result = make_driver().run(
        "networks", [ScriptedResponse(json=expected)], resume_state=CiscoMerakiResumeConfig(next_url=next_url)
    )

    assert result.raised is None
    assert result.rows == expected
    assert result.urls == [next_url]
    assert result.saved_states == [CiscoMerakiResumeConfig(completed=True)]


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
def test_region_controls_probe_and_sync_hosts(region: str, host: str) -> None:
    base_url = f"https://{host}/api/v1/organizations/123456"
    config = make_config(region=region)

    with scripted_network([ScriptedResponse(json={"id": "123456"})]) as network:
        assert validate_credentials(config, "v1") == (True, None)
    result = SourceDriver(CiscoMerakiSource(), config).run("networks", [ScriptedResponse(json=[{"id": "network"}])])

    assert result.raised is None
    assert result.rows == [{"id": "network"}]
    assert [request.url for request in network.requests_log] == [base_url]
    assert result.urls == [f"{base_url}/networks?perPage=1000"]
    assert all(urlsplit(request.url).hostname == host for request in [*network.requests_log, *result.requests])


def test_auth_survives_meraki_shard_redirect() -> None:
    shard_url = "https://n123.meraki.com/api/v1/organizations/123456/networks"
    result = make_driver().run(
        "networks",
        [ScriptedResponse(status=308, headers={"Location": shard_url}), ScriptedResponse(json=[{"id": "network"}])],
    )

    assert result.raised is None
    assert result.rows == [{"id": "network"}]
    assert result.requests[-1].url == shard_url
    assert result.requests[-1].headers["x-cisco-meraki-api-key"] == "fake-meraki-key"


@pytest.mark.parametrize(
    "location",
    [
        "https://example.com/steal",
        "http://api.meraki.com/steal",
        "https://api.meraki.com:8443/steal",
    ],
)
def test_redirect_rejects_unapproved_destination(location: str) -> None:
    result = make_driver().run("networks", [ScriptedResponse(status=308, headers={"Location": location})])

    assert isinstance(result.raised, ValueError)
    assert "unapproved destination" in str(result.raised)
    assert len(result.requests) == 1


def test_pagination_rejects_unapproved_destination() -> None:
    result = make_driver().run(
        "networks",
        [ScriptedResponse(json=[{"id": "first"}], headers={"Link": '<https://example.com/steal>; rel="next"'})],
    )

    assert isinstance(result.raised, ValueError)
    assert "unapproved destination" in str(result.raised)
    assert len(result.requests) == 1


def test_resume_rejects_unapproved_destination() -> None:
    result = make_driver().run(
        "networks", [], resume_state=CiscoMerakiResumeConfig(next_url="https://example.com/steal")
    )

    assert isinstance(result.raised, ValueError)
    assert "unapproved destination" in str(result.raised)
    assert result.requests == []


@pytest.mark.parametrize(
    ("status", "schema", "expected"),
    [
        (403, None, (True, None)),
        (403, "networks", (False, PERMISSION_ERROR)),
        (403, "network_events", (False, PERMISSION_ERROR)),
        (404, None, (False, NOT_FOUND_ERROR)),
    ],
)
def test_credential_status_mapping(status: int, schema: str | None, expected: tuple[bool, str | None]) -> None:
    body = [{"id": "network"}] if schema else {"id": "123456"}
    answer = ScriptedResponse(
        status=status, json=body if status == 200 else {"errors": ["No valid authentication method found"]}
    )

    with scripted_network([answer]) as network:
        assert validate_credentials(make_config(), "v1", schema) == expected

    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.headers["x-cisco-meraki-api-key"] == "fake-meraki-key"
    assert request.path == f"/api/v1/organizations/123456{'/networks' if schema else ''}"
    assert request.query == ({"perPage": ("4",)} if schema else {})


@pytest.mark.parametrize(("status", "message"), [(401, AUTH_ERROR), (403, PERMISSION_ERROR), (404, NOT_FOUND_ERROR)])
def test_sync_auth_errors_are_not_retried(status: int, message: str) -> None:
    result = make_driver().run(
        "networks", [ScriptedResponse(status=status, json={"errors": ["No valid authentication method found"]})]
    )

    assert isinstance(result.raised, HTTPError)
    matches = [
        value
        for pattern, value in CiscoMerakiSource().get_non_retryable_errors().items()
        if pattern in str(result.raised)
    ]
    assert matches == [message]
    assert len(result.requests) == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_probe_failure_does_not_reject_credentials(status: int) -> None:
    answer = ScriptedResponse(status=status, json={"errors": ["Try again"]}, headers={"Retry-After": "0"})
    with scripted_network(always(answer)) as network:
        with pytest.raises(RESTClientRetryableError):
            validate_credentials(make_config(), "v1")

    assert len(network.requests_log) > 1


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"region": "https://example.com"}, REGION_ERROR),
        ({"organization_id": "../other"}, ORGANIZATION_ERROR),
        ({"organization_id": "123?key=value"}, ORGANIZATION_ERROR),
        ({"organization_id": ""}, ORGANIZATION_ERROR),
    ],
)
def test_invalid_connection_input_sends_no_request(overrides: dict[str, str], message: str) -> None:
    config = make_config(**overrides)
    with scripted_network([]) as network:
        assert validate_credentials(config, "v1") == (False, message)
    result = SourceDriver(CiscoMerakiSource(), config).run("networks", [])

    assert isinstance(result.raised, ValueError)
    assert str(result.raised) == message
    assert network.requests_log == []
    assert result.requests == []


def test_unknown_table_fails_before_network_access() -> None:
    result = make_driver().run("unknown", [])
    with scripted_network([]) as network:
        with pytest.raises(UnknownResourceError):
            validate_credentials(make_config(), "v1", "unknown")

    assert isinstance(result.raised, UnknownResourceError)
    assert result.requests == []
    assert network.requests_log == []


def network_api(routes: dict[tuple[str, str | None], ScriptedResponse]) -> Any:
    def answer(request: RecordedRequest) -> ScriptedResponse:
        path = request.path
        if product_type := request.param("productType"):
            path = f"{path}?productType={product_type}"
        return routes[(path, request.param("endingBefore") or request.param("startingAfter"))]

    return answer


def test_network_clients_fan_out_over_every_network_page() -> None:
    next_clients = f"{API_URL}/networks/N_1/clients?perPage=1000&timespan=2678400&startingAfter=k2"
    result = make_driver().run(
        "network_clients",
        network_api(
            {
                ("/api/v1/organizations/123456/networks", None): ScriptedResponse(json=[{"id": "N_1"}, {"id": "N_2"}]),
                ("/api/v1/networks/N_1/clients", None): ScriptedResponse(
                    json=[{"id": "k1"}], headers={"Link": f'<{next_clients}>; rel="next"'}
                ),
                ("/api/v1/networks/N_1/clients", "k2"): ScriptedResponse(json=[{"id": "k2"}]),
                ("/api/v1/networks/N_2/clients", None): ScriptedResponse(json=[{"id": "k1"}]),
            }
        ),
    )

    assert result.raised is None
    assert [(row["networkId"], row["id"]) for row in result.rows] == [("N_1", "k1"), ("N_1", "k2"), ("N_2", "k1")]
    assert [request.param("timespan") for request in result.requests[1:]] == ["2678400"] * 3


def test_network_clients_resume_skips_completed_networks() -> None:
    result = make_driver().run(
        "network_clients",
        network_api(
            {
                ("/api/v1/organizations/123456/networks", None): ScriptedResponse(json=[{"id": "N_1"}, {"id": "N_2"}]),
                ("/api/v1/networks/N_2/clients", None): ScriptedResponse(json=[{"id": "k9"}]),
            }
        ),
        resume_state=CiscoMerakiResumeConfig(completed_paths=["networks/N_1/clients"]),
    )

    assert result.raised is None
    assert result.rows == [{"id": "k9", "networkId": "N_2"}]
    assert result.final_state == CiscoMerakiResumeConfig(
        completed_paths=["networks/N_1/clients", "networks/N_2/clients"]
    )


def _event(occurred_at: str) -> dict[str, Any]:
    return {"occurredAt": occurred_at, "networkId": "N_1", "type": "association"}


@pytest.mark.parametrize(
    ("watermark", "expected_pages"),
    [
        (None, [None, "2026-01-02T00:00:00Z", "2026-01-01T06:00:00Z", "2025-12-31T00:00:00Z"]),
        (datetime(2026, 1, 1, tzinfo=UTC), [None, "2026-01-02T00:00:00Z", "2026-01-01T06:00:00Z"]),
    ],
)
def test_network_events_walk_back_per_product_type(
    watermark: datetime | None, expected_pages: list[str | None]
) -> None:
    def page(events: list[dict[str, Any]], older_than: str) -> ScriptedResponse:
        prev_url = f"{API_URL}/networks/N_1/events?productType=appliance&perPage=1000&endingBefore={older_than}"
        return ScriptedResponse(json={"events": events}, headers={"Link": f'<{prev_url}>; rel="prev"'})

    appliance_path = "/api/v1/networks/N_1/events?productType=appliance"
    result = make_driver().run(
        "network_events",
        network_api(
            {
                ("/api/v1/organizations/123456/networks", None): ScriptedResponse(
                    json=[{"id": "N_1", "productTypes": ["appliance", "sensor", "wireless"]}]
                ),
                ("/api/v1/networks/N_1/events?productType=wireless", None): ScriptedResponse(json={"events": []}),
                (appliance_path, None): page(
                    [_event("2026-01-03T00:00:00Z"), _event("2026-01-02T00:00:00Z")], "2026-01-02T00:00:00Z"
                ),
                (appliance_path, "2026-01-02T00:00:00Z"): page([], "2026-01-01T06:00:00Z"),
                (appliance_path, "2026-01-01T06:00:00Z"): page(
                    [_event("2026-01-01T05:00:00Z"), _event("2025-12-31T00:00:00Z")], "2025-12-31T00:00:00Z"
                ),
                (appliance_path, "2025-12-31T00:00:00Z"): page([], "2013-12-31T00:00:00Z"),
            }
        ),
        incremental_field="occurredAt" if watermark else None,
        db_incremental_field_last_value=watermark,
    )

    appliance = [request for request in result.requests if request.param("productType") == "appliance"]
    assert result.raised is None
    assert [request.param("endingBefore") for request in appliance] == expected_pages
    assert {request.param("productType") for request in result.requests[1:]} == {"appliance", "wireless"}
    assert {row["productType"] for row in result.rows} == {"appliance"}
    assert len({row["id"] for row in result.rows}) == len(result.rows) == 4


NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
NETWORKS_PATH = "/api/v1/organizations/123456/networks"


def _usage_history(client_id: str, ts: str) -> dict[str, Any]:
    return {
        "clientId": client_id,
        "clientIp": "192.0.2.10",
        "clientMac": "00:00:5e:00:53:01",
        "usageHistory": [{"ts": ts, "sent": 10.0, "received": 20.0}],
    }


@time_machine.travel(NOW, tick=False)
@pytest.mark.parametrize(
    ("endpoint", "child_path", "watermark", "expected_timespan"),
    [
        ("uplink_usage_history", "/api/v1/networks/N_1/appliance/uplinks/usageHistory", None, "2592000"),
        (
            "uplink_usage_history",
            "/api/v1/networks/N_1/appliance/uplinks/usageHistory",
            datetime(2026, 2, 26, 12, 0, tzinfo=UTC),
            "259200",
        ),
        (
            "uplink_usage_history",
            "/api/v1/networks/N_1/appliance/uplinks/usageHistory",
            datetime(2026, 3, 1, 11, 50, tzinfo=UTC),
            "7200",
        ),
        (
            "uplink_usage_history",
            "/api/v1/networks/N_1/appliance/uplinks/usageHistory",
            "2025-12-01T00:00:00Z",
            "2592000",
        ),
        ("client_usage_histories", "/api/v1/networks/N_1/clients/usageHistories", None, "2678400"),
        (
            "client_usage_histories",
            "/api/v1/networks/N_1/clients/usageHistories",
            datetime(2026, 2, 26, 12, 0, tzinfo=UTC),
            "259200",
        ),
        (
            "client_usage_histories",
            "/api/v1/networks/N_1/clients/usageHistories",
            "2026-03-01T00:00:00Z",
            "86400",
        ),
        (
            "client_usage_histories",
            "/api/v1/networks/N_1/clients/usageHistories",
            datetime(2025, 12, 1, tzinfo=UTC),
            "2678400",
        ),
    ],
)
def test_usage_history_timespan_follows_watermark(
    endpoint: str, child_path: str, watermark: datetime | str | None, expected_timespan: str
) -> None:
    result = make_driver().run(
        endpoint,
        network_api(
            {
                (NETWORKS_PATH, None): ScriptedResponse(json=[{"id": "N_1", "productTypes": ["appliance"]}]),
                ("/api/v1/networks/N_1/clients", None): ScriptedResponse(json=[{"id": "k1"}]),
                (child_path, None): ScriptedResponse(json=[]),
            }
        ),
        incremental_field="startTime" if endpoint == "uplink_usage_history" else "ts",
        should_use_incremental_field=watermark is not None,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    timespans = {request.path: request.param("timespan") for request in result.requests[1:]}
    assert timespans[child_path] == expected_timespan
    if endpoint == "client_usage_histories":
        assert timespans["/api/v1/networks/N_1/clients"] == expected_timespan


def test_full_refresh_ignores_stored_watermark() -> None:
    result = make_driver().run(
        "uplink_usage_history",
        network_api(
            {
                (NETWORKS_PATH, None): ScriptedResponse(json=[{"id": "N_1", "productTypes": ["appliance"]}]),
                ("/api/v1/networks/N_1/appliance/uplinks/usageHistory", None): ScriptedResponse(json=[]),
            }
        ),
        incremental_field="startTime",
        should_use_incremental_field=False,
        db_incremental_field_last_value=datetime.now(UTC),
    )

    assert result.raised is None
    assert result.requests[-1].param("timespan") == "2592000"


def test_uplink_usage_history_reads_only_appliance_networks() -> None:
    interval = {
        "startTime": "2026-01-01T00:00:00Z",
        "endTime": "2026-01-01T01:00:00Z",
        "byInterface": [{"interface": "wan1", "sent": 100, "received": 200}],
    }
    result = make_driver().run(
        "uplink_usage_history",
        network_api(
            {
                (NETWORKS_PATH, None): ScriptedResponse(
                    json=[
                        {"id": "N_1", "productTypes": ["appliance", "switch"]},
                        {"id": "N_2", "productTypes": ["wireless"]},
                        {"id": "N_3", "productTypes": []},
                    ]
                ),
                # A Link header on this endpoint must not start a second request.
                ("/api/v1/networks/N_1/appliance/uplinks/usageHistory", None): ScriptedResponse(
                    json=[interval],
                    headers={"Link": f'<{API_URL}/networks/N_1/appliance/uplinks/usageHistory?page=2>; rel="next"'},
                ),
            }
        ),
    )

    assert result.raised is None
    assert result.rows == [{**interval, "networkId": "N_1"}]
    assert [request.path for request in result.requests] == [
        NETWORKS_PATH,
        "/api/v1/networks/N_1/appliance/uplinks/usageHistory",
    ]
    assert result.requests[1].query == {"timespan": ("2592000",), "resolution": ("3600",)}
    assert result.response is not None
    assert result.response.sort_mode is None
    assert result.response.partition_keys == ["startTime"]


def test_client_usage_histories_batch_client_keys_for_each_network() -> None:
    usage_path = "/api/v1/networks/N_1/clients/usageHistories"
    next_clients = f"{API_URL}/networks/N_1/clients?perPage=1000&timespan=2678400&startingAfter=k120"

    def answer(request: RecordedRequest) -> ScriptedResponse:
        if request.path == usage_path:
            keys = (request.param("clients") or "").split(",")
            return ScriptedResponse(json=[_usage_history(key, "2026-01-01T00:00:00Z") for key in keys[:1]])
        return network_api(
            {
                (NETWORKS_PATH, None): ScriptedResponse(
                    json=[{"id": "N_1"}, {"id": "N_2"}, {"id": "N_3"}],
                    headers={"Link": f'<{API_URL}/organizations/123456/networks?startingAfter=N_3>; rel="next"'},
                ),
                (NETWORKS_PATH, "N_3"): ScriptedResponse(json=[]),
                ("/api/v1/networks/N_1/clients", None): ScriptedResponse(
                    json=[{"id": f"k{index}"} for index in range(120)],
                    headers={"Link": f'<{next_clients}>; rel="next"'},
                ),
                ("/api/v1/networks/N_1/clients", "k120"): ScriptedResponse(json=[{"id": "k120"}]),
                ("/api/v1/networks/N_2/clients", None): ScriptedResponse(json=[]),
                ("/api/v1/networks/N_3/clients", None): ScriptedResponse(json=[{"id": "k1"}]),
                ("/api/v1/networks/N_3/clients/usageHistories", None): ScriptedResponse(
                    json=[{"clientId": "k1", "usageHistory": []}]
                ),
            }
        )(request)

    result = make_driver().run("client_usage_histories", answer)

    assert result.raised is None
    usage_requests = [request for request in result.requests if request.path.endswith("/usageHistories")]
    assert [len((request.param("clients") or "").split(",")) for request in usage_requests] == [100, 20, 1, 1]
    assert [request.param("clients") for request in usage_requests][2:] == ["k120", "k1"]
    assert [(row["networkId"], row["clientId"], row["ts"]) for row in result.rows] == [
        ("N_1", "k0", "2026-01-01T00:00:00Z"),
        ("N_1", "k100", "2026-01-01T00:00:00Z"),
        ("N_1", "k120", "2026-01-01T00:00:00Z"),
    ]
    assert result.rows[0] == {
        "networkId": "N_1",
        "clientId": "k0",
        "clientIp": "192.0.2.10",
        "clientMac": "00:00:5e:00:53:01",
        "ts": "2026-01-01T00:00:00Z",
        "sent": 10.0,
        "received": 20.0,
    }
    assert result.completed_state is None


def test_client_usage_histories_resume_skips_completed_networks() -> None:
    result = make_driver().run(
        "client_usage_histories",
        network_api(
            {
                (NETWORKS_PATH, None): ScriptedResponse(json=[{"id": "N_1"}, {"id": "N_2"}, {"id": "N_3"}]),
                ("/api/v1/networks/N_2/clients", None): ScriptedResponse(json=[{"id": "k9"}]),
                ("/api/v1/networks/N_2/clients/usageHistories", None): ScriptedResponse(
                    json=[_usage_history("k9", "2026-01-02T00:00:00Z")]
                ),
                ("/api/v1/networks/N_3/clients", None): ScriptedResponse(json=[]),
            }
        ),
        resume_state=CiscoMerakiResumeConfig(completed_paths=["networks/N_1/clients/usageHistories"]),
    )

    assert result.raised is None
    assert [row["clientId"] for row in result.rows] == ["k9"]
    assert not any(request.path.startswith("/api/v1/networks/N_1/") for request in result.requests)
    assert result.final_state == CiscoMerakiResumeConfig(
        completed_paths=["networks/N_1/clients/usageHistories", "networks/N_2/clients/usageHistories"]
    )
