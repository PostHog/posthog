from typing import Any

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rentcast import (
    RentCastSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rentcast.rentcast import (
    PAGE_SIZE,
    RentCastResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rentcast.settings import (
    ENDPOINTS,
    RENTCAST_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rentcast.source import RentCastSource


def _driver() -> SourceDriver:
    return SourceDriver(RentCastSource(), RentCastSourceConfig(api_key="rc-key"))


def _page(body: Any) -> ScriptedResponse:
    # RentCast list endpoints return a bare JSON array of records.
    return ScriptedResponse(json=body)


def _full_page(start_id: int) -> list[dict]:
    return [{"id": start_id + i} for i in range(PAGE_SIZE)]


class TestPagination:
    def test_paginates_and_progresses_offset(self) -> None:
        result = _driver().run("properties", [_page(_full_page(0)), _page([{"id": 999}])])

        assert len(result.rows) == PAGE_SIZE + 1
        assert result.rows[-1] == {"id": 999}
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert result.requests[0].param("limit") == str(PAGE_SIZE)
        # Checkpoint saved after the first full page (points at the next page); short page ends it.
        assert result.saved_states == [RentCastResumeConfig(offset=PAGE_SIZE)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run("properties", [_page([{"id": 5}])], resume_state=RentCastResumeConfig(offset=PAGE_SIZE))

        # Offset 0 must never be fetched on resume — the first request starts at the saved offset.
        assert result.params("offset") == [str(PAGE_SIZE)]
        assert result.rows == [{"id": 5}]

    @parameterized.expand([("bare_string", "nope"), ("dict_without_list", {"error": "nope"})])
    def test_non_list_body_is_retryable(self, _name: str, bad_body: Any) -> None:
        # A 200 body that isn't a list means an unexpected shape — retry, don't sync garbage.
        result = _driver().run("properties", always(_page(bad_body)))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert "Unexpected 200 response body shape" in str(result.raised)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid RentCast API key"),
            ("forbidden", 403, False, "Invalid RentCast API key"),
            ("server_error", 500, False, "RentCast returned HTTP 500"),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool, expected_message: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            assert validate_credentials("rc-key") == (expected_valid, expected_message)

    def test_connection_error_is_not_validated(self) -> None:
        # A transport failure must not raise out of validate_credentials — it maps to "not validated".
        with scripted_network(always(ConnectionError("boom"))):
            assert validate_credentials("rc-key") == (False, "Could not validate RentCast API key")


class TestRentCastSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_page([])])

        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every record, so we don't partition.
        assert result.response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in RENTCAST_ENDPOINTS.values())
        assert set(RENTCAST_ENDPOINTS) == set(ENDPOINTS)
