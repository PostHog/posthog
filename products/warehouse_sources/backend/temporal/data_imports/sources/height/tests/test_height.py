import json
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.height import HeightSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.height.height import (
    HeightAPIKeyAuth,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.height.settings import ENDPOINTS, HEIGHT_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.height.source import HeightSource


class TestHeightAuth:
    def test_redacts_both_composite_and_raw_key(self) -> None:
        # Both the header value and the raw key on its own are scrubbed from logged errors.
        auth = HeightAPIKeyAuth("secret_abc")
        assert set(auth.secret_values()) == {"api-key secret_abc", "secret_abc"}


class TestHeightSourceRows:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(HeightSource(), HeightSourceConfig(api_key="secret_key"))

    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_every_endpoint_targets_its_path(self, endpoint: str) -> None:
        result = self._driver().run(endpoint, [ScriptedResponse(json={"list": []})], team_id=1, job_id="j")

        assert result.raised is None
        assert result.urls == [f"https://api.height.app{HEIGHT_ENDPOINTS[endpoint].path}"]
        assert result.rows == []

    @parameterized.expand(
        [
            ("bare_array", [{"id": 1}]),
            ("missing_list_key", {"data": []}),
            ("null_body", None),
        ]
    )
    def test_unexpected_payload_fails_loud(self, _name: str, body: Any) -> None:
        result = self._driver().run("users", [ScriptedResponse(body=json.dumps(body).encode())])

        # A 200 body without a `list` key means the response shape changed — fail loud, not 0 rows.
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)
        assert result.rows == []


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid Height API key"),
            (403, False, "Invalid Height API key"),
            (500, False, "Height returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("secret_key") == (expected_valid, expected_message)
        assert {request.path for request in network.requests_log} == {"/users"}
        assert all(request.headers["authorization"] == "api-key secret_key" for request in network.requests_log)
        assert network.session_options == [{"redact_values": ("secret_key",)}]

    def test_connection_error_is_not_validated(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("secret_key") == (False, "Could not validate Height API key")
        assert {request.path for request in network.requests_log} == {"/users"}


class TestHeightSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = SourceDriver(HeightSource(), HeightSourceConfig(api_key="secret_key")).run(
            endpoint, [ScriptedResponse(json={"list": []})]
        )
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in HEIGHT_ENDPOINTS.values())
        assert set(HEIGHT_ENDPOINTS) == set(ENDPOINTS)
