from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.octopusdeploy import (
    OctopusDeploySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.octopus_deploy import (
    octopus_deploy as octopus_deploy_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.octopus_deploy.octopus_deploy import (
    OctopusDeployResumeConfig,
    _build_params,
    _format_incremental_value,
    _parse_retry_after,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.octopus_deploy.settings import (
    OCTOPUS_DEPLOY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.octopus_deploy.source import OctopusDeploySource


def _page(items: list[dict[str, Any]], has_next: bool) -> ScriptedResponse:
    links = {"Self": "/api/x"}
    if has_next:
        links["Page.Next"] = "/api/x?skip=next"
    return ScriptedResponse(json={"Items": items, "Links": links})


def _driver() -> SourceDriver:
    return SourceDriver(OctopusDeploySource(), OctopusDeploySourceConfig(host="my-org.octopus.app", api_key="API-KEY"))


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            (date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_incremental_value(value) == expected


class TestBuildParams:
    def test_non_incremental_endpoint_never_sends_filter(self):
        # Deployments expose no server-side date filter; an incremental run must not invent one.
        params = _build_params(
            OCTOPUS_DEPLOY_ENDPOINTS["deployments"],
            skip=0,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert params == {"skip": 0, "take": 100}


class TestValidateCredentials:
    def test_success(self):
        with scripted_network([ScriptedResponse(json={"Items": []})]) as network:
            assert validate_credentials("my-org.octopus.app", "API-KEY") == (True, None)
        assert network.requests_log[0].path == "/api/spaces"
        assert network.requests_log[0].param("take") == "1"

    def test_403_at_source_create_is_accepted(self):
        with scripted_network([ScriptedResponse(status=403)]):
            assert validate_credentials("my-org.octopus.app", "API-KEY", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with scripted_network([ScriptedResponse(status=403)]):
            valid, msg = validate_credentials("my-org.octopus.app", "API-KEY", schema_name="deployments")
            assert valid is False
            assert msg is not None

    def test_error_body_message_is_surfaced(self):
        with scripted_network([ScriptedResponse(status=400, json={"ErrorMessage": "Something broke"})]):
            valid, msg = validate_credentials("my-org.octopus.app", "API-KEY")
            assert valid is False
            assert msg == "Something broke"

    @pytest.mark.parametrize("bad_host", ["", "not a host!", "https://"])
    def test_invalid_host_short_circuits(self, bad_host):
        valid, msg = validate_credentials(bad_host, "API-KEY")
        assert valid is False
        assert msg == "Invalid Octopus Deploy host"

    def test_rejects_redirect_response(self):
        # A validated host that 3xx-redirects (potentially to an internal address) must be
        # rejected, not followed (SSRF).
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://other.example.com/api/spaces"})]
        ) as network:
            valid, msg = validate_credentials("my-org.octopus.app", "API-KEY")
            assert valid is False
            assert msg == octopus_deploy_module.HOST_NOT_ALLOWED_ERROR
        assert network.requests_log[0].path == "/api/spaces"
        assert len(network.requests_log) == 1
        assert network.requests_log[0].headers["x-octopus-apikey"] == "API-KEY"

    def test_blocks_unsafe_host(self):
        # When a team_id is supplied, a host resolving to an internal address is rejected before
        # any HTTP request is made (SSRF guard).
        with (
            mock.patch.object(octopus_deploy_module, "_is_host_safe", return_value=(False, "internal address")),
            scripted_network([]) as network,
        ):
            valid, msg = validate_credentials("10.0.0.1", "API-KEY", team_id=99)
            assert valid is False
            assert msg == "internal address"
        assert network.requests_log == []


class TestOctopusDeploySourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_keys, partition_key",
        [
            ("spaces", ["Id"], None),
            ("projects", ["SpaceId", "Id"], None),
            ("releases", ["SpaceId", "Id"], "Assembled"),
            ("deployments", ["SpaceId", "Id"], "Created"),
            ("tasks", ["SpaceId", "Id"], "QueueTime"),
            ("events", ["SpaceId", "Id"], "Occurred"),
        ],
    )
    def test_response_shape(self, endpoint, primary_keys, partition_key):
        script = [_page([], has_next=False)]
        if endpoint != "spaces":
            script = [_page([{"Id": "Spaces-1"}], has_next=False), *script]
        result = _driver().run(endpoint, script)
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "desc"
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None


class TestGetRows:
    def test_empty_page_terminates(self):
        responses = [
            _page([{"Id": "Spaces-1"}], has_next=False),
            _page([], has_next=False),
        ]
        result = _driver().run("projects", responses)
        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 2

    # "spaces" exercises the instance-level `_paginate` loop; "projects" (space-scoped) first
    # exercises the `_get_space_ids` enumeration loop. Both must refuse a host that advertises
    # `Page.Next` forever rather than looping indefinitely.
    @pytest.mark.parametrize("endpoint", ["spaces", "projects"])
    def test_pagination_budget_aborts_runaway_listing(self, endpoint):
        responses = [_page([{"Id": "Spaces-1"}], has_next=True) for _ in range(3)]
        with mock.patch.object(octopus_deploy_module, "MAX_PAGES_PER_LISTING", 3):
            result = _driver().run(endpoint, responses)
        assert isinstance(result.raised, octopus_deploy_module.OctopusDeployPaginationLimitError)
        assert len(result.requests) == 3

    # The page ceiling only catches a host returning pages *fast*; one that keeps advertising
    # `Page.Next` while each page burns wall-clock (slow drip / stall before headers) would hold a
    # worker indefinitely without the time budget. Same two loops as the page-ceiling test.
    @pytest.mark.parametrize("endpoint", ["spaces", "projects"])
    def test_pagination_time_budget_aborts_slow_listing(self, endpoint):
        responses = [_page([{"Id": "Spaces-1"}], has_next=True)]
        with mock.patch.object(octopus_deploy_module, "MAX_LISTING_SECONDS", -1):
            result = _driver().run(endpoint, responses)
        assert isinstance(result.raised, octopus_deploy_module.OctopusDeployPaginationLimitError)
        assert len(result.requests) == 1

    def test_resumes_from_saved_space_and_skip(self):
        responses = [
            _page([{"Id": "Spaces-1"}, {"Id": "Spaces-2"}, {"Id": "Spaces-3"}], has_next=False),
            _page([{"Id": "P-1"}], has_next=False),  # Spaces-2, resumed at skip=200
            _page([{"Id": "P-2"}], has_next=False),  # Spaces-3, fresh at skip=0
        ]
        result = _driver().run(
            "projects", responses, resume_state=OctopusDeployResumeConfig(skip=200, space_id="Spaces-2")
        )
        assert result.raised is None
        assert result.rows == [{"Id": "P-1", "SpaceId": "Spaces-2"}, {"Id": "P-2", "SpaceId": "Spaces-3"}]
        assert result.paths[1] == "/api/Spaces-2/projects"
        assert result.requests[1].param("skip") == "200"
        assert result.paths[2] == "/api/Spaces-3/projects"
        assert result.requests[2].param("skip") == "0"
        # Spaces-1 was already completed before the crash — not re-fetched.
        assert "/api/Spaces-1/projects" not in result.paths

    def test_instance_level_endpoint_skips_space_fan_out(self):
        responses = [_page([{"Id": "Spaces-1"}, {"Id": "Spaces-2"}], has_next=False)]
        result = _driver().run("spaces", responses)

        assert result.raised is None
        assert result.paths == ["/api/spaces"]
        assert [row["Id"] for row in result.rows] == ["Spaces-1", "Spaces-2"]

    def test_incremental_filter_applied_to_every_page(self):
        responses = [
            _page([{"Id": "Spaces-1"}], has_next=False),
            _page([{"Id": "T-1"}], has_next=True),
            _page([{"Id": "T-2"}], has_next=False),
        ]
        result = _driver().run(
            "tasks",
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("fromCompletedDate") == [None, "2024-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"]
        assert result.params("skip") == ["0", "0", "1"]

    def test_redirect_response_raises(self):
        # Requests are made with allow_redirects=False, and a redirect response is rejected rather
        # than followed to a (potentially internal) Location (SSRF).
        result = _driver().run(
            "projects", [ScriptedResponse(status=302, headers={"Location": "https://other.example.com/api/spaces"})]
        )
        assert isinstance(result.raised, octopus_deploy_module.OctopusDeployHostNotAllowedError)
        assert result.paths == ["/api/spaces"]

    def test_unsafe_host_raises_before_any_request(self):
        with mock.patch.object(octopus_deploy_module, "_is_host_safe", return_value=(False, "internal address")):
            result = _driver().run("projects", [])
        assert isinstance(result.raised, octopus_deploy_module.OctopusDeployHostNotAllowedError)
        assert result.requests == []


class TestReadCappedBody:
    def _streamed(self, chunks: list[bytes]) -> mock.MagicMock:
        response = mock.MagicMock()
        response.iter_content.return_value = chunks
        return response

    def test_rejects_oversized_body(self):
        # A customer-controlled host that streams past the cap must be refused before it exhausts
        # the worker's memory, not buffered whole.
        response = self._streamed([b"x" * 10, b"x" * 10])
        with mock.patch.object(octopus_deploy_module, "MAX_RESPONSE_BYTES", 15):
            with pytest.raises(octopus_deploy_module.OctopusDeployResponseTooLargeError):
                octopus_deploy_module._read_capped_body(response)
        response.close.assert_called_once()

    def test_rejects_slow_download(self):
        # A host dribbling the body under the per-read timeout must hit the wall-clock deadline
        # rather than holding the connection (and worker) open indefinitely.
        response = self._streamed([b"x"])
        with mock.patch.object(octopus_deploy_module, "MAX_DOWNLOAD_SECONDS", -1):
            with pytest.raises(octopus_deploy_module.OctopusDeployResponseTooSlowError):
                octopus_deploy_module._read_capped_body(response)
        response.close.assert_called_once()


class TestFetchPageErrorLogging:
    def test_error_body_is_truncated_in_log(self):
        # A customer-controlled host can return a large-but-under-cap 4xx body; the log line must
        # carry only a bounded preview plus the byte count, never the whole body.

        body = b"x" * (octopus_deploy_module.LOG_BODY_PREVIEW_BYTES * 4)
        response = mock.MagicMock()
        response.status_code = 400
        response.ok = False
        response.is_redirect = False
        response.is_permanent_redirect = False
        response.iter_content.return_value = [body]
        response.raise_for_status.side_effect = requests.HTTPError("bad request", response=response)

        session = mock.MagicMock()
        session.get.return_value = response
        logger = mock.MagicMock()

        with pytest.raises(requests.HTTPError):
            octopus_deploy_module._fetch_page(session, "https://my-org.octopus.app/api/spaces", {}, logger)

        logged = logger.error.call_args.args[0]
        assert f"body_bytes={len(body)}" in logged
        assert logged.count("x") <= octopus_deploy_module.LOG_BODY_PREVIEW_BYTES


class TestRetryAfter:
    @pytest.mark.parametrize(
        "headers, expected",
        [
            ({"Retry-After": "5"}, 5.0),
            ({"Retry-After": "100000"}, 60.0),  # capped
            ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),  # HTTP-date ignored
            ({}, None),
        ],
    )
    def test_parse_retry_after(self, headers, expected):
        response = mock.MagicMock()
        response.headers = headers
        assert _parse_retry_after(response) == expected
