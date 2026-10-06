import copy
import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.attio.attio import (
    AttioResumeConfig,
    attio_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.attio.settings import ATTIO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class TestValidateCredentials:
    def test_non_ascii_key_returns_actionable_message_without_leaking_encoding_error(self):
        # A non-latin-1 key can't be encoded into the Authorization header; the raw
        # UnicodeEncodeError ("'latin-1' codec can't encode ... ordinal not in range(256)")
        # must never surface to the user.
        valid, msg = validate_credentials("bad中key")

        assert valid is False
        assert "Retype it by hand" in (msg or "")
        assert "latin-1" not in (msg or "")
        assert "ordinal not in range" not in (msg or "")


def _page(endpoint: str, start: int, count: int) -> Response:
    primary_key = ATTIO_ENDPOINTS[endpoint].primary_key
    rows = [
        {"id": {"workspace_id": "ws", primary_key: f"row-{i}"}, "created_at": "2024-01-01"}
        for i in range(start, start + count)
    ]
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps({"data": rows}).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _make_manager(resume: AttioResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


class TestAttioResume:
    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        sent: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            # The paginator mutates one request object across pages, so copy what each send carries.
            sent.append(copy.deepcopy(request.json if request.method == "POST" else request.params))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            response = attio_source(
                api_key="key",
                endpoint=endpoint,
                team_id=1,
                job_id="job",
                resumable_source_manager=manager,
            )
            rows = [row for page in cast(Iterable[list[dict[str, Any]]], response.items()) for row in page]
        return sent, rows

    @pytest.mark.parametrize("endpoint", ["companies", "people", "deals", "notes", "tasks"])
    def test_fresh_run_stages_next_offset_after_each_page(self, endpoint: str) -> None:
        limit = ATTIO_ENDPOINTS[endpoint].page_size
        manager = _make_manager()
        responses = [_page(endpoint, 0, limit), _page(endpoint, limit, limit), _page(endpoint, 2 * limit, 3)]

        sent, rows = self._drive(endpoint, manager, responses)

        assert [request["offset"] for request in sent] == [0, limit, 2 * limit]
        assert all(request["limit"] == limit for request in sent)
        assert len(rows) == 2 * limit + 3
        assert rows[-1][ATTIO_ENDPOINTS[endpoint].primary_key] == f"row-{2 * limit + 2}"
        assert [call.args[0] for call in manager.save_state.call_args_list] == [
            AttioResumeConfig(offset=limit),
            AttioResumeConfig(offset=2 * limit),
        ]
        manager.load_state.assert_not_called()

    @pytest.mark.parametrize("endpoint", ["companies", "notes"])
    def test_single_short_page_stages_nothing(self, endpoint: str) -> None:
        manager = _make_manager()

        sent, rows = self._drive(endpoint, manager, [_page(endpoint, 0, 2)])

        assert [request["offset"] for request in sent] == [0]
        assert len(rows) == 2
        manager.save_state.assert_not_called()

    @pytest.mark.parametrize("endpoint", ["companies", "people", "lists", "notes", "tasks", "workspace_members"])
    def test_resumed_run_starts_from_saved_offset(self, endpoint: str) -> None:
        limit = ATTIO_ENDPOINTS[endpoint].page_size
        manager = _make_manager(AttioResumeConfig(offset=2 * limit))
        responses = [_page(endpoint, 2 * limit, limit), _page(endpoint, 3 * limit, 1)]

        sent, rows = self._drive(endpoint, manager, responses)

        assert [request["offset"] for request in sent] == [2 * limit, 3 * limit]
        assert rows[0][ATTIO_ENDPOINTS[endpoint].primary_key] == f"row-{2 * limit}"
        assert [call.args[0] for call in manager.save_state.call_args_list] == [AttioResumeConfig(offset=3 * limit)]

    def test_resumed_query_keeps_sort_order_in_body(self) -> None:
        # Offsets only line up across runs when every run asks for the same order.
        manager = _make_manager(AttioResumeConfig(offset=500))

        sent, _ = self._drive("companies", manager, [_page("companies", 500, 1)])

        assert sent == [{"sorts": [{"attribute": "created_at", "direction": "asc"}], "offset": 500, "limit": 500}]
