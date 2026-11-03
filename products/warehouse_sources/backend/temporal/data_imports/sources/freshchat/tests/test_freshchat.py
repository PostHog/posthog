from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientNonRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.freshchat import (
    FreshchatHostNotAllowedError,
    FreshchatResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.settings import (
    PER_PAGE,
    USERS_CREATED_FROM,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.source import FreshchatSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.freshchat import (
    FreshchatSourceConfig,
)

BASE_HOST = "acme.freshchat.com"

# What a Freshworks portal domain answers with on these paths: the web app, not the API.
HTML_BODY = b"<!DOCTYPE html><html><head><title>Freshworks</title></head><body></body></html>"


def _page(data_key: str, items: list[dict[str, Any]], current: int, total_pages: int) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            data_key: items,
            "pagination": {"current_page": current, "total_pages": total_pages, "total_items": 999},
        }
    )


def _driver(domain: str = BASE_HOST, api_key: str = "key") -> SourceDriver:
    return SourceDriver(FreshchatSource(), FreshchatSourceConfig(domain=domain, api_key=api_key))


class TestGetRows:
    def test_paginates_by_page_number_and_saves_state(self) -> None:
        result = _driver().run(
            "agents",
            [
                _page("agents", [{"id": 1}], current=1, total_pages=2),
                _page("agents", [{"id": 2}], current=2, total_pages=2),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}]
        # The API reports total_pages=2, so it stops right after page 2 — no extra empty request.
        assert len(result.requests) == 2
        assert result.params("page") == ["1", "2"]
        assert result.params("items_per_page") == [str(PER_PAGE), str(PER_PAGE)]
        # State saved once, pointing at page 2 (the next page after the first was written).
        assert result.saved_states == [FreshchatResumeConfig(page=2)]

    def test_outbound_messages_is_one_unpaginated_request(self) -> None:
        # The endpoint documents no paging and returns every message at once. Page params would
        # make the paginator re-request the same array until it hit an empty page that never comes.
        messages = [
            {"message_id": "m1", "request_id": "r1", "status": "Delivered", "created_on": 1700000000},
            {"message_id": "m2", "request_id": "r1", "status": "Failed", "failure_code": "OBM001"},
        ]
        result = _driver().run("outbound_messages", [ScriptedResponse(json={"outbound_messages": messages})])

        assert result.raised is None
        assert result.rows == messages
        assert len(result.requests) == 1
        assert result.requests[0].path == "/v2/outbound-messages"
        assert result.requests[0].query == {}
        assert result.saved_states == []

    def test_bearer_token_is_redacted_from_samples(self) -> None:
        # The token rides in the Authorization header; it must be value-redacted from captured
        # HTTP samples via the tracked session's redact_values.
        result = _driver(api_key="secret-key").run("agents", [_page("agents", [{"id": 1}], 1, 1)])

        assert result.raised is None
        assert "secret-key" in result.session_options[0].get("redact_values", ())

    @pytest.mark.parametrize("status_code", [401, 403, 404])
    def test_non_retryable_status_raises(self, status_code: int) -> None:
        result = _driver().run("agents", [ScriptedResponse(status=status_code, json={"error": "boom"})])

        assert isinstance(result.raised, requests.HTTPError)

    def test_html_body_raises_the_mapped_non_retryable_error(self) -> None:
        # A domain that serves the web app answers 200 with HTML. That must fail the table once with
        # the message the source maps, not retry a body that can never parse.
        result = _driver().run("agents", [ScriptedResponse(body=HTML_BODY)])

        assert isinstance(result.raised, RESTClientNonRetryableError)
        assert str(result.raised).startswith("Non-JSON response from")
        assert len(result.requests) == 1

    def test_disallowed_host_raises_before_any_request(self) -> None:
        # A saved-then-edited domain must never receive the stored token at sync time (SSRF).
        result = _driver(domain="metadata.google.internal").run("agents", [])

        assert isinstance(result.raised, FreshchatHostNotAllowedError)
        assert result.requests == []

    def test_redirect_response_raises_and_is_not_followed(self) -> None:
        # A 3xx from the allowed host could point anywhere; following it would defeat the host
        # allowlist, so it must surface as a hard error instead.
        result = _driver().run(
            "agents", [ScriptedResponse(status=302, headers={"Location": "http://169.254.169.254/"})]
        )

        assert isinstance(result.raised, ValueError)
        assert len(result.requests) == 1


class TestFanout:
    """Freshchat exposes no top-level conversations list, so both conversation tables are reached
    by fanning out from Users."""

    def test_user_conversations_carries_the_parent_user_id(self) -> None:
        result = _driver().run(
            "user_conversations",
            route(
                {
                    "/v2/users": [_page("users", [{"id": "u1"}, {"id": "u2"}], current=1, total_pages=1)],
                    "/v2/users/u1/conversations": [ScriptedResponse(json={"conversations": [{"id": "c1"}]})],
                    "/v2/users/u2/conversations": [
                        ScriptedResponse(json={"conversations": [{"id": "c2"}, {"id": "c3"}]})
                    ],
                }
            ),
        )

        assert result.raised is None
        # A conversation can be listed under more than one user, so the row has to name its parent
        # — the primary key is (user_id, id).
        assert result.rows == [
            {"id": "c1", "user_id": "u1"},
            {"id": "c2", "user_id": "u2"},
            {"id": "c3", "user_id": "u2"},
        ]
        assert result.requests[0].param("created_from") == USERS_CREATED_FROM
        # The child endpoint documents no query params; sending page-size or sort params there
        # would be undocumented guesswork.
        assert result.requests[1].query == {}

    def test_conversation_messages_is_not_resumable(self) -> None:
        result = _driver().run(
            "conversation_messages",
            [_page("users", [], current=1, total_pages=1)],
            resume_state=FreshchatResumeConfig(page=2),
        )

        assert result.response is not None
        assert result.response.supports_resume is False


class TestValidateCredentials:
    # A Freshworks portal domain answers the probe with its web app, not the API. An empty body and
    # a truncated body stay acceptable, because the sync path reads an empty 2xx as an empty page
    # and retries a truncated one, rather than calling either a broken host.
    @pytest.mark.parametrize(
        "body, returned_json",
        [(HTML_BODY, False), (b"", True), (b'{"configuration": {"app_id"', True)],
    )
    def test_probe_reports_whether_the_body_is_json(self, body: bytes, returned_json: bool) -> None:
        with scripted_network([ScriptedResponse(body=body)]) as network:
            assert validate_credentials(BASE_HOST, "key") == (200, returned_json)

        assert network.requests_log[0].path == "/v2/accounts/configuration"

    def test_session_redacts_api_key_from_samples(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            validate_credentials(BASE_HOST, "secret-key")

        assert network.session_options[0].get("redact_values") == ("secret-key",)

    def test_probe_disables_redirects_to_protect_token(self) -> None:
        # The token rides on the probe; the session must be built with redirects pinned off so a
        # redirect can't replay it to the redirect target during validation.
        with scripted_network([ScriptedResponse()]) as network:
            validate_credentials(BASE_HOST, "key")

        assert network.session_options[0].get("allow_redirects") is False
