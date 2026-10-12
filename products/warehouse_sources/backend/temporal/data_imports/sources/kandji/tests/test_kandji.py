from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.kandji.kandji import (
    KandjiNextLinkPaginator,
    build_base_url,
    kandji_source,
    validate_credentials,
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
            # URL metacharacters would rewrite the request authority and leak the bearer token
            # to an attacker-controlled host (e.g. "attacker?" resolves to https://attacker/).
            ("subdomain_with_query", "attacker?", "us"),
            ("subdomain_with_fragment", "attacker#", "us"),
            ("subdomain_with_percent_encoding", "attacker%2eexample%2ecom", "us"),
            ("subdomain_with_userinfo", "user@attacker", "us"),
            ("subdomain_with_colon", "attacker:443", "us"),
            ("subdomain_leading_hyphen", "-accuhive", "us"),
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
    def test_validate_credentials_handles_request_exception(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.exceptions.RequestException("boom")
        is_valid, message = validate_credentials(api_token="tok", subdomain="accuhive", region="us")
        assert is_valid is False
        assert message is not None and "boom" in message

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


class TestKandjiNextLinkPaginator:
    def test_copies_next_query_onto_original_request(self) -> None:
        paginator = KandjiNextLinkPaginator()
        request = requests.Request(
            method="GET", url="https://accuhive.api.kandji.io/api/v1/users", params={"sizePerPage": 300}
        )
        response = Mock()
        # Kandji documents `next` links on the non-`api` host; the token must not follow them there.
        response.json.return_value = {"next": "https://accuhive.kandji.io/api/v1/users?cursor=cD0yOTE0Mw%3D%3D"}

        paginator.update_state(response, [{"id": "u1"}])
        paginator.update_request(request)

        assert paginator.has_next_page is True
        assert request.url == "https://accuhive.api.kandji.io/api/v1/users"
        assert request.params == {"sizePerPage": 300, "cursor": "cD0yOTE0Mw=="}

    @parameterized.expand(
        [
            ("null_next", [{"next": None}]),
            ("missing_next", [{"results": []}]),
            ("repeated_next", [{"next": "https://x/api/v1/library/custom-apps?page=2"}] * 2),
        ]
    )
    def test_stops_paging(self, _name, bodies) -> None:
        paginator = KandjiNextLinkPaginator()
        for body in bodies:
            response = Mock()
            response.json.return_value = body
            paginator.update_state(response, [])

        assert paginator.has_next_page is False
