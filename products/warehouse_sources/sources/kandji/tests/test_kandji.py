from typing import Any

import pytest
from unittest.mock import Mock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.kandji._config import KandjiSourceConfig
from products.warehouse_sources.sources.kandji.kandji import (
    KandjiNextLinkPaginator,
    KandjiResumeConfig,
    build_base_url,
    kandji_source,
    validate_credentials,
)
from products.warehouse_sources.sources.kandji.source import KandjiSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network


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
    def test_validate_credentials_status_mapping(
        self, _name: str, status_code: int, schema_name: str | None, expected_ok: bool
    ) -> None:
        response = ScriptedResponse(status=status_code)
        with scripted_network(always(response) if status_code == 500 else [response]) as network:
            is_valid, _message = validate_credentials(
                api_token="tok", subdomain="accuhive", region="us", schema_name=schema_name
            )

        assert is_valid is expected_ok
        assert {request.path for request in network.requests_log} == {"/api/v1/devices"}
        assert {request.param("limit") for request in network.requests_log} == {"1"}
        assert {request.headers["authorization"] for request in network.requests_log} == {"Bearer tok"}

    def test_validate_credentials_rejects_bad_base_url_before_request(self) -> None:
        is_valid, message = validate_credentials(api_token="tok", subdomain="", region="us")
        assert is_valid is False
        assert message is not None

    def test_validate_credentials_handles_request_exception(self) -> None:
        with scripted_network(always(requests.exceptions.ConnectionError("boom"))) as network:
            is_valid, message = validate_credentials(api_token="tok", subdomain="accuhive", region="us")

        assert is_valid is False
        assert message is not None and "boom" in message
        assert {request.path for request in network.requests_log} == {"/api/v1/devices"}

    @patch("products.warehouse_sources.sources.kandji.kandji.rest_api_resource")
    def test_kandji_source_devices_top_level(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        response = kandji_source(
            api_token="tok",
            subdomain="accuhive",
            region="us",
            endpoint="devices",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=Mock(can_resume=Mock(return_value=False)),
        )

        assert response.name == "devices"
        assert response.primary_keys == ["device_id"]
        assert response.sort_mode == "asc"

    def test_kandji_source_device_apps_fanout_injects_parent_id(self) -> None:
        result = SourceDriver(
            KandjiSource(), KandjiSourceConfig(api_token="tok", subdomain="accuhive", region="us")
        ).run(
            "device_apps",
            [
                ScriptedResponse(json=[{"device_id": "dev_1"}]),
                ScriptedResponse(json={"apps": [{"bundle_id": "com.apple.Safari"}]}),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/devices", "/api/v1/devices/dev_1/apps"]
        # The parent device id is injected onto each child row and renamed to device_id.
        assert result.rows == [{"bundle_id": "com.apple.Safari", "device_id": "dev_1"}]
        # bundle_id is only unique within a device, so the parent device id is part of the key.
        assert result.response is not None
        assert result.response.primary_keys == ["device_id", "bundle_id"]

    @parameterized.expand(
        [
            (
                "offset_list",
                "devices",
                {"offset": 300},
                [ScriptedResponse(json=[{"device_id": "dev_301"}])],
                ["https://accuhive.api.kandji.io/api/v1/devices?offset=300&limit=300"],
            ),
            (
                "next_link_list",
                "users",
                {"next_params": {"cursor": "abc"}},
                [ScriptedResponse(json={"results": [{"id": "u2"}], "next": None})],
                ["https://accuhive.api.kandji.io/api/v1/users?sizePerPage=300&cursor=abc"],
            ),
            (
                "fan_out",
                "device_apps",
                {"completed": ["/devices/dev_1/apps"], "current": None, "child_state": None, "parent": None},
                [
                    ScriptedResponse(json=[{"device_id": "dev_1"}, {"device_id": "dev_2"}]),
                    ScriptedResponse(json={"apps": [{"bundle_id": "com.apple.Safari"}]}),
                ],
                [
                    "https://accuhive.api.kandji.io/api/v1/devices?limit=300&offset=0",
                    "https://accuhive.api.kandji.io/api/v1/devices/dev_2/apps?limit=300",
                ],
            ),
        ]
    )
    def test_resumes_from_saved_state(
        self,
        _name: str,
        endpoint: str,
        saved: dict[str, Any],
        script: list[ScriptedResponse],
        expected_urls: list[str],
    ) -> None:
        result = SourceDriver(
            KandjiSource(), KandjiSourceConfig(api_token="tok", subdomain="accuhive", region="us")
        ).run(endpoint, script, resume_state=KandjiResumeConfig(paginator_state=saved))

        assert result.raised is None
        assert result.urls == expected_urls
        assert len(result.rows) == 1

    def test_list_endpoint_marks_completion_before_its_last_page(self) -> None:
        driver = SourceDriver(KandjiSource(), KandjiSourceConfig(api_token="tok", subdomain="accuhive", region="us"))

        result = driver.run("users", [ScriptedResponse(json={"results": [{"id": "u1"}], "next": None})])

        assert result.raised is None
        assert result.saved_states[-1] == KandjiResumeConfig(completed=True)

        resumed = driver.run("users", [], resume_state=KandjiResumeConfig(completed=True))

        assert resumed.raised is None
        assert resumed.urls == []
        assert resumed.rows == []


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
