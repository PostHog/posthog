from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.persistiq import (
    PersistIqSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.persistiq.persistiq import (
    PersistiqResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.persistiq.source import PersistIqSource


def _driver(api_key: str = "pq-key") -> SourceDriver:
    return SourceDriver(PersistIqSource(), PersistIqSourceConfig(api_key=api_key))


def _page(items: list[dict[str, Any]], has_more: bool, list_key: str = "leads") -> ScriptedResponse:
    return ScriptedResponse(json={list_key: items, "has_more": has_more, "next_page": None})


class TestPagination:
    def test_single_page_yields_items_and_stops(self) -> None:
        result = _driver().run("leads", [_page([{"id": "l_1"}, {"id": "l_2"}], has_more=False)])

        assert result.raised is None
        assert result.rows == [{"id": "l_1"}, {"id": "l_2"}]
        assert result.params("page") == ["1"]
        # No further pages, so no resume state is persisted.
        assert result.saved_states == []

    def test_follows_pagination_until_has_more_is_false(self) -> None:
        result = _driver().run(
            "leads",
            [
                _page([{"id": "l_1"}], has_more=True),
                _page([{"id": "l_2"}], has_more=True),
                # The final page carries rows AND has_more=False — termination reads the flag, not
                # an empty page, so no extra request is made past it.
                _page([{"id": "l_3"}], has_more=False),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["l_1", "l_2", "l_3"]
        assert result.params("page") == ["1", "2", "3"]

    def test_saves_next_page_after_yielding_each_batch(self) -> None:
        result = _driver().run("leads", [_page([{"id": "l_1"}], has_more=True), _page([{"id": "l_2"}], has_more=False)])

        # State is saved after page 1 is yielded (pointing at page 2), and never for the final page.
        assert result.raised is None
        assert result.saved_states == [PersistiqResumeConfig(next_page=2)]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "leads",
            [_page([{"id": "l_2"}], has_more=True), _page([{"id": "l_3"}], has_more=False)],
            resume_state=PersistiqResumeConfig(next_page=2),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["l_2", "l_3"]
        # Page 1 must never be fetched on resume.
        assert result.params("page") == ["2", "3"]

    def test_empty_first_page_yields_nothing_and_no_checkpoint(self) -> None:
        result = _driver().run("leads", [_page([], has_more=False)])

        assert result.raised is None
        assert result.rows == []
        assert result.params("page") == ["1"]
        assert result.saved_states == []

    def test_uses_endpoint_specific_list_key(self) -> None:
        # `users` reads rows from the "users" envelope key, not "leads".
        result = _driver().run("users", [_page([{"id": "u_1"}], has_more=False, list_key="users")])

        assert result.raised is None
        assert result.rows == [{"id": "u_1"}]

    def test_registers_api_key_for_redaction(self) -> None:
        # The api key rides in the `x-api-key` header through the tracked transport; it must be
        # registered for redaction so it never lands in HTTP logs, samples, or error messages.
        result = _driver(api_key="secret").run("leads", [_page([], has_more=False)])

        assert result.raised is None
        assert result.requests[0].headers["x-api-key"] == "secret"
        assert result.session_options == [{"redact_values": ("secret",)}]


class TestMalformedBody:
    def test_missing_list_key_is_retried_then_succeeds(self) -> None:
        result = _driver().run(
            "leads", [ScriptedResponse(json={"has_more": False}), _page([{"id": "l_1"}], has_more=False)]
        )

        assert result.raised is None
        assert result.rows == [{"id": "l_1"}]
        assert result.params("page") == ["1", "1"]

    def test_non_dict_body_is_retried_then_succeeds(self) -> None:
        result = _driver().run(
            "leads", [ScriptedResponse(json=[{"id": "l_1"}]), _page([{"id": "l_1"}], has_more=False)]
        )

        assert result.raised is None
        assert result.rows == [{"id": "l_1"}]
        assert result.params("page") == ["1", "1"]

    def test_persistently_malformed_body_exhausts_and_raises(self) -> None:
        result = _driver().run("leads", always(ScriptedResponse(json={"has_more": False})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert result.params("page") == ["1"] * 5


class TestRetries:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_status_is_retried_then_succeeds(self, status: int) -> None:
        result = _driver().run(
            "leads", [ScriptedResponse(status=status, json={}), _page([{"id": "l_1"}], has_more=False)]
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["l_1"]
        assert result.params("page") == ["1", "1"]

    def test_retries_exhaust_then_raise(self) -> None:
        result = _driver().run("leads", always(ScriptedResponse(status=500, json={})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert result.params("page") == ["1"] * 5

    @pytest.mark.parametrize(
        ("status", "reason"),
        [(401, "Unauthorized"), (403, "Forbidden"), (404, "Not Found")],
    )
    def test_client_errors_raise_http_error_without_retry(self, status: int, reason: str) -> None:
        result = _driver().run("leads", [ScriptedResponse(status=status, json={})])

        assert isinstance(result.raised, requests.HTTPError)
        assert f"{status} Client Error: {reason}" in str(result.raised)
        assert result.params("page") == ["1"]

    def test_unauthorized_message_matches_non_retryable_mapping(self) -> None:
        # source.py maps this exact substring to the friendly invalid-key message.
        result = _driver().run("leads", [ScriptedResponse(status=401, json={})])

        assert isinstance(result.raised, requests.HTTPError)
        assert "401 Client Error: Unauthorized for url: https://api.persistiq.com/v1" in str(result.raised)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (200, (True, None)),
        ],
    )
    def test_status_mapping(self, status: int, expected: tuple[bool, str | None]) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            actual = validate_credentials("pq-key")

        assert actual == expected
        assert network.requests_log
        assert {request.path for request in network.requests_log} == {"/v1/users"}
        assert {request.param("page") for request in network.requests_log} == {"1"}
        assert {request.headers["x-api-key"] for request in network.requests_log} == {"pq-key"}
