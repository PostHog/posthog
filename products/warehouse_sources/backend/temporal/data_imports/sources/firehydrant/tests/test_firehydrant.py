from typing import Any, Literal

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.firehydrant import (
    FireHydrantResumeConfig,
    base_url_for_region,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.settings import (
    ENDPOINTS,
    FIREHYDRANT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.source import FireHydrantSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.firehydrant import (
    FireHydrantSourceConfig,
)


def _response(items: list[dict[str, Any]] | None, *, next_page: int | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"data": items or []}
    body["pagination"] = {"next": next_page}
    return ScriptedResponse(json=body)


def _driver(api_key: str = "fhb_test", region: Literal["us", "eu"] = "us") -> SourceDriver:
    return SourceDriver(FireHydrantSource(), FireHydrantSourceConfig(api_key=api_key, region=region))


class TestFanout:
    def test_resume_skips_parents_already_synced(self) -> None:
        result = _driver().run(
            "team_escalation_policies",
            [
                _response([{"id": "t1"}, {"id": "t2"}], next_page=None),
                _response([{"id": "task2"}], next_page=None),
            ],
            resume_state=FireHydrantResumeConfig(
                paginator_state={
                    "completed": ["/v1/teams/t1/escalation_policies"],
                    "current": None,
                    "child_state": None,
                }
            ),
        )

        # Only the unfinished parent is re-fetched, so a resumed fan-out doesn't replay the whole
        # parent list's children.
        assert result.raised is None
        assert result.paths == ["/v1/teams", "/v1/teams/t2/escalation_policies"]
        assert result.rows == [{"id": "task2", "team_id": "t2"}]

    def test_child_response_without_the_data_envelope_fails_loud(self) -> None:
        # A shape change has to stop the sync. Reading it as an empty page would replace the whole
        # table with no rows, and nothing downstream would report that.
        result = _driver().run(
            "team_escalation_policies",
            [_response([{"id": "t1"}]), ScriptedResponse(json={"escalation_policies": [{"id": "ep1"}]})],
        )

        assert isinstance(result.raised, ValueError)
        assert "data_selector" in str(result.raised)


class TestSourceResponse:
    @parameterized.expand(list(ENDPOINTS))
    def test_source_response_matches_endpoint_config(self, endpoint: str) -> None:
        config = FIREHYDRANT_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_response([])])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_partition_keys_are_stable_creation_fields(self) -> None:
        # A partition key that changes (updated_at/lastSeen) rewrites partitions every sync.
        # `occurred_at` is when a timeline event happened, which is as immutable as `created_at`.
        for config in FIREHYDRANT_ENDPOINTS.values():
            if config.partition_key:
                assert config.partition_key in {"created_at", "occurred_at"}

    @parameterized.expand(
        [
            ("priorities", ["slug"]),
            ("severities", ["slug"]),
            ("incident_tags", ["name"]),
            ("custom_field_definitions", ["field_id"]),
            ("incidents", ["id"]),
        ]
    )
    def test_endpoint_specific_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        assert FIREHYDRANT_ENDPOINTS[endpoint].primary_keys == expected_keys


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            valid, _error = validate_credentials("fhb_test")
        assert valid is expected_valid
        assert {request.path for request in network.requests_log} == {"/v1/ping"}

    def test_network_error_is_invalid(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))) as network:
            valid, error = validate_credentials("fhb_test")
        assert valid is False
        assert error is not None
        assert {request.path for request in network.requests_log} == {"/v1/ping"}

    @parameterized.expand(
        [
            ("default_us", None, "https://api.firehydrant.io/v1/ping"),
            ("eu", "eu", "https://api.eu.firehydrant.io/v1/ping"),
        ]
    )
    def test_probes_region_host(self, _name: str, region: str | None, expected_url: str) -> None:
        # The key is only valid against its own region's host, so validation must probe there.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("fhb_test", region=region)
        assert network.requests_log[0].url == expected_url

    @parameterized.expand(
        [
            ("default_us", None, "https://api.firehydrant.io"),
            ("us", "us", "https://api.firehydrant.io"),
            ("eu", "eu", "https://api.eu.firehydrant.io"),
            ("unknown_falls_back", "apac", "https://api.firehydrant.io"),
        ]
    )
    def test_base_url_for_region(self, _name: str, region: str | None, expected_host: str) -> None:
        # EU accounts are pinned to the data-residency host; an unknown or missing region must fall
        # back to the US default rather than a wrong host.
        assert base_url_for_region(region) == expected_host


class TestCredentialRedaction:
    """The token must be registered for redaction so it can't leak into logged URLs or HTTP samples."""

    def test_validate_credentials_redacts_api_key(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("fhb_secret")
        assert network.session_options[0].get("redact_values") == ("fhb_secret",)

    def test_transport_redacts_api_key(self) -> None:
        result = _driver(api_key="fhb_secret").run("incidents", [_response([])])
        # The bearer token is registered for value-based redaction when the tracked session is built.
        assert result.raised is None
        assert any("fhb_secret" in options.get("redact_values", ()) for options in result.session_options)
