import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.sequenzy.sequenzy import (
    SequenzyResumeConfig,
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


class TestSequenzyCompanyHeader:
    def test_company_id_sets_workspace_header(self) -> None:
        manager = _manager()
        responses = [
            _make_http_response({"success": True, "tags": []}),
        ]
        mock_session, _, _ = _drive("tags", manager, responses, company_id="company_abc123")

        assert mock_session.headers.get("x-company-id") == "company_abc123"


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
