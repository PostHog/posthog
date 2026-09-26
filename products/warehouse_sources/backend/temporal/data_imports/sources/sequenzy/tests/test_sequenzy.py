import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.sequenzy.sequenzy import (
    SequenzyResumeConfig,
    _paginator_state,
    sequenzy_source,
    validate_credentials,
)

_SESSION_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client"
    ".make_tracked_session"
)


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _drive(
    endpoint: str,
    manager: MagicMock,
    responses: list[Response],
    company_id: str | None = None,
) -> tuple[MagicMock, list[dict[str, Any]], list[Any]]:
    """Drive ``sequenzy_source`` with a mocked HTTP session.

    Returns ``(mock_session, sent_params, rows)``. ``sent_params`` holds shallow copies
    of ``request.params`` captured at send-time, because the paginator mutates the
    Request object in place between pages.
    """
    sent_params: list[dict[str, Any]] = []
    response_iter = iter(responses)

    def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
        sent_params.append(dict(request.params or {}))
        return next(response_iter)

    with patch(_SESSION_PATH) as MockSession:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.side_effect = lambda req: req
        mock_session.send.side_effect = fake_send

        source_response = sequenzy_source(
            api_key="test-key",
            endpoint=endpoint,
            team_id=123,
            job_id="test_job",
            resumable_source_manager=manager,
            company_id=company_id,
        )
        # The resource yields one list of rows per page; flatten so assertions read per-row.
        pages = list(cast(Iterable[Any], source_response.items()))
        rows = [row for page in pages for row in (page if isinstance(page, list) else [page])]
        return mock_session, sent_params, rows


def _manager(resume: SequenzyResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


class TestSequenzyPagination:
    def test_subscribers_follow_next_cursor_until_null(self) -> None:
        manager = _manager()
        responses = [
            _make_http_response(
                {
                    "success": True,
                    "subscribers": [{"id": "sub_1", "email": "a@example.com"}],
                    "pagination": {"nextCursor": "cur_1", "hasMore": True},
                }
            ),
            _make_http_response(
                {
                    "success": True,
                    "subscribers": [{"id": "sub_2", "email": "b@example.com"}],
                    "pagination": {"nextCursor": "cur_2", "hasMore": True},
                }
            ),
            _make_http_response(
                {
                    "success": True,
                    "subscribers": [{"id": "sub_3", "email": "c@example.com"}],
                    "pagination": {"nextCursor": None, "hasMore": False},
                }
            ),
        ]
        _, sent_params, rows = _drive("subscribers", manager, responses)

        assert [p.get("cursor") for p in sent_params] == [None, "cur_1", "cur_2"]
        assert [row["id"] for row in rows] == ["sub_1", "sub_2", "sub_3"]
        # The intermediate cursors are staged so a crash resumes mid-collection.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            SequenzyResumeConfig(cursor="cur_1"),
            SequenzyResumeConfig(cursor="cur_2"),
        ]

    def test_subscribers_request_shape(self) -> None:
        manager = _manager()
        responses = [
            _make_http_response(
                {
                    "success": True,
                    "subscribers": [{"id": "sub_1"}],
                    "pagination": {"nextCursor": None, "hasMore": False},
                }
            ),
        ]
        _, sent_params, _ = _drive("subscribers", manager, responses)

        # `status=all` must go out or unsubscribed/bounced contacts silently never sync;
        # `includeTotal=false` skips the API's count query; page size rides as `limit`.
        assert sent_params[0]["status"] == "all"
        assert sent_params[0]["includeTotal"] == "false"
        assert sent_params[0]["limit"] == 1000

    def test_campaigns_offset_pagination_stops_at_total(self) -> None:
        manager = _manager()
        responses = [
            _make_http_response(
                {
                    "success": True,
                    "campaigns": [{"id": f"camp_{i}"} for i in range(100)],
                    "pagination": {"limit": 100, "offset": 0, "count": 100, "total": 150, "hasMore": True},
                }
            ),
            _make_http_response(
                {
                    "success": True,
                    "campaigns": [{"id": f"camp_{i}"} for i in range(100, 150)],
                    "pagination": {"limit": 100, "offset": 100, "count": 50, "total": 150, "hasMore": False},
                }
            ),
        ]
        _, sent_params, rows = _drive("campaigns", manager, responses)

        assert [(p.get("offset"), p.get("limit")) for p in sent_params] == [(0, 100), (100, 100)]
        assert len(rows) == 150

    def test_email_metrics_page_pagination_stops_at_total_pages(self) -> None:
        manager = _manager()
        responses = [
            _make_http_response(
                {
                    "success": True,
                    "emails": [{"emailType": "campaign", "emailId": "camp_1"}],
                    "pagination": {"page": 1, "limit": 500, "total": 2, "totalPages": 2},
                }
            ),
            _make_http_response(
                {
                    "success": True,
                    "emails": [{"emailType": "sequence", "emailId": "node_1"}],
                    "pagination": {"page": 2, "limit": 500, "total": 2, "totalPages": 2},
                }
            ),
        ]
        _, sent_params, rows = _drive("email_metrics", manager, responses)

        assert [p.get("page") for p in sent_params] == [1, 2]
        # A stable sort keeps rows from shuffling between pages while counts move mid-sync.
        assert sent_params[0]["sort"] == "name"
        assert sent_params[0]["order"] == "asc"
        assert len(rows) == 2

    @pytest.mark.parametrize("endpoint", ["tags", "lists", "segments"])
    def test_single_page_endpoints_make_one_request(self, endpoint: str) -> None:
        manager = _manager()
        responses = [
            _make_http_response({"success": True, endpoint: [{"id": f"{endpoint}_1", "name": "x"}]}),
        ]
        _, sent_params, rows = _drive(endpoint, manager, responses)

        assert len(sent_params) == 1
        assert [row["id"] for row in rows] == [f"{endpoint}_1"]
        manager.save_state.assert_not_called()


