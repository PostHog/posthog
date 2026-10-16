from typing import Any, cast

import pytest
from unittest.mock import Mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.census.census import (
    CensusResumeConfig,
    get_endpoint_permissions,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.census.source import CensusSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.census import CensusSourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(CensusSource(), CensusSourceConfig(api_key="key", region="us"))


def _page(rows: list[dict[str, Any]], last_page: int = 1) -> ScriptedResponse:
    return ScriptedResponse(json={"data": rows, "pagination": {"last_page": last_page}})


class TestCensusTransport:
    @parameterized.expand(
        [
            ("us", "https://app.getcensus.com"),
            ("eu", "https://app-eu.getcensus.com"),
            ("unknown", "https://app.getcensus.com"),  # unrecognized region falls back to US
        ]
    )
    def test_validate_credentials_uses_region_host(self, region, expected_host) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials(api_key="key", region=region)

        assert network.requests_log[0].url == f"{expected_host}/api/v1/syncs"
        assert network.requests_log[0].headers["authorization"] == "Bearer key"

    @parameterized.expand(
        [
            (200, None, True, None),
            (401, None, False, "Census rejected the API token. Generate a new workspace access token and reconnect."),
            (403, None, True, None),  # missing scope accepted at source-create
            (403, "syncs", False, "Your Census API token does not have access to this resource."),
            (500, None, False, "Census API returned an unexpected status: 500"),
        ]
    )
    def test_validate_credentials_status_mapping(self, status, schema_name, expected_valid, expected_message) -> None:
        with scripted_network(always(ScriptedResponse(status=status))):
            result = validate_credentials(api_key="key", region="us", schema_name=schema_name)

        assert result == (expected_valid, expected_message)

    def test_validate_credentials_network_failure(self) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            result = validate_credentials(api_key="key", region="us")

        assert result == (False, "Could not reach Census. Please check your network and selected region, then retry.")

    @parameterized.expand(
        [
            (200, None),
            (
                401,
                "Listing workspaces needs an organization-level Census API token. Reconnect with an organization token, or deselect this table.",
            ),
            (
                403,
                "Listing workspaces needs an organization-level Census API token. Reconnect with an organization token, or deselect this table.",
            ),
            (429, None),  # a throttle is not a refusal
            (500, None),
        ]
    )
    def test_get_endpoint_permissions_reports_refusals(self, status, expected_reason) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            permissions = get_endpoint_permissions(api_key="key", region="us", endpoints=["workspaces"])

        assert permissions == {"workspaces": expected_reason}
        assert {request.url for request in network.requests_log} == {"https://app.getcensus.com/api/v1/workspaces"}

    def test_get_endpoint_permissions_network_failure_is_not_a_refusal(self) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            assert get_endpoint_permissions(api_key="key", region="us", endpoints=["workspaces"]) == {
                "workspaces": None
            }

    def test_get_endpoint_permissions_skips_workspace_scoped_endpoints(self) -> None:
        # Every workspace token can read these, so probing them would only slow the schema picker.
        with scripted_network([]) as network:
            permissions = get_endpoint_permissions(
                api_key="key", region="us", endpoints=["syncs", "sync_runs", "sources", "destinations"]
            )

        assert permissions == {"syncs": None, "sync_runs": None, "sources": None, "destinations": None}
        assert network.requests_log == []

    def test_get_resource_full_refresh(self) -> None:
        resource = cast(dict[str, Any], get_resource(endpoint="syncs"))
        assert resource["name"] == "syncs"
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["path"] == "/api/v1/syncs"
        assert resource["endpoint"]["data_selector"] == "data"
        assert resource["endpoint"]["params"] == {"per_page": 100, "order": "asc"}
        assert isinstance(resource["endpoint"]["paginator"], PageNumberPaginator)
        assert resource["table_format"] == "delta"

    def test_get_resource_rejects_sync_runs_fanout(self) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource(endpoint="sync_runs")

    @parameterized.expand(
        [
            ("sources", "connection_details", {"user": "DEV"}),
            ("destinations", "connection_details", {"user": "DEV"}),
            ("workspaces", "notification_emails", ["alerts@example.com"]),
        ]
    )
    def test_get_resource_strips_sensitive_fields(self, endpoint, stripped_field, stripped_value) -> None:
        # `connection_details` carries warehouse account identifiers and `notification_emails`
        # carries people's addresses; neither belongs in a table any project member can query.
        resource = cast(dict[str, Any], get_resource(endpoint=endpoint))
        row = resource["data_map"]({"id": 1, "name": "Census", stripped_field: stripped_value})
        assert row == {"id": 1, "name": "Census"}

    def test_get_resource_syncs_keeps_all_fields(self) -> None:
        resource = cast(dict[str, Any], get_resource(endpoint="syncs"))
        assert "data_map" not in resource

    def test_probe_disables_sample_capture(self) -> None:
        # The `/syncs` probe response echoes `connection_details`; capturing it would persist the
        # warehouse account/user/warehouse identifiers to shared sample storage before any mapper runs.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials(api_key="key", region="us")

        assert network.session_options[0]["capture"] is False

    def test_client_session_disables_sample_capture(self) -> None:
        # Sync responses echo `connection_details` which `_drop_fields` strips per-row, but HTTP
        # sample capture records the raw body first — the client must run capture=False so that
        # metadata never reaches shared sample storage.
        result = _driver().run("syncs", [_page([{"id": 1}])])

        assert result.raised is None
        assert result.rows == [{"id": 1}]
        assert result.session_options[0]["capture"] is False
        assert result.session_options[0]["redact_values"] == ("key",)
        assert result.paths == ["/api/v1/syncs"]

    def test_census_source_top_level_response(self) -> None:
        result = _driver().run("syncs", [_page([])])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == "syncs"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    def test_census_source_resumes_from_saved_state(self) -> None:
        result = _driver().run(
            "syncs", [_page([{"id": 3}], last_page=3)], resume_state=CensusResumeConfig(paginator_state={"page": 3})
        )

        assert result.raised is None
        assert result.params("page") == ["3"]
        assert result.rows == [{"id": 3}]

    def test_census_source_saves_checkpoints_after_batches(self) -> None:
        result = _driver().run("syncs", [_page([{"id": 1}], last_page=2), _page([{"id": 2}], last_page=2)])

        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert result.saved_states == [CensusResumeConfig(paginator_state={"page": 2})]
        # A terminal (None) checkpoint is not persisted — the Redis TTL handles cleanup.
        assert result.final_state == CensusResumeConfig(paginator_state={"page": 2})

    def test_sync_runs_fanout_row_format(self) -> None:
        result = _driver().run(
            "sync_runs",
            [
                _page([{"id": 42}]),
                _page([{"id": 7, "status": "completed"}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": 7, "status": "completed", "sync_id": 42}]
        assert result.paths == ["/api/v1/syncs", "/api/v1/syncs/42/sync_runs"]
        # Run ids are only documented per-sync, so the parent sync id is part of the key.
        response = result.response
        assert response is not None
        assert response.primary_keys == ["sync_id", "id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.sort_mode == "asc"

    def test_sync_runs_fanout_wiring(self) -> None:
        result = _driver().run(
            "sync_runs",
            [
                _page([{"id": 42}], last_page=2),
                _page([{"id": 7}]),
                _page([{"id": 43}], last_page=2),
                _page([{"id": 8}]),
            ],
            resume_state=CensusResumeConfig(paginator_state={"completed": [], "current": None}),
        )

        assert result.raised is None
        assert result.paths == [
            "/api/v1/syncs",
            "/api/v1/syncs/42/sync_runs",
            "/api/v1/syncs",
            "/api/v1/syncs/43/sync_runs",
        ]
        assert result.params("per_page") == ["100"] * 4
        assert result.params("page") == ["1", "1", "2", "1"]
        assert result.params("order") == ["asc"] * 4
        assert result.requests[0].query == {"per_page": ("100",), "order": ("asc",), "page": ("1",)}
        assert result.rows == [{"id": 7, "sync_id": 42}, {"id": 8, "sync_id": 43}]
        assert result.saved_states


class TestCensusPageNumberPaginator:
    def test_stops_at_last_page(self) -> None:
        paginator = PageNumberPaginator(base_page=1, page_param="page", total_path="pagination.last_page")
        request = Mock()
        request.params = {}
        paginator.init_request(request)
        assert request.params["page"] == 1

        response = Mock()
        response.json.return_value = {"pagination": {"last_page": 1}, "data": [{"id": 1}]}
        paginator.update_state(response, data=[{"id": 1}])

        assert paginator.has_next_page is False

    def test_continues_before_last_page(self) -> None:
        paginator = PageNumberPaginator(base_page=1, page_param="page", total_path="pagination.last_page")

        response = Mock()
        response.json.return_value = {"pagination": {"last_page": 3}, "data": [{"id": 1}]}
        paginator.update_state(response, data=[{"id": 1}])

        assert paginator.has_next_page is True

        request = Mock()
        request.params = {}
        paginator.update_request(request)
        assert request.params["page"] == 2

    def test_resume_state_roundtrip(self) -> None:
        paginator = PageNumberPaginator(base_page=1, page_param="page", total_path="pagination.last_page")
        response = Mock()
        response.json.return_value = {"pagination": {"last_page": 5}, "data": [{"id": 1}]}
        paginator.update_state(response, data=[{"id": 1}])

        state = paginator.get_resume_state()
        assert state == {"page": 2}

        resumed = PageNumberPaginator(base_page=1, page_param="page", total_path="pagination.last_page")
        resumed.set_resume_state(cast(dict[str, Any], state))
        request = Mock()
        request.params = {}
        resumed.init_request(request)
        assert request.params["page"] == 2
