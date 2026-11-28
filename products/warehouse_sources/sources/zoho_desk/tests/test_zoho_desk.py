from collections.abc import Iterator
from typing import Any

import pytest

from requests import HTTPError

from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.sources.zoho_desk._config import ZohoDeskSourceConfig
from products.warehouse_sources.sources.zoho_desk.source import ZohoDeskSource
from products.warehouse_sources.sources.zoho_desk.zoho_desk import (
    ACCESS_TOKENS,
    CLIENT_REJECTED_MESSAGE,
    ZohoDeskAuthError,
    ZohoDeskResumeConfig,
    ZohoDeskTokenUnavailableError,
)

TOKEN_PATH = "/oauth/v2/token"


@pytest.fixture(autouse=True)
def _empty_token_cache() -> Iterator[None]:
    ACCESS_TOKENS.clear()
    yield
    ACCESS_TOKENS.clear()


def _config(**overrides: Any) -> ZohoDeskSourceConfig:
    return ZohoDeskSourceConfig(
        client_id="1000.client", client_secret="client-secret", refresh_token="1000.refresh", **overrides
    )


def _driver(**overrides: Any) -> SourceDriver:
    return SourceDriver(ZohoDeskSource(), _config(**overrides))


def _token(expires_in: int = 3600) -> ScriptedResponse:
    return ScriptedResponse(json={"access_token": "access-token", "expires_in": expires_in})


def _rows(start: int, count: int) -> list[dict[str, Any]]:
    return [{"id": str(index)} for index in range(start, start + count)]


def _page(rows: list[dict[str, Any]], key: str = "data") -> ScriptedResponse:
    return ScriptedResponse(json={key: rows})


def _list_requests(requests: list[RecordedRequest]) -> list[RecordedRequest]:
    return [request for request in requests if request.method == "GET"]


class TestZohoDeskPagination:
    @pytest.mark.parametrize(
        ("last_page", "expected_row_count"),
        [
            pytest.param(_page(_rows(200, 3)), 203, id="short_page"),
            pytest.param(ScriptedResponse(status=204), 200, id="empty_204_after_a_full_page"),
        ],
    )
    def test_walks_one_based_pages_to_the_terminal_page(
        self, last_page: ScriptedResponse, expected_row_count: int
    ) -> None:
        result = _driver().run(
            "tickets",
            route(
                {
                    TOKEN_PATH: [_token()],
                    "/api/v1/tickets": [_page(_rows(0, 100)), _page(_rows(100, 100)), last_page],
                }
            ),
        )

        assert result.raised is None
        assert len(result.rows) == expected_row_count
        pages = _list_requests(result.requests)
        assert [page.param("from") for page in pages] == ["1", "101", "201"]
        assert {page.param("limit") for page in pages} == {"100"}
        assert {page.param("sortBy") for page in pages} == {"createdTime"}
        assert {page.headers["authorization"] for page in pages} == {"Zoho-oauthtoken access-token"}
        assert all("orgid" not in page.headers for page in pages)
        assert result.committed_states == [ZohoDeskResumeConfig(next_index=101), ZohoDeskResumeConfig(next_index=201)]

    def test_resumes_from_the_saved_index(self) -> None:
        result = _driver().run(
            "tickets",
            route({TOKEN_PATH: [_token()], "/api/v1/tickets": [_page(_rows(200, 3))]}),
            resume_state=ZohoDeskResumeConfig(next_index=201),
        )

        assert [page.param("from") for page in _list_requests(result.requests)] == ["201"]

    @pytest.mark.parametrize(
        ("pages", "resume_state", "expected_from", "expected_ids"),
        [
            pytest.param(
                [_page(_rows(0, 200)), _page([{"id": "199"}, {"id": "200"}])],
                None,
                ["0", "200"],
                [str(index) for index in range(201)],
                id="fresh_run",
            ),
            pytest.param(
                [_page([{"id": "199"}, {"id": "200"}])],
                ZohoDeskResumeConfig(next_index=200, last_id="199"),
                ["200"],
                ["200"],
                id="resumed_run",
            ),
        ],
    )
    def test_zero_based_walk_drops_the_record_a_one_based_endpoint_repeats(
        self,
        pages: list[ScriptedResponse],
        resume_state: ZohoDeskResumeConfig | None,
        expected_from: list[str],
        expected_ids: list[str],
    ) -> None:
        result = _driver().run(
            "agents", route({TOKEN_PATH: [_token()], "/api/v1/agents": pages}), resume_state=resume_state
        )

        assert result.raised is None
        assert [page.param("from") for page in _list_requests(result.requests)] == expected_from
        assert [row["id"] for row in result.rows] == expected_ids

    def test_saves_the_last_record_id_for_an_endpoint_that_drops_repeats(self) -> None:
        result = _driver().run(
            "agents",
            route({TOKEN_PATH: [_token()], "/api/v1/agents": [_page(_rows(0, 200)), _page(_rows(200, 1))]}),
        )

        assert result.committed_states == [ZohoDeskResumeConfig(next_index=200, last_id="199")]

    def test_does_not_follow_a_redirect_from_the_desk_host(self) -> None:
        result = _driver().run(
            "tickets",
            route(
                {
                    TOKEN_PATH: [_token()],
                    "/api/v1/tickets": [
                        ScriptedResponse(status=302, headers={"Location": "https://attacker.example/api/v1/tickets"})
                    ],
                }
            ),
        )

        assert result.raised is not None
        assert {request.origin for request in result.requests} == {"https://accounts.zoho.com", "https://desk.zoho.com"}

    def test_reads_teams_from_their_own_response_key(self) -> None:
        result = _driver().run(
            "teams",
            route({TOKEN_PATH: [_token()], "/api/v1/teams": [_page([{"id": "team-1"}], key="teams")]}),
        )

        assert result.rows == [{"id": "team-1"}]


