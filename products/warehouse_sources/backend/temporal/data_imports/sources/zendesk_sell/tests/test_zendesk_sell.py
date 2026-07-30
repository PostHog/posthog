import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell.zendesk_sell import (
    PER_PAGE,
    ZendeskSellResumeConfig,
    ZendeskSellUntrustedURLError,
    _validate_pagination_url,
    validate_credentials,
    zendesk_sell_source,
)

# The RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the zendesk_sell module.
ZENDESK_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell.zendesk_sell.make_tracked_session"
)
# Where tenacity sleeps between retries — patch so the retry loop doesn't actually block.
TENACITY_SLEEP_PATCH = "tenacity.nap.time.sleep"

FIRST_URL = "https://api.getbase.com/v2/contacts"
PAGE_2_URL = "https://api.getbase.com/v2/contacts?page=2&per_page=100"


def _envelope(records: list[dict[str, Any]], next_page: str | None) -> dict[str, Any]:
    """Build the Zendesk Sell collection envelope around a list of record dicts."""
    links: dict[str, Any] = {"self": "https://api.getbase.com/v2/contacts?page=1&per_page=100"}
    if next_page:
        links["next_page"] = next_page
    return {
        "items": [{"data": r, "meta": {"type": "contact"}} for r in records],
        "meta": {"type": "collection", "count": len(records), "links": links},
    }


def _response(body: dict[str, Any], status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = FIRST_URL
    return resp


def _make_manager(resume_state: ZendeskSellResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Any]) -> tuple[list[str | None], list[dict[str, Any]]]:
    """Wire a mock session and capture each request's URL and params AT SEND TIME.

    ``request.url``/``request.params`` are mutated in place across pages (the next-page URL replaces
    the previous one), so inspecting them after the run shows only the final state — snapshot at
    prepare_request time instead. ``responses`` may hold ``Response`` objects or a callable side_effect.
    """
    session.headers = {}
    url_snapshots: list[str | None] = []
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        url_snapshots.append(request.url)
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots, param_snapshots


def _source(endpoint: str, manager: mock.MagicMock):
    return zendesk_sell_source(
        access_token="token",
        endpoint=endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_yields_unwrapped_records_across_pages(self, MockSession) -> None:
        session = MockSession.return_value
        urls, params = _wire(
            session,
            [
                _response(_envelope([{"id": 1}, {"id": 2}], next_page=PAGE_2_URL)),
                _response(_envelope([{"id": 3}], next_page=None)),
            ],
        )

        rows = _rows(_source("contacts", _make_manager()))

        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        # First request hits the base path with per_page; the second follows meta.links.next_page verbatim.
        assert urls[0] == FIRST_URL
        assert params[0] == {"per_page": PER_PAGE}
        assert urls[1] == PAGE_2_URL

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_only_when_more_pages_remain(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(_envelope([{"id": 1}], next_page=PAGE_2_URL)),
                _response(_envelope([{"id": 2}], next_page=None)),
            ],
        )

        manager = _make_manager()
        _rows(_source("contacts", manager))

        # Exactly one checkpoint: after the first page (which had a next_page). The final page must not
        # persist state, so a completed sync leaves nothing to resume into.
        manager.save_state.assert_called_once_with(ZendeskSellResumeConfig(next_url=PAGE_2_URL))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, MockSession) -> None:
        session = MockSession.return_value
        urls, _params = _wire(session, [_response(_envelope([{"id": 2}], next_page=None))])

        manager = _make_manager(ZendeskSellResumeConfig(next_url=PAGE_2_URL))
        rows = _rows(_source("contacts", manager))

        # The initial page is never requested — only the saved next_url is fetched.
        assert rows == [{"id": 2}]
        assert session.send.call_count == 1
        assert urls[0] == PAGE_2_URL

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_collection_yields_nothing_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(_envelope([], next_page=None))])

        manager = _make_manager()
        rows = _rows(_source("contacts", manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_item_without_data_fails_fast(self, MockSession) -> None:
        session = MockSession.return_value
        # Every envelope item must carry `data`; a missing key is a malformed response and must raise
        # rather than silently drop the record.
        _wire(session, [_response({"items": [{"meta": {"type": "contact"}}], "meta": {"links": {}}})])

        with pytest.raises(KeyError):
            _rows(_source("contacts", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_hostile_upstream_next_page_is_rejected(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(_envelope([{"id": 1}], next_page="https://evil.example.com/v2/contacts"))])

        manager = _make_manager()
        with pytest.raises(ZendeskSellUntrustedURLError):
            _rows(_source("contacts", manager))
        # The poisoned link must not be persisted as resume state.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_hostile_resumed_next_url_is_rejected(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [])

        manager = _make_manager(ZendeskSellResumeConfig(next_url="https://evil.example.com/v2/contacts"))
        with pytest.raises(ZendeskSellUntrustedURLError):
            _rows(_source("contacts", manager))
        # A poisoned resume state must never reach the network with the bearer token.
        session.send.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bearer_token_registered_for_redaction(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(_envelope([{"id": 1}], next_page=None))])

        _rows(_source("contacts", _make_manager()))

        # The token flows through framework auth, which registers it for value-based log/error redaction.
        assert MockSession.call_args.kwargs["redact_values"] == ("token",)


class TestRetryClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(TENACITY_SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_retry_then_raise(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [])
        session.send.side_effect = lambda *a, **k: _response({}, status=status)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("contacts", _make_manager()))
        # Retried up to the client's attempt budget rather than failing on the first transient error.
        assert session.send.call_count > 1

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_http_error(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [])
        session.send.side_effect = [_response({}, status=status)]

        with pytest.raises(requests.HTTPError):
            _rows(_source("contacts", _make_manager()))


class TestValidatePaginationUrl:
    @parameterized.expand(
        [
            ("first_page", f"https://api.getbase.com/v2/contacts?per_page={PER_PAGE}"),
            ("next_page", PAGE_2_URL),
            ("other_endpoint", "https://api.getbase.com/v2/deals?page=3"),
        ]
    )
    def test_trusted_urls_pass_through(self, _name: str, url: str) -> None:
        assert _validate_pagination_url(url) == url

    @parameterized.expand(
        [
            ("foreign_host", "https://evil.example.com/v2/contacts"),
            ("subdomain_lookalike", "https://api.getbase.com.evil.example.com/v2/contacts"),
            ("http_scheme", "http://api.getbase.com/v2/contacts"),
            ("wrong_path_prefix", "https://api.getbase.com/internal/contacts"),
            ("missing_path", "https://api.getbase.com"),
            ("metadata_endpoint", "http://169.254.169.254/latest/meta-data/"),
        ]
    )
    def test_untrusted_urls_raise(self, _name: str, url: str) -> None:
        with pytest.raises(ZendeskSellUntrustedURLError):
            _validate_pagination_url(url)


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(ZENDESK_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, expected: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("token") is expected

    @mock.patch(ZENDESK_SESSION_PATCH)
    def test_network_error_is_false(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("token") is False

    @mock.patch(ZENDESK_SESSION_PATCH)
    def test_probe_session_redacts_token_and_disables_redirects(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("secret-token")
        assert mock_session.call_args.kwargs["redact_values"] == ("secret-token",)
        assert mock_session.call_args.kwargs["allow_redirects"] is False


class TestZendeskSellSource:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_partitioned_endpoint_response(self, MockSession) -> None:
        response = _source("contacts", _make_manager())
        assert response.name == "contacts"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unpartitioned_lookup_endpoint_response(self, MockSession) -> None:
        response = _source("stages", _make_manager())
        assert response.name == "stages"
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None
