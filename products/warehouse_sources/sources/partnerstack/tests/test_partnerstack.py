from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.partnerstack import (
    PartnerStackSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.partnerstack import (
    PAGE_SIZE,
    PartnerStackResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.settings import (
    ENDPOINTS,
    PARTNERSTACK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.source import PartnerStackSource


def _driver() -> SourceDriver:
    return SourceDriver(PartnerStackSource(), PartnerStackSourceConfig(public_key="pub", private_key="priv"))


def _response(
    items: list[dict[str, Any]] | None = None, *, has_more: bool = False, body: Any = "__default__"
) -> ScriptedResponse:
    if body == "__default__":
        body = {"data": {"items": items or [], "has_more": has_more}}
    return ScriptedResponse(json=body)


class TestPagination:
    def test_follows_cursor_until_has_more_false(self) -> None:
        result = _driver().run(
            "partnerships",
            [_response([{"key": "a"}, {"key": "b"}], has_more=True), _response([{"key": "c"}])],
        )

        assert result.raised is None
        assert result.rows == [{"key": "a"}, {"key": "b"}, {"key": "c"}]
        # The second request advances the cursor to the last key of the first page.
        assert result.params("starting_after") == [None, "b"]
        assert result.params("limit") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        # State is saved once, after the first page (cursor "b"); the final page persists nothing.
        assert result.saved_states == [PartnerStackResumeConfig(starting_after="b")]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "partnerships", [_response([{"key": "c"}])], resume_state=PartnerStackResumeConfig(starting_after="b")
        )

        # The initial (cursor-less) page is never fetched on resume; the first request seeds the cursor.
        assert result.raised is None
        assert result.rows == [{"key": "c"}]
        assert result.params("starting_after") == ["b"]

    def test_stops_when_last_object_missing_cursor(self) -> None:
        # has_more is true but the last object has no `key`, so we can't advance and must stop.
        result = _driver().run("partnerships", [_response([{"no_key": 1}], has_more=True)])

        assert result.raised is None
        assert result.rows == [{"no_key": 1}]
        assert len(result.requests) == 1
        assert result.saved_states == []

    @parameterized.expand(
        [("deal_stages", "/api/v2/sales_cycles/deal/stages"), ("lead_stages", "/api/v2/sales_cycles/lead/stages")]
    )
    def test_stage_lookups_fetch_a_single_unpaginated_page(self, endpoint: str, path: str) -> None:
        result = _driver().run(endpoint, [_response([{"key": "stg_a"}, {"key": "stg_b"}], has_more=True)])

        assert result.raised is None
        assert result.rows == [{"key": "stg_a"}, {"key": "stg_b"}]
        assert [request.path for request in result.requests] == [path]
        assert result.params("limit") == [None]
        assert result.saved_states == []


class TestRetryAndFailure:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_retry_then_raise(self, _name: str, status: int) -> None:
        result = _driver().run("partnerships", always(ScriptedResponse(status=status, json={"error": "nope"})))

        assert isinstance(result.raised, RESTClientRetryableError)
        # Retried up to the client's attempt cap before giving up.
        assert len(result.requests) == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status_without_retry(self, _name: str, status: int) -> None:
        result = _driver().run("partnerships", [ScriptedResponse(status=status, json={"error": "nope"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1

    @parameterized.expand(
        [
            ("bare_list", [{"key": "a"}]),
            ("missing_data", {"items": []}),
            ("data_not_dict", {"data": []}),
            ("non_list_items", {"data": {"items": "nope", "has_more": False}}),
        ]
    )
    def test_unexpected_envelope_is_retried_then_raises(self, _name: str, body: Any) -> None:
        result = _driver().run("partnerships", always(_response(body=body)))

        # An unexpected 200 body shape is treated as transient: retried, then raised.
        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, None),
        ]
    )
    def test_status_to_message(self, status: int, expected_message: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            valid, message = validate_credentials("pub", "priv")

        assert valid is (status == 200)
        assert message == expected_message
        assert network.requests_log[0].path == "/api/v2/partnerships"
        assert network.requests_log[0].param("limit") == "1"

    def test_connection_error_is_not_validated_with_message(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            valid, message = validate_credentials("pub", "priv")

        assert valid is False
        assert message is not None
        assert {request.path for request in network.requests_log} == {"/api/v2/partnerships"}


class TestSourceResponseShape:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_response()])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["key"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert result.response.partition_mode is None

    def test_every_endpoint_uses_key_primary_key(self) -> None:
        assert all(config.primary_keys == ["key"] for config in PARTNERSTACK_ENDPOINTS.values())
        assert set(PARTNERSTACK_ENDPOINTS) == set(ENDPOINTS)
