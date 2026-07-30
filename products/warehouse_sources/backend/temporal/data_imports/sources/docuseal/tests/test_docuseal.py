import json
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.docuseal.docuseal import (
    DEFAULT_REGION,
    DOCUSEAL_HOSTS,
    PAGE_SIZE,
    DocusealResumeConfig,
    _base_url,
    docuseal_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the docuseal module.
DOCUSEAL_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.docuseal.docuseal.make_tracked_session"
)


def _response(rows: list[dict[str, Any]], next_cursor: int | None) -> Response:
    body = {"data": rows, "pagination": {"count": len(rows), "next": next_cursor, "prev": None}}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _rows(start_id: int, count: int) -> list[dict[str, Any]]:
    """`count` rows in DocuSeal's newest-first (descending id) order, starting at `start_id`."""
    return [{"id": start_id - offset, "created_at": "2026-01-01T00:00:00Z"} for offset in range(count)]


def _make_manager(resume_state: DocusealResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _drive(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestBaseUrl:
    @parameterized.expand(
        [
            ("us", DOCUSEAL_HOSTS["us"]),
            ("eu", DOCUSEAL_HOSTS["eu"]),
            (None, DOCUSEAL_HOSTS[DEFAULT_REGION]),
            ("", DOCUSEAL_HOSTS[DEFAULT_REGION]),
            ("unknown", DOCUSEAL_HOSTS[DEFAULT_REGION]),
        ]
    )
    def test_picks_correct_base_url(self, region: str | None, expected: str) -> None:
        assert _base_url(region) == expected


class TestValidateCredentials:
    @mock.patch(DOCUSEAL_SESSION_PATCH)
    def test_returns_true_on_200(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        success, error = validate_credentials("key", "us")

        assert success is True
        assert error is None
        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == f"{DOCUSEAL_HOSTS['us']}/templates?limit=1"

    @mock.patch(DOCUSEAL_SESSION_PATCH)
    def test_probes_selected_region_host(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("key", "eu")

        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url.startswith(DOCUSEAL_HOSTS["eu"])

    @parameterized.expand(
        [
            (401, "invalid"),
            (500, "unexpected status"),
        ]
    )
    @mock.patch(DOCUSEAL_SESSION_PATCH)
    def test_returns_false_on_http_status(
        self, status_code: int, expected_substring: str, mock_session: mock.MagicMock
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        success, error = validate_credentials("key", "us")

        assert success is False
        assert error is not None
        assert expected_substring.lower() in error.lower()

    @mock.patch(DOCUSEAL_SESSION_PATCH)
    def test_returns_false_on_network_error(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")

        success, error = validate_credentials("key", "us")

        assert success is False
        assert error is not None
        assert "could not reach docuseal" in error.lower()


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_short_page_terminates_without_extra_request(self, MockSession) -> None:
        session = MockSession.return_value
        # A short page carries a non-null `next` (DocuSeal's final page always does) yet is the end.
        params = _wire(session, [_response(_rows(3, 3), next_cursor=1)])

        rows = _drive(
            docuseal_source("tok", "us", "templates", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )

        assert [r["id"] for r in rows] == [3, 2, 1]
        assert session.send.call_count == 1
        assert "after" not in params[0]
        assert params[0]["limit"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_pages_using_after_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response(_rows(300, PAGE_SIZE), next_cursor=201),
                _response(_rows(200, PAGE_SIZE), next_cursor=101),
                _response(_rows(100, 50), next_cursor=51),
            ],
        )

        rows = _drive(
            docuseal_source("tok", "us", "templates", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )

        assert len(rows) == 250
        assert [p.get("after") for p in params] == [None, 201, 101]
        # Newest-first across the whole walk.
        assert rows[0]["id"] == 300
        assert rows[-1]["id"] == 51

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_next_cursor_is_null(self, MockSession) -> None:
        session = MockSession.return_value
        # A full-size page whose `next` is null must still terminate.
        _wire(session, [_response(_rows(100, PAGE_SIZE), next_cursor=None)])

        rows = _drive(
            docuseal_source("tok", "us", "templates", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )

        assert len(rows) == PAGE_SIZE
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], next_cursor=None)])

        rows = _drive(
            docuseal_source("tok", "us", "templates", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_uses_saved_after_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(_rows(499, 2), next_cursor=498)])

        manager = _make_manager(DocusealResumeConfig(after=500))
        rows = _drive(
            docuseal_source("tok", "us", "templates", team_id=1, job_id="j", resumable_source_manager=manager)
        )

        # First request must continue from the saved cursor, not start over.
        assert params[0]["after"] == 500
        assert [r["id"] for r in rows] == [499, 498]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_only_already_fetched_cursors_after_yield(self, MockSession) -> None:
        # Walk several full pages then a short one, and assert we never persist a cursor we haven't
        # fetched from yet (the "save current page, not next" invariant) — otherwise a crash would
        # skip rows still buffered.
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response(_rows(1000, PAGE_SIZE), next_cursor=901),
                _response(_rows(900, PAGE_SIZE), next_cursor=801),
                _response(_rows(800, PAGE_SIZE), next_cursor=701),
                _response(_rows(700, 50), next_cursor=651),
            ],
        )

        manager = _make_manager()
        rows = _drive(
            docuseal_source("tok", "us", "templates", team_id=1, job_id="j", resumable_source_manager=manager)
        )

        assert len(rows) == 3 * PAGE_SIZE + 50
        assert manager.save_state.called, "expected at least one checkpoint save across the walk"
        fetched_afters = {p.get("after") for p in params}
        saved_afters = [call.args[0].after for call in manager.save_state.call_args_list]
        assert all(after in fetched_afters for after in saved_afters)


class TestDocusealSourceResponse:
    @parameterized.expand(["templates", "submissions", "submitters"])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = docuseal_source(
            api_key="tok",
            region="us",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Rows arrive newest-first, so the pipeline must not assume ascending order.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
