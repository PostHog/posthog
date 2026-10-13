from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zenduty import (
    ZendutySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zenduty.source import ZendutySource
from products.warehouse_sources.backend.temporal.data_imports.sources.zenduty.zenduty import (
    ZendutyResumeConfig,
    ZendutyRetryableError,
    _extract_items_and_next,
    _fetch_page,
    probe_credentials,
)


class TestExtractItemsAndNext:
    def test_bare_list_returns_no_next(self) -> None:
        # Smaller team-nested collections come back as a bare array with no pagination envelope.
        rows, next_url = _extract_items_and_next([{"a": 1}, {"a": 2}])
        assert rows == [{"a": 1}, {"a": 2}]
        assert next_url is None

    @parameterized.expand(
        [
            ("empty_results", {"results": []}, [], None),
            ("null_results", {"results": None}, [], None),
            ("single_object", {"unique_id": "x"}, [{"unique_id": "x"}], None),
            ("unexpected_type", "nope", [], None),
        ]
    )
    def test_edge_shapes(self, _name: str, data: Any, expected_rows: list, expected_next: Any) -> None:
        assert _extract_items_and_next(data) == (expected_rows, expected_next)


class TestFetchPage:
    def _response(self, status_code: int, json_value: Any = None, raises_json: bool = False) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.text = "body"
        if raises_json:
            response.json.side_effect = ValueError("not json")
        else:
            response.json.return_value = json_value
        response.headers = {}
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} Client Error", response=response) if status_code >= 400 else None
        )
        return response

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_transient_status_raises_retryable(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = self._response(status_code)
        # Retry wrapper re-raises the last error after exhausting attempts.
        with pytest.raises(ZendutyRetryableError):
            _fetch_page(session, "https://www.zenduty.com/api/incidents/", {}, MagicMock())

    def test_non_json_2xx_is_retryable(self) -> None:
        # Zenduty's WAF answered our unauthenticated probe with a non-JSON "Blocked" body (HTTP 209);
        # treat an unparseable 2xx as transient rather than crashing the sync.
        session = MagicMock()
        session.get.return_value = self._response(209, raises_json=True)
        with pytest.raises(ZendutyRetryableError):
            _fetch_page(session, "https://www.zenduty.com/api/incidents/", {}, MagicMock())

    def test_forbidden_raises_http_error(self) -> None:
        session = MagicMock()
        session.get.return_value = self._response(403)
        with pytest.raises(requests.HTTPError):
            _fetch_page(session, "https://www.zenduty.com/api/account/teams/", {}, MagicMock())

    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/api/incidents/"),
            ("plain_http", "http://www.zenduty.com/api/incidents/"),
            ("host_suffix_trick", "https://www.zenduty.com.evil.example.com/api/incidents/"),
        ]
    )
    def test_non_zenduty_url_is_refused_without_a_request(self, _name: str, url: str) -> None:
        # Requests carry the account API key, so a tampered `next` URL or poisoned resume
        # checkpoint must never be fetched.
        session = MagicMock()
        with pytest.raises(ValueError):
            _fetch_page(session, url, {}, MagicMock())
        session.get.assert_not_called()

    def test_redirect_is_refused(self) -> None:
        # A redirect off the validated origin would re-send the API key wherever it points.
        session = MagicMock()
        session.get.return_value = self._response(302)
        with pytest.raises(ValueError):
            _fetch_page(session, "https://www.zenduty.com/api/incidents/", {}, MagicMock())
        assert session.get.call_args.kwargs["allow_redirects"] is False


def _driver() -> SourceDriver:
    return SourceDriver(ZendutySource(), ZendutySourceConfig(api_key="tok"))


