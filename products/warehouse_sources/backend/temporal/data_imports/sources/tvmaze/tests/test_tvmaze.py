import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.tvmaze.tvmaze import (
    UPDATES_CHUNK_SIZE,
    TVMazeResumeConfig,
    check_connection,
    tvmaze_source,
)

REST_CLIENT_SESSION_FACTORY = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client"
    ".make_tracked_session"
)
TVMAZE_SESSION_FACTORY = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.tvmaze.tvmaze.make_tracked_session"
)


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _drive_index(
    endpoint: str, manager: MagicMock, responses: list[Response]
) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
    sent_params: list[dict[str, Any]] = []
    response_iter = iter(responses)

    def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
        sent_params.append(dict(request.params or {}))
        return next(response_iter)

    with patch(REST_CLIENT_SESSION_FACTORY) as MockSession:
        mock_session = MockSession.return_value
        mock_session.prepare_request.side_effect = lambda req: req
        mock_session.send.side_effect = fake_send

        source = tvmaze_source(
            endpoint=endpoint,
            team_id=123,
            job_id="test_job",
            resumable_source_manager=manager,
        )
        pages = list(cast(Iterable[list[dict[str, Any]]], source.items()))
        return sent_params, pages


class TestIndexPagination:
    """End-to-end pagination + resume behaviour of the show/person indexes."""

    @pytest.mark.parametrize("endpoint", ["shows", "people"])
    def test_walks_pages_until_404_and_skips_empty_pages(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response([{"id": 1}, {"id": 2}]),
            # Deleted records can leave a sparse (empty) page mid-index; it must
            # not terminate the walk — only the documented 404 does.
            _make_http_response([]),
            _make_http_response([{"id": 700}]),
            _make_http_response([], status_code=404),
        ]
        sent_params, pages = _drive_index(endpoint, manager, responses)

        assert [p.get("page") for p in sent_params] == [0, 1, 2, 3]
        assert [row["id"] for page in pages for row in page] == [1, 2, 700]

    def test_saves_next_page_after_each_yielded_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response([{"id": 1}]),
            _make_http_response([{"id": 300}]),
            _make_http_response([], status_code=404),
        ]
        _drive_index("shows", manager, responses)

        # One checkpoint per yielded data page; the terminating 404 page is
        # never checkpointed (there is nothing left to resume to).
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [TVMazeResumeConfig(page=1), TVMazeResumeConfig(page=2)]

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = TVMazeResumeConfig(page=7)

        responses = [
            _make_http_response([{"id": 1750}]),
            _make_http_response([], status_code=404),
        ]
        sent_params, _ = _drive_index("shows", manager, responses)

        assert [p.get("page") for p in sent_params] == [7, 8]
        manager.load_state.assert_called_once()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([], status_code=404)]
        _drive_index("shows", manager, responses)

        manager.load_state.assert_not_called()


class TestUpdatesEndpoints:
    @pytest.mark.parametrize(
        ("endpoint", "expected_path"),
        [
            ("show_updates", "/updates/shows"),
            ("person_updates", "/updates/people"),
        ],
    )
    def test_flattens_id_to_timestamp_map_into_rows(self, endpoint: str, expected_path: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)

        with patch(TVMAZE_SESSION_FACTORY) as MockSession:
            mock_session = MockSession.return_value
            mock_session.get.return_value = _make_http_response({"1": 1631010933, "42": 1631010934})

            source = tvmaze_source(
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            pages = list(cast(Iterable[list[dict[str, Any]]], source.items()))

        requested_url = mock_session.get.call_args.args[0]
        assert requested_url.endswith(expected_path)
        # Ids arrive as JSON object keys (strings) and must land as integers so
        # they can join against the shows/people tables.
        assert pages == [[{"id": 1, "updated": 1631010933}, {"id": 42, "updated": 1631010934}]]

    def test_large_map_is_yielded_in_chunks(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        payload = {str(i): i for i in range(UPDATES_CHUNK_SIZE + 1)}

        with patch(TVMAZE_SESSION_FACTORY) as MockSession:
            MockSession.return_value.get.return_value = _make_http_response(payload)

            source = tvmaze_source(
                endpoint="show_updates",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            pages = list(cast(Iterable[list[dict[str, Any]]], source.items()))

        assert [len(page) for page in pages] == [UPDATES_CHUNK_SIZE, 1]


class TestCheckConnection:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (403, False),
            (503, False),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        with patch(TVMAZE_SESSION_FACTORY) as MockSession:
            response = MagicMock()
            response.status_code = status_code
            MockSession.return_value.get.return_value = response

            valid, error = check_connection()

        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    def test_network_error_returns_message(self) -> None:
        with patch(TVMAZE_SESSION_FACTORY) as MockSession:
            MockSession.return_value.get.side_effect = Exception("boom")
            valid, error = check_connection()

        assert valid is False
        assert error == "boom"
