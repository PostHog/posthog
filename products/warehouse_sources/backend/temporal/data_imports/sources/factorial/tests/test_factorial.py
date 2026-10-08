import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.factorial.factorial import (
    API_VERSION_2026_04_01,
    PAGE_SIZE,
    FactorialCursorPaginator,
    FactorialResumeConfig,
    factorial_source,
    validate_credentials,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.factorial.factorial"
_SESSION_FACTORY = f"{_MODULE}.make_tracked_session"


def _full_page() -> list[dict[str, Any]]:
    return [{"id": i} for i in range(PAGE_SIZE)]


def _meta_response(meta: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"meta": meta, "data": []}
    return response


class TestFactorialCursorPaginator:
    def test_get_resume_state_none_on_terminal_page(self) -> None:
        paginator = FactorialCursorPaginator()
        paginator.update_state(_meta_response({"has_next_page": False}), [])
        assert paginator.get_resume_state() is None


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
    api_version: str = API_VERSION_2026_04_01,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Run ``factorial_source`` to exhaustion against canned pages, capturing every request."""
    sent_params: list[dict[str, Any]] = []
    sent_urls: list[str] = []
    response_iter = iter(responses)

    def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
        sent_params.append(dict(request.params or {}))
        sent_urls.append(request.url)
        return next(response_iter)

    with patch(_SESSION_FACTORY) as MockSession:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.side_effect = lambda req: req
        mock_session.send.side_effect = fake_send

        source = factorial_source(
            api_key="test-key",
            endpoint=endpoint,
            team_id=123,
            job_id="test_job",
            resumable_source_manager=manager,
            api_version=api_version,
        )
        list(cast(Iterable[Any], source.items()))
        return sent_params, sent_urls


def _page_body(items: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    return {"data": items, "meta": meta}


class TestFactorialSourceResumeBehavior:
    """End-to-end resume behaviour of ``factorial_source`` via ``rest_api_resource``."""

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_page_body([{"id": 1}], {"has_next_page": False, "end_cursor": None})),
        ]
        _drive("employees", manager, responses)

        manager.load_state.assert_not_called()


class TestEndpointParams:
    """Static endpoint params must survive both the paginator and the page walk."""

    def test_allowance_stats_pins_one_reference_date_across_pages(self) -> None:
        # Factorial recomputes allowance_stats against the date it receives, defaulting to today,
        # so a walk that crosses midnight would otherwise mix two as-of dates into one table.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_page_body(_full_page(), {"has_next_page": True, "end_cursor": "Mjc="})),
            _make_http_response(_page_body([{"id": "1/2/x"}], {"has_next_page": False, "end_cursor": None})),
        ]
        with patch(f"{_MODULE}.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 5, 4, 23, 59, tzinfo=UTC)
            sent_params, _ = _drive("allowance_stats", manager, responses)

        assert [p["reference_date"] for p in sent_params] == ["2026-05-04", "2026-05-04"]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [FactorialResumeConfig(after_id="Mjc=", reference_date="2026-05-04")]

    def test_allowance_stats_resume_reuses_the_saved_reference_date(self) -> None:
        # A resumed walk must keep the earlier pages' as-of date, not the day it resumes on.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = FactorialResumeConfig(after_id="MTY=", reference_date="2026-05-04")

        responses = [
            _make_http_response(_page_body([{"id": "1/2/x"}], {"has_next_page": False, "end_cursor": None})),
        ]
        with patch(f"{_MODULE}.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 5, 5, 0, 1, tzinfo=UTC)
            sent_params, _ = _drive("allowance_stats", manager, responses)

        assert sent_params[0]["reference_date"] == "2026-05-04"
        assert sent_params[0]["after_id"] == "MTY="


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        with patch(_SESSION_FACTORY) as MockSession:
            mock_session = MockSession.return_value
            response = MagicMock()
            response.status_code = status_code
            mock_session.get.return_value = response

            valid, error = validate_credentials("test-key", API_VERSION_2026_04_01)
            assert valid is expected_valid
            if expected_valid:
                assert error is None
            else:
                assert error is not None

    def test_network_error_returns_message(self) -> None:
        with patch(_SESSION_FACTORY) as MockSession:
            MockSession.return_value.get.side_effect = Exception("boom")
            valid, error = validate_credentials("test-key", API_VERSION_2026_04_01)
            assert valid is False
            assert error == "boom"
