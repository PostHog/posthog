from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.recruitee import (
    RecruiteeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recruitee.recruitee import (
    PAGE_SIZE,
    RecruiteeResumeConfig,
    base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recruitee.source import RecruiteeSource


def _response(
    items: list[dict[str, Any]] | None, *, data_key: str = "candidates", body: Any = None
) -> ScriptedResponse:
    return ScriptedResponse(json=body if body is not None else {data_key: items or []})


def _source(endpoint: str = "candidates", script: Script | None = None, **inputs: Any) -> DriveResult:
    config = RecruiteeSourceConfig(company_id="acme", api_token="rc-token")
    return SourceDriver(RecruiteeSource(), config).run(endpoint, script if script is not None else [], **inputs)


class TestBaseUrl:
    @parameterized.expand([("slash", "a/b"), ("dot", "evil.com"), ("space", "a b"), ("at", "user@host")])
    def test_rejects_unsafe_company_id(self, _name: str, company_id: str) -> None:
        with pytest.raises(ValueError):
            base_url(company_id)


class TestPagination:
    def test_paginates_and_progresses_offset(self) -> None:
        full_page = [{"id": i} for i in range(PAGE_SIZE)]

        result = _source(script=[_response(full_page), _response([{"id": 999}])])

        assert [r["id"] for r in result.rows] == [*range(PAGE_SIZE), 999]
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert result.params("limit") == [str(PAGE_SIZE)] * 2
        # Checkpoint saved once after the first full page (points at the next page); short page ends it.
        assert result.saved_states == [RecruiteeResumeConfig(offset=PAGE_SIZE)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _source(script=[_response([{"id": 5}])], resume_state=RecruiteeResumeConfig(offset=200))

        # Offset 0 must never be fetched on resume — the first request starts at the saved offset.
        assert result.params("offset") == ["200"]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _source(script=[_response([{"id": 5}])])

        assert result.params("offset") == ["0"]


class TestDataExtraction:
    @parameterized.expand([("candidates",), ("offers",), ("departments",), ("placements",)])
    def test_extracts_rows_from_resource_named_key(self, endpoint: str) -> None:
        result = _source(endpoint=endpoint, script=[_response([{"id": 1}, {"id": 2}], data_key=endpoint)])

        assert [r["id"] for r in result.rows] == [1, 2]
        assert result.paths == [f"/c/acme/{endpoint}"]

    @parameterized.expand(
        [
            ("non_dict_body", [{"id": 1}]),
            ("missing_data_key", {"offers": []}),
            ("value_not_a_list", {"candidates": {"id": 1}}),
        ]
    )
    def test_malformed_body_is_retried_then_raises(self, _name: str, malformed: Any) -> None:
        # A 200 whose body isn't the expected list-under-key shape is retried; after the attempts are
        # exhausted the retryable error propagates instead of syncing 0 rows or a garbage row.
        result = _source(script=always(_response(None, body=malformed)))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) > 1


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool, expected_message: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            assert validate_credentials("acme", "rc-token") == (expected_valid, expected_message)

        assert network.requests_log[0].path == "/c/acme/departments"
        assert network.requests_log[0].headers["authorization"] == "Bearer rc-token"