class TestZohoDeskAuth:
    @pytest.mark.parametrize(
        ("expires_in", "expected_token_requests"),
        [
            pytest.param(3600, 1, id="token_outlives_the_run"),
            pytest.param(60, 3, id="token_inside_the_refresh_margin"),
        ],
    )
    def test_mints_a_new_token_only_when_the_old_one_is_about_to_expire(
        self, expires_in: int, expected_token_requests: int
    ) -> None:
        result = _driver().run(
            "tickets",
            route(
                {
                    TOKEN_PATH: [_token(expires_in)] * 3,
                    "/api/v1/tickets": [_page(_rows(0, 100)), _page(_rows(100, 100)), _page(_rows(200, 3))],
                }
            ),
        )

        assert result.raised is None
        assert len([request for request in result.requests if request.method == "POST"]) == expected_token_requests

    @pytest.mark.parametrize(
        ("second_answer", "expected_error", "expected_row_count"),
        [
            pytest.param(_page(_rows(0, 3)), None, 3, id="new_token_accepted"),
            pytest.param(
                ScriptedResponse(status=401, json={"errorCode": "INVALID_OAUTH"}), HTTPError, 0, id="new_token_rejected"
            ),
        ],
    )
    def test_a_401_is_sent_again_once_with_a_new_token(
        self, second_answer: ScriptedResponse, expected_error: type[Exception] | None, expected_row_count: int
    ) -> None:
        result = _driver().run(
            "tickets",
            route(
                {
                    TOKEN_PATH: [
                        ScriptedResponse(json={"access_token": "first-token", "expires_in": 3600}),
                        ScriptedResponse(json={"access_token": "second-token", "expires_in": 3600}),
                    ],
                    "/api/v1/tickets": [
                        ScriptedResponse(status=401, json={"errorCode": "INVALID_OAUTH"}),
                        second_answer,
                    ],
                }
            ),
        )

        assert (type(result.raised) if result.raised else None) is expected_error
        assert len(result.rows) == expected_row_count
        assert [page.headers["authorization"] for page in _list_requests(result.requests)] == [
            "Zoho-oauthtoken first-token",
            "Zoho-oauthtoken second-token",
        ]

    def test_a_503_from_the_token_endpoint_is_retried_while_a_401_is_sent_again(self) -> None:
        result = _driver().run(
            "tickets",
            route(
                {
                    TOKEN_PATH: [
                        ScriptedResponse(json={"access_token": "first-token", "expires_in": 3600}),
                        ScriptedResponse(status=503),
                        ScriptedResponse(json={"access_token": "second-token", "expires_in": 3600}),
                    ],
                    "/api/v1/tickets": [ScriptedResponse(status=401), _page(_rows(0, 3))],
                }
            ),
        )

        assert result.raised is None
        assert len(result.rows) == 3

    def test_table_syncs_with_the_same_credentials_share_one_token(self) -> None:
        first = _driver().run("tickets", route({TOKEN_PATH: [_token()], "/api/v1/tickets": [_page(_rows(0, 1))]}))
        second = _driver().run("contacts", route({"/api/v1/contacts": [_page(_rows(0, 1))]}))

        assert first.raised is None and second.raised is None
        assert [request.method for request in second.requests] == ["GET"]
        assert second.requests[0].headers["authorization"] == "Zoho-oauthtoken access-token"

    def test_sends_requests_to_the_hosts_of_the_picked_data_center(self) -> None:
        result = _driver(region="eu", organization_id="2389290").run(
            "tickets",
            route({TOKEN_PATH: [_token()], "/api/v1/tickets": [_page(_rows(0, 1))]}),
        )

        token_request, list_request = result.requests
        assert token_request.origin == "https://accounts.zoho.eu"
        assert list_request.origin == "https://desk.zoho.eu"
        assert list_request.headers["orgid"] == "2389290"

    @pytest.mark.parametrize(
        ("token_response", "expected_error"),
        [
            pytest.param(
                ScriptedResponse(json={"error": "invalid_code"}), ZohoDeskAuthError, id="rejected_refresh_token"
            ),
            pytest.param(
                ScriptedResponse(status=400, json={"error": "Access Denied"}),
                ZohoDeskTokenUnavailableError,
                id="unknown_code_with_4xx",
            ),
            pytest.param(ScriptedResponse(status=400), HTTPError, id="4xx_with_no_body"),
            pytest.param(ScriptedResponse(json={}), ZohoDeskTokenUnavailableError, id="no_token_and_no_code"),
        ],
    )
    def test_only_a_known_credential_error_is_a_permanent_auth_error(
        self, token_response: ScriptedResponse, expected_error: type[Exception]
    ) -> None:
        result = _driver().run("tickets", route({TOKEN_PATH: [token_response]}))

        assert type(result.raised) is expected_error
        assert result.rows == []

    @pytest.mark.parametrize(
        ("script", "expected"),
        [
            pytest.param([_token()], (True, None), id="valid"),
            pytest.param(
                [ScriptedResponse(json={"error": "invalid_client"})],
                (False, CLIENT_REJECTED_MESSAGE),
                id="client_from_another_data_center",
            ),
            pytest.param(
                always(ScriptedResponse(status=503)),
                (False, "Could not get an access token from Zoho. Wait a minute, then try again."),
                id="accounts_host_unavailable",
            ),
        ],
    )
    def test_validate_credentials_reports_the_token_exchange_result(
        self, script: Any, expected: tuple[bool, str | None]
    ) -> None:
        with scripted_network(script):
            assert ZohoDeskSource().validate_credentials(_config(), team_id=1) == expected
