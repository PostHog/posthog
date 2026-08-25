import json
from collections.abc import Iterable
from typing import Any, Optional, cast

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.secoda.secoda import (
    SECODA_BASE_URL,
    SecodaResumeConfig,
    secoda_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.secoda.settings import ENDPOINTS, SECODA_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the secoda module.
SECODA_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.secoda.secoda.make_tracked_session"
)
# The client retries transient failures via tenacity; patch its sleep so retry tests don't wait.
SLEEP_PATCH = "tenacity.nap.time.sleep"

TABLES_URL = f"{SECODA_BASE_URL}/api/v1/table/tables"


def _json_response(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _page(results: list[dict], *, links_next: Optional[str] = None, top_level_next: Optional[str] = None) -> Response:
    # DRF cursor endpoints nest the follow link under links.next; a few endpoints instead expose it
    # top-level under next (with no links envelope). Build one shape or the other, never both.
    if top_level_next is not None:
        return _json_response({"results": results, "next": top_level_next})
    return _json_response({"results": results, "links": {"next": links_next, "previous": None}})


def _make_manager(resume_state: SecodaResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[str]:
    """Wire a mock session and return a list capturing each request's URL AT SEND TIME.

    ``prepare_request`` receives the fully-built ``Request``; snapshot its URL so we can assert the
    cursor progression (the next-page URL is self-contained and replaces the base path each page).
    """
    session.headers = {}
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        url_snapshots.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots


def _run(manager: mock.MagicMock, endpoint: str = "tables") -> list[dict[str, Any]]:
    source_response = secoda_source("sk-key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)
    return [row for page in cast("Iterable[Any]", source_response.items()) for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_yields_and_stops(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"id": "a"}, {"id": "b"}], links_next=None)])

        manager = _make_manager()
        rows = _run(manager)

        assert rows == [{"id": "a"}, {"id": "b"}]
        assert session.send.call_count == 1
        # A null next link ends the sync without persisting resume state.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_links_next_cursor_until_null(self, MockSession) -> None:
        session = MockSession.return_value
        second = f"{TABLES_URL}?page=2"
        urls = _wire(session, [_page([{"id": "a"}], links_next=second), _page([{"id": "b"}], links_next=None)])

        manager = _make_manager()
        rows = _run(manager)

        assert rows == [{"id": "a"}, {"id": "b"}]
        # First request hits the base path; the second follows the self-contained cursor URL verbatim.
        assert urls[0] == TABLES_URL
        assert urls[1] == second
        # State is saved once — after the first page, pointing at the next cursor — then we stop.
        manager.save_state.assert_called_once_with(SecodaResumeConfig(next_url=second))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_top_level_next_is_followed(self, MockSession) -> None:
        session = MockSession.return_value
        second = f"{SECODA_BASE_URL}/api/v1/tag?page=2"
        # Endpoints that expose the follow link top-level (no links.next) must still paginate.
        urls = _wire(
            session,
            [_page([{"id": "a"}], links_next=None, top_level_next=second), _page([{"id": "b"}], links_next=None)],
        )

        manager = _make_manager()
        rows = _run(manager, endpoint="tags")

        assert rows == [{"id": "a"}, {"id": "b"}]
        assert urls[1] == second
        manager.save_state.assert_called_once_with(SecodaResumeConfig(next_url=second))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        second = f"{TABLES_URL}?page=2"
        urls = _wire(session, [_page([{"id": "b"}], links_next=None)])

        manager = _make_manager(SecodaResumeConfig(next_url=second))
        rows = _run(manager)

        assert rows == [{"id": "b"}]
        # The first page URL must never be fetched on resume — we start at the saved cursor.
        assert session.send.call_count == 1
        assert urls[0] == second

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([], links_next=None)])

        manager = _make_manager()
        rows = _run(manager)

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestTransientResponsesRetried:
    @parameterized.expand(
        [
            ("bare_list_body", [{"id": "x"}]),
            ("missing_results_key", {"count": 1}),
            ("results_not_a_list", {"results": {"nope": 1}}),
        ]
    )
    @mock.patch(SLEEP_PATCH, return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_200_body_is_reissued(self, _name: str, bad_body: Any, MockSession, _sleep) -> None:
        session = MockSession.return_value
        # A 200 whose body isn't the expected {"results": [...]} shape is transient — the framework
        # reissues it; a well-formed follow-up succeeds.
        _wire(session, [_json_response(bad_body), _page([{"id": "a"}], links_next=None)])

        rows = _run(_make_manager())

        assert rows == [{"id": "a"}]
        assert session.send.call_count == 2

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(SLEEP_PATCH, return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_reissued(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        # 429/5xx are retried by the client itself; the retried request then succeeds.
        _wire(session, [_json_response({}, status=status), _page([{"id": "a"}], links_next=None)])

        rows = _run(_make_manager())

        assert rows == [{"id": "a"}]
        assert session.send.call_count == 2


class TestValidateCredentials:
    @mock.patch(SECODA_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("sk-key") == (True, None)

    @parameterized.expand(
        [
            ("unauthorized", 401, "Invalid Secoda API key"),
            ("forbidden", 403, "Invalid Secoda API key"),
            ("server_error", 500, "Secoda returned HTTP 500"),
        ]
    )
    @mock.patch(SECODA_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, expected_message: str, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("sk-key") == (False, expected_message)

    @mock.patch(SECODA_SESSION_PATCH)
    def test_connection_error_maps_to_generic_message(self, mock_session) -> None:
        # validate_via_probe swallows transport errors and reports status None.
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("sk-key") == (False, "Could not validate Secoda API key")


class TestSecodaSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        # Construction does no I/O (items is a lazy generator), so no session patch is needed.
        response = secoda_source("sk-key", endpoint, team_id=1, job_id="j", resumable_source_manager=mock.MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SECODA_ENDPOINTS.values())
        assert set(SECODA_ENDPOINTS) == set(ENDPOINTS)
