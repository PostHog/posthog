from typing import Any

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flowlu.flowlu import (
    FlowluResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flowlu.settings import ENDPOINTS, FLOWLU_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.flowlu.source import FlowluSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.flowlu import FlowluSourceConfig


def _envelope(items: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    return {"response": {"items": items, "total": total if total is not None else len(items), "count": len(items)}}


def _driver() -> SourceDriver:
    return SourceDriver(FlowluSource(), FlowluSourceConfig(api_key="fl-key", subdomain="acme"))


class TestPagination:
    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "accounts",
            [ScriptedResponse(json=_envelope([{"id": 2}])), ScriptedResponse(json=_envelope([]))],
            resume_state=FlowluResumeConfig(next_page=2),
        )

        assert result.raised is None
        assert result.rows == [{"id": 2}]
        # Page 1 must never be fetched on resume.
        assert result.params("page")[0] == "2"


class TestErrorHandling:
    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status: int) -> None:
        result = _driver().run("accounts", [ScriptedResponse(status=status)])

        assert isinstance(result.raised, HTTPError)

    def test_client_error_message_omits_api_key_and_keeps_status_prefix(self) -> None:
        # The 401 raise_for_status embeds the request URL, which carries the `api_key` query param.
        # The framework redacts the key's VALUE from the raised message while preserving the
        # "<status> Client Error: <reason> for url" prefix that get_non_retryable_errors matches on.
        result = _driver().run("accounts", [ScriptedResponse(status=401)])

        assert isinstance(result.raised, HTTPError)
        message = str(result.raised)
        assert "fl-key" not in message
        assert message.startswith("401 Client Error: Unauthorized for url")

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_transient_statuses_are_retried_then_recover(self, _name: str, status: int) -> None:
        # First page fails once, then succeeds on retry; an empty page terminates.
        result = _driver().run(
            "accounts",
            [
                ScriptedResponse(status=status),
                ScriptedResponse(json=_envelope([{"id": 1}])),
                ScriptedResponse(json=_envelope([])),
            ],
        )

        # A 429/5xx is transient: the client retries and recovers rather than failing loudly.
        assert result.raised is None
        assert result.rows == [{"id": 1}]
        assert len(result.requests) == 3


class TestMalformedPayload:
    @parameterized.expand(
        [
            ("bare_array", [{"id": 1}]),
            ("missing_response_key", {"data": []}),
            ("non_dict_response", {"response": []}),
            ("missing_items", {"response": {"total": 0}}),
        ]
    )
    def test_unexpected_shape_fails_loudly(self, _name: str, body: Any) -> None:
        # A 200 body that doesn't match `response.items` means the shape changed — fail loud
        # instead of silently syncing 0 rows.
        result = _driver().run("accounts", [ScriptedResponse(json=body)])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestValidateCredentials:
    def test_connection_error_maps_to_generic_message(self) -> None:
        # The probe swallows the exception (which could embed the api_key-carrying URL) and returns
        # a fixed message, so the raw exception text is never surfaced.
        with scripted_network(always(RuntimeError("https://acme.flowlu.com/...?api_key=fl-key"))):
            assert validate_credentials("fl-key", "acme") == (False, "Could not connect to Flowlu")


class TestFlowluSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=_envelope([]))])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        # No stable creation timestamp could be verified across every object, so we don't partition.
        assert result.response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in FLOWLU_ENDPOINTS.values())
        assert set(FLOWLU_ENDPOINTS) == set(ENDPOINTS)
