from typing import Any

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.secureframe import (
    SecureframeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.secureframe.secureframe import (
    SecureframeResumeConfig,
    _extract_rows,
    get_endpoint_permissions,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.secureframe.source import SecureframeSource


def _driver() -> SourceDriver:
    return SourceDriver(SecureframeSource(), SecureframeSourceConfig(api_key="key", api_secret="secret", region="us"))


def _response(payload: Any, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=payload)


def _envelopes(*rows: dict[str, Any]) -> ScriptedResponse:
    return _response({"data": [{"id": row["id"], "type": "x", "attributes": row} for row in rows]})


def _scope(scope_id: str, asset_id: str, asset_type: str) -> dict[str, Any]:
    return {"id": scope_id, "asset_id": asset_id, "asset_type": asset_type, "framework_id": "fw-1"}


class TestExtractRows:
    @pytest.mark.parametrize(
        "payload, expected",
        [
            # Array of per-item JSON:API envelopes (the shape the OpenAPI spec declares).
            (
                [{"data": {"id": "a", "type": "control", "attributes": {"name": "x"}}}],
                [{"id": "a", "name": "x"}],
            ),
            # Standard JSON:API document with a top-level data array.
            (
                {"data": [{"id": "b", "type": "control", "attributes": {"id": "b", "name": "y"}}]},
                [{"id": "b", "name": "y"}],
            ),
            # Plain row dicts, with and without a wrapping data key.
            ([{"id": "c", "name": "z"}], [{"id": "c", "name": "z"}]),
            ({"data": [{"id": "d", "name": "w"}]}, [{"id": "d", "name": "w"}]),
            # Attributes win, but a missing id is backfilled from the envelope.
            (
                [{"data": {"id": "e", "attributes": {"name": "v", "id": "other"}}}],
                [{"id": "other", "name": "v"}],
            ),
            # Unexpected payloads yield nothing instead of raising.
            ({"message": "Authorization failed"}, []),
            ([], []),
            (None, []),
            ("not json we expect", []),
            ([None, "junk", 42], []),
        ],
    )
    def test_extract_rows_shapes(self, payload, expected):
        assert _extract_rows(payload) == expected


class TestPagination:
    def test_top_level_array_envelopes_are_flattened(self):
        # The declared shape: a top-level array of per-item JSON:API envelopes.
        result = _driver().run(
            "controls",
            [
                _response([{"data": {"id": "a", "type": "control", "attributes": {"name": "x"}}}]),
                _response([]),
            ],
        )
        assert result.rows == [{"id": "a", "name": "x"}]

    def test_resumes_from_saved_page(self):
        result = _driver().run(
            "controls",
            [_response({"data": []})],
            resume_state=SecureframeResumeConfig(page=5),
        )
        assert result.params("page")[0] == "5"

    def test_auth_failure_raises_instead_of_ending_sync(self):
        result = _driver().run("controls", [_response({"message": "Authorization failed"}, status_code=401)])

        assert isinstance(result.raised, HTTPError)
        assert result.saved_states == []


class TestFrameworkAssetScopesFanout:
    def test_walks_every_parent_kind_and_skips_deleted_assets(self):
        result = _driver().run(
            "framework_asset_scopes",
            route(
                {
                    "/devices": [_envelopes({"id": "d1"}, {"id": "d2"}), _response({"data": []})],
                    "/devices/d1/framework_asset_scopes": [
                        _envelopes(_scope("s1", "d1", "Device"), _scope("s2", "d1", "Device"))
                    ],
                    # The asset was deleted after the device list was read.
                    "/devices/d2/framework_asset_scopes": [_response({"error": "not found"}, status_code=404)],
                    "/cloud_resources": [_envelopes({"id": "c1"}), _response({"data": []})],
                    "/cloud_resources/c1/framework_asset_scopes": [_envelopes(_scope("s3", "c1", "CloudResource"))],
                    "/repositories": [_response({"data": []})],
                }
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["s1", "s2", "s3"]
        assert result.rows[0] == _scope("s1", "d1", "Device")
        child_requests = [r for r in result.requests if r.path.endswith("/framework_asset_scopes")]
        assert [r.param("page") for r in child_requests] == [None, None, None]
        assert result.paths[-1] == "/repositories"

    @pytest.mark.parametrize(
        "resume_state, expected_paths",
        [
            (
                SecureframeResumeConfig(
                    parent="cloud_resources",
                    fanout_state={
                        "completed": ["/cloud_resources/c1/framework_asset_scopes"],
                        "current": None,
                        "child_state": None,
                    },
                ),
                ["/cloud_resources", "/cloud_resources/c2/framework_asset_scopes", "/cloud_resources", "/repositories"],
            ),
            (
                SecureframeResumeConfig(parent="repositories"),
                ["/repositories"],
            ),
        ],
    )
    def test_resumes_at_the_saved_parent_kind(self, resume_state, expected_paths):
        result = _driver().run(
            "framework_asset_scopes",
            route(
                {
                    "/cloud_resources": [_envelopes({"id": "c1"}, {"id": "c2"}), _response({"data": []})],
                    "/cloud_resources/c2/framework_asset_scopes": [_envelopes(_scope("s4", "c2", "CloudResource"))],
                    "/repositories": [_response({"data": []})],
                }
            ),
            resume_state=resume_state,
        )

        assert result.raised is None
        assert result.paths == expected_paths

    def test_stages_the_next_parent_kind_once_the_previous_one_is_done(self):
        result = _driver().run(
            "framework_asset_scopes",
            route(
                {
                    "/devices": [_envelopes({"id": "d1"}), _response({"data": []})],
                    "/devices/d1/framework_asset_scopes": [_envelopes(_scope("s1", "d1", "Device"))],
                    "/cloud_resources": [_response({"data": []})],
                    "/repositories": [_response({"data": []})],
                }
            ),
        )

        assert SecureframeResumeConfig(parent="cloud_resources") in result.saved_states
        assert SecureframeResumeConfig(parent="repositories") in result.saved_states


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            # A valid key whose role lacks the probed scope is authenticated but not authorized.
            (403, (True, False)),
        ],
    )
    def test_status_mapping(self, status_code, expected):
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            assert validate_credentials("key", "secret", "us") == expected


class TestGetEndpointPermissions:
    @pytest.mark.parametrize("denied_status", [401, 403])
    def test_denied_endpoints_carry_a_reason(self, denied_status):
        with scripted_network([ScriptedResponse(status=200, json={}), ScriptedResponse(status=denied_status, json={})]):
            permissions = get_endpoint_permissions("key", "secret", "us", ["controls", "tests"])

        assert permissions["controls"] is None
        assert permissions["tests"] is not None
        assert "tests" in permissions["tests"]

    @pytest.mark.parametrize("denied_parent_index", [0, 1, 2])
    def test_fanout_table_is_denied_when_any_parent_list_is_denied(self, denied_parent_index):
        statuses = [200, 200, 200]
        statuses[denied_parent_index] = 403
        with scripted_network([ScriptedResponse(status=status, json={}) for status in statuses]):
            permissions = get_endpoint_permissions("key", "secret", "us", ["framework_asset_scopes"])

        assert permissions["framework_asset_scopes"] is not None

    def test_transient_failures_are_not_denials(self):
        with scripted_network(always(ConnectionError("connection reset"))):
            assert get_endpoint_permissions("key", "secret", "us", ["controls"]) == {"controls": None}


class TestSessionHardening:
    @pytest.mark.parametrize(
        "call",
        [
            lambda: validate_credentials("key", "secret", "us"),
            lambda: get_endpoint_permissions("key", "secret", "us", ["controls"]),
        ],
    )
    def test_session_excludes_responses_from_sample_capture_and_redacts_credentials(self, call):
        with scripted_network(always(ScriptedResponse(status=200, json={}))) as network:
            call()

        # Secureframe responses carry customer PII the generic scrubber can't remove, so the
        # session must opt out of HTTP sample capture and mask both credential halves.
        kwargs = network.session_options[-1]
        assert kwargs["capture"] is False
        assert set(kwargs["redact_values"]) == {"key", "secret"}

    def test_sync_transport_session_is_hardened(self):
        # The transport session handed to the rest_source client is built the same way.
        result = _driver().run("controls", [_response({"data": []})])

        kwargs = result.session_options[-1]
        assert kwargs["capture"] is False
        assert set(kwargs["redact_values"]) == {"key", "secret"}
        assert kwargs["headers"]["Authorization"] == "key secret"
