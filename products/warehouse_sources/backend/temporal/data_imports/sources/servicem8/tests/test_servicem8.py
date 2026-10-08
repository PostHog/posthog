import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.servicem8.servicem8 import (
    ServiceM8Paginator,
    ServiceM8ResumeConfig,
    _format_filter_datetime,
    servicem8_source,
    validate_credentials,
)


class TestFormatFilterDatetime:
    def test_formats_a_date(self) -> None:
        assert _format_filter_datetime(date(2024, 1, 2)) == "2024-01-02 00:00:00"

    def test_passes_through_a_string(self) -> None:
        assert _format_filter_datetime("2024-01-02 03:04:05") == "2024-01-02 03:04:05"


class TestServiceM8Paginator:
    def test_initial_state_initializes_params_when_missing(self) -> None:
        # ServiceM8Paginator must not assume the caller pre-populates `request.params`.
        paginator = ServiceM8Paginator()
        request = Request(method="GET", url="https://api.servicem8.com/api_1.0/job.json")
        request.params = None
        paginator.init_request(request)

        assert request.params == {"cursor": "-1"}

    def test_update_request_initializes_params_when_missing(self) -> None:
        paginator = ServiceM8Paginator()
        paginator._cursor = "cursor-42"
        request = Request(method="GET", url="https://api.servicem8.com/api_1.0/job.json")
        request.params = None
        paginator.update_request(request)

        assert request.params["cursor"] == "cursor-42"

    def test_get_resume_state_returns_none_on_terminal_page(self) -> None:
        paginator = ServiceM8Paginator()
        response = MagicMock()
        response.headers = {}
        paginator.update_state(response)

        assert paginator.get_resume_state() is None


def _make_http_response(body: list[dict[str, Any]], headers: dict[str, str] | None = None) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    for key, value in (headers or {}).items():
        resp.headers[key] = value
    return resp


class TestServiceM8SourceResumeBehavior:
    """End-to-end resume behaviour of ``servicem8_source`` via ``rest_api_resource``."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[MagicMock, list[dict[str, Any]]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            resource = servicem8_source(
                api_key="test-key",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=None,
                should_use_incremental_field=False,
            )
            list(cast(Iterable[Any], resource))
            return mock_session, sent_params

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ServiceM8ResumeConfig(cursor="cursor-resumed")

        responses = [_make_http_response([{"uuid": "d"}])]
        _, sent_params = self._drive("Job", manager, responses)

        assert [p.get("cursor") for p in sent_params] == ["cursor-resumed"]
        manager.load_state.assert_called_once()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{"uuid": "a"}])]
        self._drive("Job", manager, responses)

        manager.load_state.assert_not_called()

    def test_incremental_run_carries_the_filter_on_every_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        sent_params: list[dict[str, Any]] = []
        responses = [
            _make_http_response([{"uuid": "a"}], {"x-next-cursor": "cursor-1"}),
            _make_http_response([{"uuid": "b"}]),
        ]
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            resource = servicem8_source(
                api_key="test-key",
                endpoint="Job",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
                should_use_incremental_field=True,
            )
            list(cast(Iterable[Any], resource))

        assert all(p.get("$filter") == "edit_date gt '2024-01-01 00:00:00'" for p in sent_params)


class TestValidateCredentials:
    @pytest.mark.parametrize(("status_code", "expected"), [(200, True), (401, False), (403, False)])
    def test_validate_credentials(self, status_code: int, expected: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.servicem8.servicem8.make_tracked_session"
        ) as mock_make_session:
            mock_session = mock_make_session.return_value
            mock_session.get.return_value = MagicMock(status_code=status_code)

            assert validate_credentials("test-key") is expected