class TestGetRowsTopLevel:
    def test_follows_next_across_pages(self) -> None:
        second = "https://www.zenduty.com/api/incidents/?page=2"
        result = _driver().run(
            "incidents",
            [
                ScriptedResponse(json={"results": [{"unique_id": "1"}], "next": second}),
                ScriptedResponse(json={"results": [{"unique_id": "2"}], "next": None}),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"unique_id": "1"}, {"unique_id": "2"}]
        assert result.paths == ["/api/incidents/", "/api/incidents/"]
        assert result.params("page_size") == ["100", None]
        assert result.params("page") == [None, "2"]
        assert result.saved_states == [ZendutyResumeConfig(next_url=second)]

    def test_poisoned_next_url_is_never_persisted(self) -> None:
        result = _driver().run(
            "incidents",
            [ScriptedResponse(json={"results": [{"unique_id": "1"}], "next": "https://evil.example.com/steal"})],
        )
        assert isinstance(result.raised, ValueError)
        assert result.rows == [{"unique_id": "1"}]
        assert result.paths == ["/api/incidents/"]
        assert result.saved_states == []


class TestGetRowsFanOut:
    def _team_pages(self) -> list[ScriptedResponse]:
        return [ScriptedResponse(json={"results": [{"unique_id": "team-a"}, {"unique_id": "team-b"}], "next": None})]

    def test_walks_each_team_and_injects_parent_id(self) -> None:
        result = _driver().run(
            "services",
            [
                *self._team_pages(),
                ScriptedResponse(json={"results": [{"unique_id": "svc-1"}], "next": None}),
                ScriptedResponse(json={"results": [{"unique_id": "svc-2"}], "next": None}),
            ],
        )
        assert result.raised is None
        assert result.paths == [
            "/api/account/teams/",
            "/api/account/teams/team-a/services/",
            "/api/account/teams/team-b/services/",
        ]
        assert result.params("page_size") == ["100", "100", "100"]
        # Each child row carries the parent team's id so the composite key stays unique table-wide.
        assert result.rows == [
            {"unique_id": "svc-1", "_zenduty_team_id": "team-a"},
            {"unique_id": "svc-2", "_zenduty_team_id": "team-b"},
        ]

    def test_checkpoints_next_team_when_a_team_completes(self) -> None:
        result = _driver().run(
            "services",
            [
                *self._team_pages(),
                ScriptedResponse(json={"results": [{"unique_id": "svc-1"}], "next": None}),
                ScriptedResponse(json={"results": [{"unique_id": "svc-2"}], "next": None}),
            ],
        )
        assert result.raised is None
        assert result.paths == [
            "/api/account/teams/",
            "/api/account/teams/team-a/services/",
            "/api/account/teams/team-b/services/",
        ]
        # After team-a completes, state points at team-b's start so a resume skips team-a entirely.
        assert result.saved_states == [ZendutyResumeConfig(next_url=None, team_id="team-b")]

    def test_resume_skips_completed_teams(self) -> None:
        # A resumed run still lists teams, then fetches only team-b's collection.
        result = _driver().run(
            "services",
            [*self._team_pages(), ScriptedResponse(json={"results": [{"unique_id": "svc-2"}], "next": None})],
            resume_state=ZendutyResumeConfig(next_url=None, team_id="team-b"),
        )
        assert result.raised is None
        assert result.paths == ["/api/account/teams/", "/api/account/teams/team-b/services/"]
        assert result.rows == [{"unique_id": "svc-2", "_zenduty_team_id": "team-b"}]

    def test_no_teams_yields_nothing(self) -> None:
        result = _driver().run("services", [ScriptedResponse(json={"results": [], "next": None})])
        assert result.raised is None
        assert result.paths == ["/api/account/teams/"]
        assert result.rows == []


class TestProbeCredentials:
    @parameterized.expand([("ok", 200), ("forbidden_bad_token", 403), ("server_error", 500)])
    def test_returns_status_code(self, _name: str, status_code: int) -> None:
        with scripted_network(lambda _request: ScriptedResponse(status=status_code)) as network:
            assert probe_credentials("tok") == status_code
        assert network.requests_log
        assert all(request.path == "/api/account/teams/" for request in network.requests_log)
        assert all(request.param("page_size") == "1" for request in network.requests_log)
        assert all(request.headers["authorization"] == "Token tok" for request in network.requests_log)

    def test_connection_failure_returns_none(self) -> None:
        def fail(_request: Any) -> ScriptedResponse:
            raise requests.ConnectionError("boom")

        with scripted_network(fail) as network:
            assert probe_credentials("tok") is None
        assert network.requests_log
