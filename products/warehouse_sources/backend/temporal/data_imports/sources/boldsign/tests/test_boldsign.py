import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign import boldsign
from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.boldsign import (
    BOLDSIGN_HOSTS,
    PAGE_SIZE,
    BoldSignResumeConfig,
    _base_url,
    _get_headers,
    boldsign_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.settings import BOLDSIGN_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the boldsign module.
BOLDSIGN_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.boldsign.make_tracked_session"
)


def _response(items: list[dict[str, Any]] | None, *, data_key: str = "result", drop_key: bool = False) -> Response:
    body: dict[str, Any] = {}
    if not drop_key:
        body[data_key] = items or []
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: BoldSignResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's params AT SEND TIME.

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


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(
    endpoint: str,
    responses: list[Response],
    session: mock.MagicMock,
    manager: mock.MagicMock | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], mock.MagicMock]:
    params = _wire(session, responses)
    manager = manager if manager is not None else _make_manager()
    rows = _rows(
        boldsign_source(
            region="us",
            api_key="key",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=manager,
        )
    )
    return rows, params, manager


class TestBaseUrlAndHeaders:
    @pytest.mark.parametrize(
        "region, expected",
        [
            ("us", "https://api.boldsign.com"),
            ("eu", "https://api-eu.boldsign.com"),
        ],
    )
    def test_base_url_per_region(self, region: str, expected: str) -> None:
        assert _base_url(region) == expected
        assert BOLDSIGN_HOSTS[region] == expected

    def test_base_url_rejects_unknown_region(self) -> None:
        with pytest.raises(ValueError):
            _base_url("apac")

    def test_headers_use_api_key_header(self) -> None:
        headers = _get_headers("secret")
        assert headers["X-API-KEY"] == "secret"
        assert headers["Accept"] == "application/json"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_paginated_endpoint_makes_single_request(self, MockSession) -> None:
        session = MockSession.return_value
        rows, params, _ = _run("brands", [_response([{"brandId": "B1"}, {"brandId": "B2"}])], session)

        assert rows == [{"brandId": "B1"}, {"brandId": "B2"}]
        assert session.send.call_count == 1
        assert "Page" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_page_terminates_pagination(self, MockSession) -> None:
        # A page shorter than PAGE_SIZE is the last page.
        session = MockSession.return_value
        rows, params, _ = _run("documents", [_response([{"documentId": "D1"}])], session)

        assert rows == [{"documentId": "D1"}]
        assert session.send.call_count == 1
        assert params[0]["Page"] == 1
        assert params[0]["PageSize"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_advances_to_next_page(self, MockSession) -> None:
        session = MockSession.return_value
        full = [{"documentId": f"D{i}"} for i in range(PAGE_SIZE)]
        rows, params, _ = _run("documents", [_response(full), _response([{"documentId": "last"}])], session)

        assert len(rows) == PAGE_SIZE + 1
        assert [p["Page"] for p in params] == [1, 2]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        rows, _, _ = _run("documents", [_response([])], session)

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_is_treated_as_empty_page(self, MockSession) -> None:
        session = MockSession.return_value
        rows, _, _ = _run("documents", [_response(None, drop_key=True)], session)

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_teams_uses_results_data_key(self, MockSession) -> None:
        session = MockSession.return_value
        rows, _, _ = _run("teams", [_response([{"teamId": "T1"}], data_key="results")], session)

        assert rows == [{"teamId": "T1"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_templates_send_template_type_param(self, MockSession) -> None:
        session = MockSession.return_value
        _, params, _ = _run("templates", [_response([{"documentId": "T1"}])], session)

        assert params[0]["TemplateType"] == "all"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_key_supplied_via_framework_auth(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"documentId": "D1"}])])
        auths: list[Any] = []
        original_prepare = session.prepare_request.side_effect

        def _prepare(request: Any) -> mock.MagicMock:
            auths.append(request.auth)
            return original_prepare(request)

        session.prepare_request.side_effect = _prepare
        _rows(
            boldsign_source(
                region="us",
                api_key="secret",
                endpoint="documents",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
            )
        )

        # The key rides on the framework's api_key auth (redacted from logs), not a raw header.
        assert auths[0] is not None
        assert auths[0].name == "X-API-KEY"
        assert auths[0].api_key == "secret"


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_page_after_yielding_each_full_page(self, MockSession) -> None:
        session = MockSession.return_value
        full = [{"documentId": f"D{i}"} for i in range(PAGE_SIZE)]
        _, _, manager = _run("documents", [_response(full), _response([{"documentId": "tail"}])], session)

        # Only the page that had a full page of results (page 1) saves state, pointing at page 2.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == BoldSignResumeConfig(
            page=2, next_cursor=None, records_fetched=PAGE_SIZE
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        manager = _make_manager(BoldSignResumeConfig(page=5, next_cursor=None, records_fetched=400))
        _, params, _ = _run("documents", [_response([{"documentId": "D5"}])], session, manager)

        assert params[0]["Page"] == 5

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        manager = _make_manager(BoldSignResumeConfig(page=1, next_cursor=4242, records_fetched=10_000))
        _, params, _ = _run("documents", [_response([{"documentId": "after"}])], session, manager)

        assert params[0]["Page"] == 1
        assert params[0]["NextCursor"] == 4242


class TestCursorPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_documents_switch_to_cursor_past_record_threshold(self, MockSession) -> None:
        # Fill exactly the 10k page-cap with full pages, then expect a NextCursor request.
        session = MockSession.return_value
        threshold_pages = boldsign.RECORD_CURSOR_THRESHOLD // PAGE_SIZE
        full_pages = [
            _response([{"documentId": f"D{p}-{i}", "cursor": p * PAGE_SIZE + i} for i in range(PAGE_SIZE)])
            for p in range(threshold_pages)
        ]
        # One more page reached via cursor, then a short page to stop.
        cursor_page = _response([{"documentId": "after-cursor", "cursor": 999999}])

        _, params, manager = _run("documents", [*full_pages, cursor_page], session)

        # The cursor passed is the last record's cursor from the final full page, with Page reset.
        expected_cursor = boldsign.RECORD_CURSOR_THRESHOLD - 1
        assert params[-1]["NextCursor"] == expected_cursor
        assert params[-1]["Page"] == 1
        # The checkpoint written after the final full page carries the cursor position.
        assert manager.save_state.call_args.args[0] == BoldSignResumeConfig(
            page=1, next_cursor=expected_cursor, records_fetched=boldsign.RECORD_CURSOR_THRESHOLD
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_cursor_endpoint_stops_at_record_threshold(self, MockSession) -> None:
        # users/list has no cursor support, so it must stop at the 10k page cap rather than loop.
        session = MockSession.return_value
        threshold_pages = boldsign.RECORD_CURSOR_THRESHOLD // PAGE_SIZE
        full_pages = [_response([{"userId": f"U{p}-{i}"} for i in range(PAGE_SIZE)]) for p in range(threshold_pages)]
        # Provide an extra page that should never be requested.
        responses = [*full_pages, _response([{"userId": "should-not-fetch"}])]

        rows, _, _ = _run("users", responses, session)

        assert session.send.call_count == threshold_pages
        assert len(rows) == boldsign.RECORD_CURSOR_THRESHOLD


class TestSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, expected_pk",
        [
            ("documents", ["documentId"]),
            ("templates", ["documentId"]),
            ("users", ["userId"]),
            ("teams", ["teamId"]),
            ("contacts", ["id"]),
            ("sender_identities", ["id"]),
            ("brands", ["brandId"]),
        ],
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_pk: list[str]) -> None:
        response = boldsign_source(
            region="us",
            api_key="key",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        # Full refresh: BoldSign timestamps are epoch ints, so no datetime partitioning.
        assert response.partition_mode is None
        assert response.primary_keys == BOLDSIGN_ENDPOINTS[endpoint].primary_keys


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid BoldSign API key"),
            (403, False, "Invalid BoldSign API key"),
            (500, False, "Unexpected response from BoldSign (status 500)"),
        ],
    )
    @mock.patch(BOLDSIGN_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected_valid, expected_message) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        is_valid, message = validate_credentials("us", "key")

        assert is_valid is expected_valid
        assert message == expected_message

    @mock.patch(BOLDSIGN_SESSION_PATCH)
    def test_network_error_is_not_reported_as_bad_key(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")

        is_valid, message = validate_credentials("us", "key")

        assert is_valid is False
        assert message == "Could not reach BoldSign"

    @mock.patch(BOLDSIGN_SESSION_PATCH)
    def test_probes_the_region_host_with_the_api_key_header(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("eu", "secret")

        url = mock_session.return_value.get.call_args.args[0]
        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert url.startswith("https://api-eu.boldsign.com/v1/document/list")
        assert headers["X-API-KEY"] == "secret"
