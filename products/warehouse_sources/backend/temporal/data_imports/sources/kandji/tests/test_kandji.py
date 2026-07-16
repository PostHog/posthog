from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kandji.kandji import (
    build_base_url,
    get_resource,
    kandji_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kandji.settings import KANDJI_ENDPOINTS


class _FakeDltResource:
    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


class TestKandjiTransport:
    @parameterized.expand(
        [
            ("us", "accuhive", "us", "https://accuhive.api.kandji.io/api/v1"),
            ("eu", "accuhive", "eu", "https://accuhive.api.eu.kandji.io/api/v1"),
            ("region_case_insensitive", "accuhive", "US", "https://accuhive.api.kandji.io/api/v1"),
            ("subdomain_trimmed", "  accuhive  ", "us", "https://accuhive.api.kandji.io/api/v1"),
        ]
    )
    def test_build_base_url(self, _name, subdomain, region, expected) -> None:
        assert build_base_url(subdomain, region) == expected

    @parameterized.expand(
        [
            ("unknown_region", "accuhive", "apac"),
            ("empty_subdomain", "", "us"),
            ("subdomain_with_dot", "accuhive.api.kandji.io", "us"),
            ("subdomain_with_slash", "accuhive/devices", "us"),
        ]
    )
    def test_build_base_url_rejects_bad_input(self, _name, subdomain, region) -> None:
        with pytest.raises(ValueError):
            build_base_url(subdomain, region)

    @parameterized.expand(
        [
            ("unauthorized", 401, None, False),
            ("forbidden_at_create", 403, None, True),
            ("forbidden_for_schema", 403, "devices", False),
            ("ok", 200, None, True),
            ("unexpected", 500, None, False),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.kandji.kandji.make_tracked_session")
    def test_validate_credentials_status_mapping(
        self, _name, status_code, schema_name, expected_ok, mock_session
    ) -> None:
        response = Mock(status_code=status_code)
        mock_session.return_value.get.return_value = response

        is_valid, _message = validate_credentials(
            api_token="tok", subdomain="accuhive", region="us", schema_name=schema_name
        )

        assert is_valid is expected_ok

    def test_validate_credentials_rejects_bad_base_url_before_request(self) -> None:
        is_valid, message = validate_credentials(api_token="tok", subdomain="", region="us")
        assert is_valid is False
        assert message is not None

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.kandji.kandji.make_tracked_session")
    def test_validate_credentials_probes_devices_with_bearer(self, mock_session) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=200)

        validate_credentials(api_token="tok", subdomain="accuhive", region="us")

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://accuhive.api.kandji.io/api/v1/devices"
        assert call.kwargs["headers"]["Authorization"] == "Bearer tok"
        assert call.kwargs["params"] == {"limit": 1}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.kandji.kandji.make_tracked_session")
    def test_validate_credentials_handles_request_exception(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.exceptions.RequestException("boom")
        is_valid, message = validate_credentials(api_token="tok", subdomain="accuhive", region="us")
        assert is_valid is False
        assert message is not None and "boom" in message

    def test_get_resource_devices_bare_array_offset_paginated(self) -> None:
        resource = cast(dict[str, Any], get_resource(KANDJI_ENDPOINTS["devices"]))
        assert resource["name"] == "devices"
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["path"] == "/devices"
        # List Devices returns a bare array, paginated by limit/offset.
        assert resource["endpoint"]["data_selector"] == "$"
        assert isinstance(resource["endpoint"]["paginator"], OffsetPaginator)

    def test_get_resource_blueprints_wrapped_results(self) -> None:
        resource = cast(dict[str, Any], get_resource(KANDJI_ENDPOINTS["blueprints"]))
        assert resource["endpoint"]["data_selector"] == "results"
        paginator = resource["endpoint"]["paginator"]
        assert isinstance(paginator, OffsetPaginator)
        assert paginator.total_path == "count"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.kandji.kandji.rest_api_resource")
    def test_kandji_source_devices_top_level(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        response = kandji_source(
            api_token="tok",
            subdomain="accuhive",
            region="us",
            endpoint="devices",
            team_id=1,
            job_id="job-1",
        )

        assert response.name == "devices"
        assert response.primary_keys == ["device_id"]
        assert response.sort_mode == "asc"

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_kandji_source_device_apps_fanout_injects_parent_id(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("devices", [{"device_id": "dev_1"}]),
            _FakeDltResource("device_apps", [{"bundle_id": "com.apple.Safari", "_devices_device_id": "dev_1"}]),
        ]

        response = kandji_source(
            api_token="tok",
            subdomain="accuhive",
            region="us",
            endpoint="device_apps",
            team_id=1,
            job_id="job-1",
        )

        rows = list(cast(Any, response.items()))
        # The parent device id is injected onto each child row and renamed to device_id.
        assert rows == [{"bundle_id": "com.apple.Safari", "device_id": "dev_1"}]
        # bundle_id is only unique within a device, so the parent device id is part of the key.
        assert response.primary_keys == ["device_id", "bundle_id"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.kandji.kandji.build_dependent_resource")
    def test_kandji_source_fanout_wires_single_page_children(self, mock_build_dependent_resource) -> None:
        mock_build_dependent_resource.return_value = iter([])

        kandji_source(
            api_token="tok",
            subdomain="accuhive",
            region="us",
            endpoint="device_library_items",
            team_id=1,
            job_id="job-1",
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        # Kandji is full-refresh only — the fan-out must not request incremental merge behavior.
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
        assert kwargs["child_endpoint_extra"]["data_selector"] == "library_items"
        assert isinstance(kwargs["child_endpoint_extra"]["paginator"], SinglePagePaginator)
        # The devices parent lists a bare array.
        assert kwargs["parent_endpoint_extra"]["data_selector"] == "$"
        assert isinstance(kwargs["parent_endpoint_extra"]["paginator"], OffsetPaginator)
