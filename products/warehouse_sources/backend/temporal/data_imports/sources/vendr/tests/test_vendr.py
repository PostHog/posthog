from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.vendr.settings import VENDR_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.vendr.vendr import (
    VendrResumeConfig,
    _client_config,
    _get_resource,
    validate_credentials,
    vendr_source,
)


class _FakeResource:
    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


def _make_manager(resume_state: VendrResumeConfig | None = None) -> Mock:
    manager = Mock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


class TestVendrTransport:
    def test_client_config_uses_api_key_header_and_pins_host(self) -> None:
        config = _client_config("secret-key")

        assert config["base_url"] == "https://api.vendr.com"
        assert config["auth"] == {
            "type": "api_key",
            "api_key": "secret-key",
            "name": "X-API-Key",
            "location": "header",
        }
        # Vendr's base URL is fixed, so pin every request to it and never follow redirects
        # off-host - the API key rides in a custom (non-Authorization) header.
        assert config["allowed_hosts"] == []
        assert config["allow_redirects"] is False

    @parameterized.expand(
        [
            ("Companies", "/v1/catalog/companies", {"sortBy": "name", "sortOrder": "asc"}),
            ("Categories", "/v1/catalog/categories", {"sortBy": "name", "sortOrder": "asc"}),
        ]
    )
    def test_get_resource_top_level_endpoints(self, endpoint, expected_path, expected_params) -> None:
        resource = cast(dict[str, Any], _get_resource(VENDR_ENDPOINTS[endpoint]))

        assert resource["name"] == endpoint
        assert resource["write_disposition"] == "replace"
        assert resource["table_format"] == "delta"
        assert resource["endpoint"]["path"] == expected_path
        assert resource["endpoint"]["params"] == expected_params
        assert resource["endpoint"]["data_selector"] == "data"
        assert resource["endpoint"]["paginator"] == {"type": "offset", "limit": 100, "total_path": None}

    @parameterized.expand([("ProductFamilies",), ("Products",)])
    def test_get_resource_rejects_fanout_endpoints(self, endpoint) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            _get_resource(VENDR_ENDPOINTS[endpoint])

    @parameterized.expand(
        [
            (200, True, 200),
            (401, False, 401),
            (403, False, 403),
            (429, False, 429),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.vendr.vendr.make_tracked_session")
    def test_validate_credentials_status_mapping(self, status, expected_ok, expected_status, mock_session) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=status)

        result = validate_credentials("secret-key")

        assert result == (expected_ok, expected_status)
        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.vendr.com/v1/catalog/companies?limit=1"
        assert call.kwargs["headers"]["X-API-Key"] == "secret-key"
        assert call.kwargs["allow_redirects"] is False

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.vendr.vendr.rest_api_resource")
    def test_top_level_source_response(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()

        response = vendr_source(
            api_key="key",
            endpoint="Companies",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        assert response.name == "Companies"
        assert response.primary_keys == ["id"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.vendr.vendr.rest_api_resource")
    def test_top_level_source_resumes_from_saved_state(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = _make_manager(VendrResumeConfig(paginator_state={"offset": 200}))

        vendr_source(
            api_key="key",
            endpoint="Companies",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        assert mock_rest_api_resource.call_args.kwargs["initial_paginator_state"] == {"offset": 200}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.vendr.vendr.rest_api_resource")
    def test_top_level_source_saves_checkpoints_after_batches(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = _make_manager()

        vendr_source(
            api_key="key",
            endpoint="Companies",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        resume_hook = mock_rest_api_resource.call_args.kwargs["resume_hook"]
        resume_hook({"offset": 100})
        manager.save_state.assert_called_once_with(VendrResumeConfig(paginator_state={"offset": 100}))

        # A terminal (falsy) checkpoint is not persisted - the Redis TTL handles cleanup.
        manager.save_state.reset_mock()
        resume_hook(None)
        manager.save_state.assert_not_called()

    @parameterized.expand([("ProductFamilies",), ("Products",)])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.vendr.vendr.build_dependent_resource")
    def test_fanout_wiring(self, endpoint, mock_build_dependent_resource) -> None:
        mock_build_dependent_resource.return_value = _FakeResource(endpoint, [])
        manager = _make_manager()

        response = vendr_source(
            api_key="key",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["child_endpoint"] == endpoint
        assert kwargs["fanout"].parent_name == "Companies"
        assert kwargs["fanout"].resolve_param == "companyId"
        assert kwargs["fanout"].resolve_field == "id"
        assert kwargs["path_format_values"] == {}
        assert kwargs["page_size_param"] == "limit"
        assert kwargs["parent_endpoint_extra"] == {
            "paginator": {"type": "offset", "limit": 100, "total_path": None},
            "data_selector": "data",
        }
        assert kwargs["child_endpoint_extra"] == {
            "paginator": {"type": "offset", "limit": 100, "total_path": None},
            "data_selector": "data",
        }
        assert kwargs["child_params_extra"] == {"sortBy": "sortOrder", "sortOrder": "asc"}
        assert kwargs["resume_hook"] is not None
        assert response.primary_keys == ["id"]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_products_fanout_row_format(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeResource("Companies", [{"id": "co_1"}]),
            _FakeResource("Products", [{"id": "prod_1", "name": "Widget", "_Companies_id": "co_1"}]),
        ]

        response = vendr_source(
            api_key="key",
            endpoint="Products",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        assert list(cast(Any, response.items())) == [{"id": "prod_1", "name": "Widget", "company_id": "co_1"}]
        assert response.primary_keys == ["id"]
