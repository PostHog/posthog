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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.planhat import (
    PlanhatSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.planhat.planhat import (
    PAGE_SIZE,
    PlanhatResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.planhat.settings import (
    ENDPOINTS,
    PLANHAT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.planhat.source import PlanhatSource


def _driver() -> SourceDriver:
    return SourceDriver(PlanhatSource(), PlanhatSourceConfig(api_key="tok"))


def _full_page(start_id: int) -> list[dict[str, Any]]:
    return [{"_id": str(start_id + i)} for i in range(PAGE_SIZE)]


class TestPagination:
    def test_paginates_and_progresses_offset(self) -> None:
        result = _driver().run(
            "companies",
            [ScriptedResponse(json=_full_page(0)), ScriptedResponse(json=[{"_id": "c_last"}])],
        )

        assert result.raised is None
        assert [row["_id"] for row in result.rows] == [*(str(i) for i in range(PAGE_SIZE)), "c_last"]
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert result.params("limit") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        # Checkpoint saved after the first full page (points at the next page); short page ends it.
        assert result.saved_states == [PlanhatResumeConfig(offset=PAGE_SIZE)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "companies",
            [ScriptedResponse(json=[{"_id": "5"}])],
            resume_state=PlanhatResumeConfig(offset=PAGE_SIZE),
        )

        assert result.raised is None
        assert [row["_id"] for row in result.rows] == ["5"]
        # Offset 0 must never be fetched on resume — the first request targets the saved offset.
        assert result.params("offset") == [str(PAGE_SIZE)]


class TestMalformedBody:
    def test_non_list_body_is_retried_then_reraises(self) -> None:
        # A 200 body that is not a bare array (an error object) — retried, never ingested as a row.
        result = _driver().run("companies", always(ScriptedResponse(json={"error": "nope"})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert "Unexpected 200 response body shape" in str(result.raised)
        assert result.rows == []
        # Exhausts the client's default retry budget (5 attempts) before giving up.
        assert len(result.requests) == 5


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, (True, None)),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: tuple[bool, str | None]) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("tok") == expected

        assert {request.path for request in network.requests_log} == {"/companies"}
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].param("offset") == "0"
        assert network.requests_log[0].headers["authorization"] == "Bearer tok"

    def test_connection_error_is_not_validated(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))) as network:
            assert validate_credentials("tok") == (False, "Could not validate Planhat API token")

        assert {request.path for request in network.requests_log} == {"/companies"}


class TestPlanhatSourceResponse:
    @parameterized.expand(
        [
            ("companies", "/companies"),
            ("endusers", "/endusers"),
            ("users", "/users"),
            ("licenses", "/licenses"),
            ("assets", "/assets"),
            ("nps", "/nps"),
            ("conversations", "/conversations"),
            ("tickets", "/tickets"),
            ("invoices", "/invoices"),
            ("sales", "/sales"),
        ]
    )
    def test_source_response_shape(self, endpoint: str, expected_path: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.paths == [expected_path]
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["_id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert result.response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["_id"] for config in PLANHAT_ENDPOINTS.values())
        assert set(PLANHAT_ENDPOINTS) == set(ENDPOINTS)
