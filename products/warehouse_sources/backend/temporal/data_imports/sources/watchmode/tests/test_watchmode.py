import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.watchmode.watchmode import (
    WatchmodeResumeConfig,
    watchmode_source,
)


def _make_json_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestWatchmodeSourceResumeBehavior:
    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[list[dict[str, Any]], list[Any]]:
        # Returns (sent_params, rows): shallow copies of request.params captured at
        # send-time (the Request object is mutated in place between pages) and the
        # flattened yielded rows.
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

            source_response = watchmode_source(
                api_key="test-key",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            rows: list[Any] = []
            for page in cast(Iterable[Any], source_response.items()):
                rows.extend(page if isinstance(page, list) else [page])
            return sent_params, rows

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = WatchmodeResumeConfig(page=5)

        responses = [
            _make_json_response({"titles": [{"id": 50}], "total_pages": 5}),
        ]
        sent_params, _ = self._drive("titles", manager, responses)

        assert [p.get("page") for p in sent_params] == [5]
        manager.load_state.assert_called_once()

    def test_endpoint_ignoring_page_param_terminates_without_duplicate_rows(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        body = {"releases": [{"id": 1, "source_id": 203}, {"id": 1, "source_id": 57}]}
        responses = [_make_json_response(body), _make_json_response(body)]
        sent_params, rows = self._drive("releases", manager, responses)

        assert len(sent_params) == 2
        assert rows == [{"id": 1, "source_id": 203}, {"id": 1, "source_id": 57}]

    def test_sync_requests_do_not_follow_redirects(self) -> None:
        # `requests` replays the `X-API-Key` header across a cross-host redirect, so a
        # dropped `allow_redirects=False` would forward the customer's key off-host.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        sent_redirects: list[Any] = []
        responses = iter([_make_json_response({"titles": [{"id": 1}], "total_pages": 1})])

        def fake_send(request: Any, *_args: Any, **kwargs: Any) -> Response:
            sent_redirects.append(kwargs.get("allow_redirects"))
            return next(responses)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source_response = watchmode_source(
                api_key="test-key",
                endpoint="titles",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            for _ in cast(Iterable[Any], source_response.items()):
                pass

        assert sent_redirects == [False]

    @pytest.mark.parametrize("endpoint", ["sources", "regions", "networks", "genres"])
    def test_reference_endpoints_fetch_a_single_unpaginated_page(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        row = {"id": 1, "country": "US", "name": "row"}
        responses = [_make_json_response([row])]
        sent_params, rows = self._drive(endpoint, manager, responses)

        assert len(sent_params) == 1
        assert "page" not in sent_params[0]
        assert rows == [row]
        manager.save_state.assert_not_called()
