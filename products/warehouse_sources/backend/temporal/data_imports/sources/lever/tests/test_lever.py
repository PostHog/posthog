import json
import dataclasses
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lever import LeverSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lever.lever import (
    LEVER_ENDPOINTS,
    LeverResumeConfig,
    _build_initial_params,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lever.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.lever.source import LeverSource


def _driver() -> SourceDriver:
    return SourceDriver(LeverSource(), LeverSourceConfig(api_key="test_key"))


def _page(items: list[dict[str, Any]], has_next: bool, next_offset: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"data": items, "hasNext": has_next}
    if next_offset is not None:
        body["next"] = next_offset
    return ScriptedResponse(json=body)


class TestBuildInitialParams:
    def test_incremental_filter_converts_seconds_to_milliseconds(self) -> None:
        params = _build_initial_params(LEVER_ENDPOINTS["opportunities"], True, 1700000000, "updatedAt")
        assert params == {"limit": 100, "updated_at_start": 1700000000000}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [
            (200, True),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            is_valid, error = validate_credentials("test_key")

        assert is_valid is expected_valid
        assert network.requests_log[0].path == "/v1/postings"
        assert network.requests_log[0].param("limit") == "1"
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    def test_network_error_is_not_valid(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            is_valid, error = validate_credentials("test_key")

        assert is_valid is False
        assert error is not None
        assert {request.path for request in network.requests_log} == {"/v1/postings"}


class TestLeverSourceResponse:
    def test_partition_key_is_never_updated_at(self) -> None:
        for endpoint in ENDPOINTS:
            assert LEVER_ENDPOINTS[endpoint].partition_key != "updatedAt"


class TestLeverPaginationAndResume:
    def test_fresh_run_paginates_and_normalizes(self) -> None:
        responses = [
            _page([{"id": "o1", "createdAt": 1700000000000}], True, "offset_2"),
            _page([{"id": "o2", "createdAt": 1700000005000}], False),
        ]

        result = _driver().run("opportunities", responses)

        # First request has no offset; second request uses the saved offset token.
        assert result.params("offset") == [None, "offset_2"]
        # `limit` rides in the query params on every request.
        assert result.params("limit") == ["100", "100"]

        # Timestamps were converted ms -> seconds in the yielded rows.
        assert result.rows == [
            {"id": "o1", "createdAt": 1700000000},
            {"id": "o2", "createdAt": 1700000005},
        ]
        assert result.raised is None

    def test_resume_seeds_first_request_with_saved_offset(self) -> None:
        result = _driver().run(
            "opportunities", [_page([{"id": "o5"}], False)], resume_state=LeverResumeConfig(offset="saved_offset")
        )

        assert result.params("offset") == ["saved_offset"]
        assert result.raised is None

    def test_hasnext_without_next_token_raises(self) -> None:
        # hasNext is True but no `next` token -> fail loudly rather than silently
        # truncating the sync with partial data.
        result = _driver().run("opportunities", [_page([{"id": "o1"}], True)])

        assert isinstance(result.raised, Exception)
        assert "hasNext was true but no next offset token" in str(result.raised)
        assert result.saved_states == []


class TestLeverOpportunityChildren:
    @pytest.mark.parametrize("endpoint", ["offers", "interviews", "feedback"])
    def test_fans_out_per_opportunity_and_tags_rows_with_parent(self, endpoint: str) -> None:
        responses = [
            _page([{"id": "opp1"}], True, "parent_2"),
            _page([{"id": "c1", "createdAt": 1700000000000}], True, "child_2"),
            _page([{"id": "c2", "createdAt": 1700000005000}], False),
            _page([{"id": "opp2"}, {"id": "opp_deleted"}], False),
            _page([{"id": "c1", "createdAt": 1700000010000}], False),
            ScriptedResponse(status=404, json={"code": "NotFound"}),
        ]

        result = _driver().run(endpoint, responses)

        assert result.paths == [
            "/v1/opportunities",
            f"/v1/opportunities/opp1/{endpoint}",
            f"/v1/opportunities/opp1/{endpoint}",
            "/v1/opportunities",
            f"/v1/opportunities/opp2/{endpoint}",
            f"/v1/opportunities/opp_deleted/{endpoint}",
        ]
        assert result.queries[0] == {"limit": ("100",), "include": ("id",)}
        assert result.requests[2].param("offset") == "child_2"
        assert result.requests[3].param("offset") == "parent_2"
        assert result.rows == [
            {"id": "c1", "createdAt": 1700000000, "opportunity_id": "opp1"},
            {"id": "c2", "createdAt": 1700000005, "opportunity_id": "opp1"},
            {"id": "c1", "createdAt": 1700000010, "opportunity_id": "opp2"},
        ]
        assert result.raised is None


class TestLeverApplications:
    def test_flattens_expanded_applications_from_opportunities(self) -> None:
        responses = [
            _page(
                [
                    {"applications": [{"id": "a1", "opportunityId": "o1", "createdAt": 1700000000000}]},
                    {"applications": []},
                ],
                True,
                "offset_2",
            ),
            _page([{"applications": [{"id": "a2", "opportunityId": "o2", "createdAt": 1700000005000}]}], False),
        ]

        result = _driver().run("applications", responses)

        assert result.requests[0].url.startswith("https://api.lever.co/v1/opportunities?")
        assert result.queries[0] == {
            "limit": ("100",),
            "expand": ("applications",),
            "include": ("applications",),
        }
        assert result.rows == [
            {"id": "a1", "opportunityId": "o1", "createdAt": 1700000000},
            {"id": "a2", "opportunityId": "o2", "createdAt": 1700000005},
        ]
        assert result.raised is None

    def test_unexpanded_application_ids_fail_loudly(self) -> None:
        result = _driver().run("applications", [_page([{"applications": ["a1"]}], False)])

        assert isinstance(result.raised, ValueError)
        assert "expected expanded applications objects" in str(result.raised)


class TestResumeConfigSerialization:
    def test_round_trip(self) -> None:
        cfg = LeverResumeConfig(offset="abc123")
        reconstituted = LeverResumeConfig(**json.loads(json.dumps(dataclasses.asdict(cfg))))
        assert reconstituted == cfg
