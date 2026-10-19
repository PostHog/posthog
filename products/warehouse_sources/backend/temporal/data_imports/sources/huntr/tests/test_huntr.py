from typing import Any

import pytest

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.huntr import HuntrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.huntr.huntr import (
    HuntrResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.huntr.settings import (
    ENDPOINTS,
    HUNTR_ENDPOINTS,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.huntr.source import HuntrSource


def _page(items: list[dict[str, Any]] | None, next_cursor: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"data": items if items is not None else []}
    if next_cursor is not None:
        body["next"] = next_cursor
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(HuntrSource(), HuntrSourceConfig(access_token="huntr-token"))


class TestPagination:
    def test_follows_cursor_until_next_is_null(self) -> None:
        result = _driver().run("members", [_page([{"id": "a"}], next_cursor="a"), _page([{"id": "b"}])])

        assert result.raised is None
        assert result.rows == [{"id": "a"}, {"id": "b"}]
        # First request omits `next`; the second passes the cursor from the previous page.
        assert result.params("next") == [None, "a"]
        assert result.params("limit") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        # State is saved after the first page (cursor advances to "a"); the null cursor stops us.
        assert result.saved_states == [HuntrResumeConfig(next="a")]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run("members", [_page([{"id": "b"}])], resume_state=HuntrResumeConfig(next="a"))

        # The first (cursorless) page must never be fetched on resume.
        assert result.raised is None
        assert result.rows == [{"id": "b"}]
        assert len(result.requests) == 1
        assert result.params("next") == ["a"]

    def test_empty_first_page_yields_nothing(self) -> None:
        result = _driver().run("members", [_page([])])

        assert result.raised is None
        assert result.rows == []
        assert result.saved_states == []


class TestCandidateActionMetrics:
    def test_fans_out_over_candidates_and_explodes_action_types(self) -> None:
        metrics = {"uniqueEmployersCt": 1, "totalCt": 2, "employers": [{"id": "e1", "name": "Acme", "totalCt": 2}]}
        result = _driver().run(
            "candidate_action_metrics",
            [
                _page([{"id": "c1"}, {"id": "c2"}], next_cursor="c2"),
                ScriptedResponse(json={"CANDIDATE_PROFILE_VIEWED": metrics, "OTHER_ACTION": {"totalCt": 5}}),
                # Candidate deleted between the listing and the metrics fetch.
                ScriptedResponse(status=404, json={"error": "not found"}),
                _page([{"id": "c3"}]),
                ScriptedResponse(json={}),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"candidate_id": "c1", "action_type": "CANDIDATE_PROFILE_VIEWED", **metrics},
            {"candidate_id": "c1", "action_type": "OTHER_ACTION", "totalCt": 5},
        ]
        assert len(result.requests) == 5
        assert result.requests[0].query == {"limit": (str(PAGE_SIZE),)}
        assert result.requests[3].query == {"limit": (str(PAGE_SIZE),), "next": ("c2",)}
        assert result.requests[1].param("limit") is None


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_are_reissued(self, _name: str, status: int) -> None:
        result = _driver().run("members", [ScriptedResponse(status=status, json={}), _page([{"id": "a"}])])

        assert result.raised is None
        assert result.rows == [{"id": "a"}]
        assert len(result.requests) == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise(self, _name: str, status: int) -> None:
        result = _driver().run("members", [ScriptedResponse(status=status, json={"error": "nope"})])

        assert isinstance(result.raised, HTTPError)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Huntr access token"),
            (403, False, "Invalid Huntr access token"),
            (500, False, "Huntr returned HTTP 500"),
        ],
    )
    def test_status_mapping(self, status: int, expected_valid: bool, expected_message: str | None) -> None:
        # The transport retries a 500, so the script answers every try.
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("huntr-token") == (expected_valid, expected_message)

        assert len(network.requests_log) == 1 or status >= 500
        assert network.requests_log[0].path == "/org/members"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer huntr-token"

    def test_connection_error_is_not_valid(self) -> None:
        # validate_via_probe swallows transport errors; the token is simply "not validated".
        def fail(_request: Any) -> ScriptedResponse:
            raise ConnectionError("boom")

        with scripted_network(fail):
            assert validate_credentials("huntr-token") == (False, "Could not validate Huntr access token")


class TestHuntrSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        answer = ScriptedResponse(json=[] if endpoint == "tags" else {"data": []})
        result = _driver().run(endpoint, [answer])

        assert result.raised is None
        assert result.response is not None
        response = result.response
        assert response.name == endpoint
        assert response.primary_keys == HUNTR_ENDPOINTS[endpoint].primary_keys
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None