class TestSequenzyResume:
    @pytest.mark.parametrize(
        ("endpoint", "resume", "param", "expected"),
        [
            ("subscribers", SequenzyResumeConfig(cursor="cur_saved"), "cursor", "cur_saved"),
            ("campaigns", SequenzyResumeConfig(offset=100), "offset", 100),
            ("email_metrics", SequenzyResumeConfig(page=2), "page", 2),
        ],
    )
    def test_resume_seeds_first_request(
        self, endpoint: str, resume: SequenzyResumeConfig, param: str, expected: Any
    ) -> None:
        manager = _manager(resume)
        selector = {"subscribers": "subscribers", "campaigns": "campaigns", "email_metrics": "emails"}[endpoint]
        responses = [
            _make_http_response({"success": True, selector: [], "pagination": {"nextCursor": None}}),
        ]
        _, sent_params, _ = _drive(endpoint, manager, responses)

        assert sent_params[0][param] == expected
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = _manager()
        responses = [
            _make_http_response(
                {
                    "success": True,
                    "subscribers": [{"id": "only"}],
                    "pagination": {"nextCursor": None, "hasMore": False},
                }
            ),
        ]
        _drive("subscribers", manager, responses)

        manager.save_state.assert_not_called()
        manager.load_state.assert_not_called()

    def test_paginator_state_drops_unset_fields(self) -> None:
        assert _paginator_state(SequenzyResumeConfig(cursor="c")) == {"cursor": "c"}
        assert _paginator_state(SequenzyResumeConfig(offset=200)) == {"offset": 200}
        assert _paginator_state(SequenzyResumeConfig()) is None


class TestSequenzyCompanyHeader:
    def test_company_id_sets_workspace_header(self) -> None:
        manager = _manager()
        responses = [
            _make_http_response({"success": True, "tags": []}),
        ]
        mock_session, _, _ = _drive("tags", manager, responses, company_id="company_abc123")

        assert mock_session.headers.get("x-company-id") == "company_abc123"

    def test_no_company_id_sends_no_workspace_header(self) -> None:
        manager = _manager()
        responses = [
            _make_http_response({"success": True, "tags": []}),
        ]
        mock_session, _, _ = _drive("tags", manager, responses)

        assert "x-company-id" not in mock_session.headers


class TestValidateCredentials:
    _SESSION = "products.warehouse_sources.backend.temporal.data_imports.sources.sequenzy.sequenzy.make_tracked_session"

    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_fragment"),
        [
            (200, True, None),
            (401, False, "Invalid API key"),
            (403, False, "company ID"),
            (500, False, "HTTP 500"),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool, expected_fragment: str | None) -> None:
        with patch(self._SESSION) as MockSession:
            MockSession.return_value.get.return_value = _make_http_response({}, status_code=status_code)
            valid, message = validate_credentials("seq_live_key")

        assert valid is expected_valid
        if expected_fragment is None:
            assert message is None
        else:
            assert expected_fragment in (message or "")

    def test_company_id_forwarded_as_header(self) -> None:
        with patch(self._SESSION) as MockSession:
            MockSession.return_value.get.return_value = _make_http_response({}, status_code=200)
            validate_credentials("seq_user_key", company_id="company_abc123")

        headers = MockSession.return_value.get.call_args.kwargs["headers"]
        assert headers["x-company-id"] == "company_abc123"

    def test_non_ascii_key_returns_actionable_message_without_a_request(self) -> None:
        # A non-latin-1 key can't be encoded into the Authorization header; the raw
        # UnicodeEncodeError must never surface to the user.
        with patch(self._SESSION) as MockSession:
            valid, message = validate_credentials("bad中key")

        assert valid is False
        assert "Retype it by hand" in (message or "")
        assert "latin-1" not in (message or "")
        MockSession.assert_not_called()
