from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.census.census import (
    CensusResumeConfig,
    census_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)


class _FakeDltResource:
    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


def _make_manager(resume_state: CensusResumeConfig | None = None) -> Mock:
    manager = Mock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


class TestCensusTransport:
    @parameterized.expand(
        [
            ("us", "https://app.getcensus.com"),
            ("eu", "https://app-eu.getcensus.com"),
            ("unknown", "https://app.getcensus.com"),  # unrecognized region falls back to US
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.census.census.make_tracked_session")
    def test_validate_credentials_uses_region_host(self, region, expected_host, mock_session) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=200)

        validate_credentials(api_key="key", region=region)

        call = mock_session.return_value.get.call_args
        assert call.args[0] == f"{expected_host}/api/v1/syncs"
        assert call.kwargs["headers"]["Authorization"] == "Bearer key"

    @parameterized.expand(
        [
            (200, None, True, None),
            (401, None, False, "Census rejected the API token. Generate a new workspace access token and reconnect."),
            (403, None, True, None),  # missing scope accepted at source-create
            (403, "syncs", False, "Your Census API token does not have access to this resource."),
            (500, None, False, "Census API returned an unexpected status: 500"),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.census.census.make_tracked_session")
    def test_validate_credentials_status_mapping(
        self, status, schema_name, expected_valid, expected_message, mock_session
    ) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=status)

        result = validate_credentials(api_key="key", region="us", schema_name=schema_name)

        assert result == (expected_valid, expected_message)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.census.census.make_tracked_session")
    def test_validate_credentials_network_failure(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")

        result = validate_credentials(api_key="key", region="us")

        assert result == (False, "Could not reach Census. Please check your network and selected region, then retry.")

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

    @parameterized.expand([("sources",), ("destinations",)])
    def test_get_resource_strips_connection_details(self, endpoint) -> None:
        # `connection_details` carries warehouse account identifiers that must not land in a
        # queryable warehouse table.
        resource = cast(dict[str, Any], get_resource(endpoint=endpoint))
        row = resource["data_map"]({"id": 1, "name": "Snowflake", "connection_details": {"user": "DEV"}})
        assert row == {"id": 1, "name": "Snowflake"}

    def test_get_resource_syncs_keeps_all_fields(self) -> None:
        resource = cast(dict[str, Any], get_resource(endpoint="syncs"))
        assert "data_map" not in resource

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.census.census.make_tracked_session")
    def test_probe_disables_sample_capture(self, mock_session) -> None:
        # The `/syncs` probe response echoes `connection_details`; capturing it would persist the
        # warehouse account/user/warehouse identifiers to shared sample storage before any mapper runs.
        mock_session.return_value.get.return_value = Mock(status_code=200)

        validate_credentials(api_key="key", region="us")

        assert mock_session.call_args.kwargs["capture"] is False

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.census.census.make_tracked_session")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.census.census.rest_api_resource")
    def test_client_session_disables_sample_capture(self, mock_rest_api_resource, mock_session) -> None:
        # Sync responses echo `connection_details` which `_drop_fields` strips per-row, but HTTP
        # sample capture records the raw body first — the client must run capture=False so that
        # metadata never reaches shared sample storage.
        mock_rest_api_resource.return_value = Mock()

        census_source(
            api_key="key",
            region="us",
            endpoint="syncs",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        assert mock_session.call_args.kwargs["capture"] is False
        assert mock_rest_api_resource.call_args.args[0]["client"]["session"] is mock_session.return_value

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.census.census.rest_api_resource")
    def test_census_source_top_level_response(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        response = census_source(
            api_key="key",
            region="us",
            endpoint="syncs",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        assert response.name == "syncs"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.census.census.rest_api_resource")
    def test_census_source_resumes_from_saved_state(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = _make_manager(CensusResumeConfig(paginator_state={"page": 3}))

        census_source(
            api_key="key",
            region="us",
            endpoint="syncs",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        kwargs = mock_rest_api_resource.call_args.kwargs
        assert kwargs["initial_paginator_state"] == {"page": 3}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.census.census.rest_api_resource")
    def test_census_source_saves_checkpoints_after_batches(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = _make_manager()

        census_source(
            api_key="key",
            region="us",
            endpoint="syncs",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        resume_hook = mock_rest_api_resource.call_args.kwargs["resume_hook"]
        resume_hook({"page": 2})
        manager.save_state.assert_called_once_with(CensusResumeConfig(paginator_state={"page": 2}))

        # A terminal (None) checkpoint is not persisted — the Redis TTL handles cleanup.
        manager.save_state.reset_mock()
        resume_hook(None)
        manager.save_state.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_sync_runs_fanout_row_format(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("syncs", [{"id": 42}]),
            _FakeDltResource("sync_runs", [{"id": 7, "status": "completed", "_syncs_id": 42}]),
        ]

        response = census_source(
            api_key="key",
            region="us",
            endpoint="sync_runs",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        rows = list(cast(Any, response.items()))
        assert rows == [{"id": 7, "status": "completed", "sync_id": 42}]
        # Run ids are only documented per-sync, so the parent sync id is part of the key.
        assert response.primary_keys == ["sync_id", "id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.sort_mode == "asc"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.census.census.build_dependent_resource")
    def test_sync_runs_fanout_wiring(self, mock_build_dependent_resource) -> None:
        mock_build_dependent_resource.return_value = iter([])
        manager = _make_manager(CensusResumeConfig(paginator_state={"completed": [], "current": None}))

        census_source(
            api_key="key",
            region="us",
            endpoint="sync_runs",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["page_size_param"] == "per_page"
        assert "params" not in kwargs["parent_endpoint_extra"]
        assert kwargs["parent_endpoint_extra"]["data_selector"] == "data"
        assert kwargs["child_endpoint_extra"]["data_selector"] == "data"
        assert isinstance(kwargs["parent_endpoint_extra"]["paginator"], PageNumberPaginator)
        assert isinstance(kwargs["child_endpoint_extra"]["paginator"], PageNumberPaginator)
        assert kwargs["child_params_extra"] == {"order": "asc"}
        assert kwargs["db_incremental_field_last_value"] is None
        assert kwargs["resume_hook"] is not None
        assert kwargs["initial_paginator_state"] == {"completed": [], "current": None}


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
