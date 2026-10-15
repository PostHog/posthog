from typing import Any

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
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


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, (True, True)),
            # A valid key whose role lacks the probed scope is authenticated but not authorized.
            (403, (True, False)),
            (401, (False, False)),
            (500, (False, False)),
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
