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
    route,
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

    @parameterized.expand(
        [
            ("offset", "candidates", RecruiteeResumeConfig(offset=200), [_response([{"id": 5}])], "200"),
            (
                "page",
                "locations",
                RecruiteeResumeConfig(page=3),
                [_response([{"id": 5}], data_key="locations"), _response([], data_key="locations")],
                "3",
            ),
        ]
    )
    def test_resumes_from_saved_position(
        self, param: str, endpoint: str, state: RecruiteeResumeConfig, script: Script, expected_first: str
    ) -> None:
        result = _source(endpoint=endpoint, script=script, resume_state=state)

        # The first page must never be fetched on resume — the first request starts at the saved position.
        assert result.params(param)[0] == expected_first

    def test_locations_paginate_by_page_until_an_empty_page(self) -> None:
        result = _source(
            endpoint="locations",
            script=[
                _response([{"id": 1}, {"id": 2}], data_key="locations"),
                _response([{"id": 3}], data_key="locations"),
                _response([], data_key="locations"),
            ],
        )

        assert [r["id"] for r in result.rows] == [1, 2, 3]
        assert result.params("page") == ["1", "2", "3"]
        assert result.params("offset") == [None, None, None]
        assert result.params("scope") == ["all"] * 3
        assert result.params("view_mode") == ["full"] * 3
        assert result.saved_states == [RecruiteeResumeConfig(page=2), RecruiteeResumeConfig(page=3)]

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


class TestCandidateNotes:
    def test_fans_out_over_candidates_and_skips_a_deleted_candidate(self) -> None:
        result = _source(
            endpoint="candidate_notes",
            script=route(
                {
                    "/c/acme/candidates": [_response([{"id": 11}, {"id": 12}, {"id": 13}])],
                    "/c/acme/candidates/11/notes": [
                        _response([{"id": 1, "body": "first"}, {"id": 2, "body": "second"}], data_key="notes")
                    ],
                    "/c/acme/candidates/12/notes": [ScriptedResponse(status=404, json={})],
                    "/c/acme/candidates/13/notes": [_response([], data_key="notes")],
                }
            ),
        )

        assert result.raised is None
        assert [(r["candidate_id"], r["id"], r["body"]) for r in result.rows] == [
            (11, 1, "first"),
            (11, 2, "second"),
        ]
        assert all("_candidates_id" not in r for r in result.rows)
        assert result.paths == [
            "/c/acme/candidates",
            "/c/acme/candidates/11/notes",
            "/c/acme/candidates/12/notes",
            "/c/acme/candidates/13/notes",
        ]
        assert result.params("limit") == [str(PAGE_SIZE), None, None, None]
        assert result.params("offset") == ["0", None, None, None]


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
