import json
from collections.abc import Iterable
from typing import Any, cast

from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.recreation.recreation import (
    RecreationResumeConfig,
    recreation_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recreation.settings import PAGE_LIMIT


def _ridb_response(records: list[dict[str, Any]], total_count: int, offset: int) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(
        {
            "RECDATA": records,
            "METADATA": {
                "RESULTS": {"CURRENT_COUNT": len(records), "TOTAL_COUNT": total_count},
                "SEARCH_PARAMETERS": {"QUERY": "", "LIMIT": PAGE_LIMIT, "OFFSET": offset},
            },
        }
    ).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _facility_rows(start: int, count: int) -> list[dict[str, Any]]:
    return [{"FacilityID": str(i), "FacilityName": f"Facility {i}"} for i in range(start, start + count)]


class TestRecreationSourceTransport:
    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Drive ``recreation_source`` with a mocked HTTP session.

        Returns ``(rows, sent_params)``. ``sent_params`` holds shallow copies of
        ``request.params`` captured at send-time because the paginator mutates the
        Request object in place between pages.
        """
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

            source_response = recreation_source(
                api_key="test-key",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            rows: list[dict[str, Any]] = []
            for page in cast(Iterable[Any], source_response.items()):
                rows.extend(page if isinstance(page, list) else [page])
            return rows, sent_params

    def test_fresh_run_paginates_to_total_count_and_checkpoints(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        # 100 total records across two full pages: pagination must stop at TOTAL_COUNT
        # without paying a third, empty-page request.
        responses = [
            _ridb_response(_facility_rows(0, PAGE_LIMIT), total_count=100, offset=0),
            _ridb_response(_facility_rows(PAGE_LIMIT, PAGE_LIMIT), total_count=100, offset=PAGE_LIMIT),
        ]
        rows, sent_params = self._drive("Facilities", manager, responses)

        assert len(rows) == 100
        assert rows[0]["FacilityID"] == "0"
        assert [p.get("offset") for p in sent_params] == [0, PAGE_LIMIT]
        assert all(p.get("limit") == PAGE_LIMIT for p in sent_params)

        # The api key must ride the header, never the query string.
        assert all("apikey" not in p for p in sent_params)

        # State is saved only after the non-terminal page, pointing at the next offset.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [RecreationResumeConfig(offset=PAGE_LIMIT)]

    def test_short_page_terminates_without_saving_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_ridb_response(_facility_rows(0, 3), total_count=3, offset=0)]
        rows, sent_params = self._drive("Facilities", manager, responses)

        assert len(rows) == 3
        assert len(sent_params) == 1
        manager.save_state.assert_not_called()

    def test_resume_seeds_paginator_with_saved_offset(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = RecreationResumeConfig(offset=150)

        responses = [_ridb_response(_facility_rows(150, 10), total_count=160, offset=150)]
        _, sent_params = self._drive("Facilities", manager, responses)

        assert [p.get("offset") for p in sent_params] == [150]
        manager.load_state.assert_called_once()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_ridb_response(_facility_rows(0, 1), total_count=1, offset=0)]
        self._drive("Facilities", manager, responses)

        manager.load_state.assert_not_called()
