import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.loops.loops import (
    LoopsResumeConfig,
    loops_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.loops.settings import LOOPS_ENDPOINTS


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _page(rows: list[dict[str, Any]], next_cursor: str | None) -> dict[str, Any]:
    return {
        "pagination": {
            "totalResults": len(rows),
            "returnedResults": len(rows),
            "perPage": 50,
            "totalPages": 1,
            "nextCursor": next_cursor,
            "nextPage": None,
        },
        "data": rows,
    }


class TestLoopsSource:
    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Drive ``loops_source`` with a mocked HTTP session.

        Returns ``(rows, sent_params)``: ``rows`` is the flattened row stream (the
        resource yields one list per page), and ``sent_params`` holds shallow copies
        of ``request.params`` captured at send-time — the Request object is mutated
        in-place by the paginator between pages.
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

            source_response = loops_source(
                api_key="test-key",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            rows = [
                row
                for item in cast(Iterable[Any], source_response.items())
                for row in (item if isinstance(item, list) else [item])
            ]
            return rows, sent_params

    def test_fresh_run_pages_through_cursors_and_saves_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_page([{"id": "c1"}], next_cursor="cursor-1")),
            _make_http_response(_page([{"id": "c2"}], next_cursor="cursor-2")),
            _make_http_response(_page([{"id": "c3"}], next_cursor=None)),
        ]
        rows, sent_params = self._drive("campaigns", manager, responses)

        assert [row["id"] for row in rows] == ["c1", "c2", "c3"]
        # First request has no cursor (fresh run); subsequent requests carry the
        # prior page's nextCursor. Every request asks for the max page size.
        assert [p.get("cursor") for p in sent_params] == [None, "cursor-1", "cursor-2"]
        assert all(p.get("perPage") == 50 for p in sent_params)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            LoopsResumeConfig(cursor="cursor-1"),
            LoopsResumeConfig(cursor="cursor-2"),
        ]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = LoopsResumeConfig(cursor="cursor-resumed")

        responses = [
            _make_http_response(_page([{"id": "c4"}], next_cursor=None)),
        ]
        _, sent_params = self._drive("campaigns", manager, responses)

        assert [p.get("cursor") for p in sent_params] == ["cursor-resumed"]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_page([{"id": "only"}], next_cursor=None)),
        ]
        self._drive("campaigns", manager, responses)

        manager.save_state.assert_not_called()
        manager.load_state.assert_not_called()

    @pytest.mark.parametrize(
        ("endpoint", "body", "expected_ids", "expected_params"),
        [
            (
                "mailing_lists",
                [{"id": "list-1", "name": "Beta"}, {"id": "list-2", "name": "Launch"}],
                ["list-1", "list-2"],
                {},
            ),
            (
                "contact_properties",
                [{"key": "firstName", "label": "First Name", "type": "string"}],
                ["firstName"],
                {"list": "all"},
            ),
        ],
    )
    def test_unpaginated_endpoints_yield_bare_array_in_one_request(
        self,
        endpoint: str,
        body: list[dict[str, Any]],
        expected_ids: list[str],
        expected_params: dict[str, str],
    ) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        rows, sent_params = self._drive(endpoint, manager, [_make_http_response(body)])

        id_field = LOOPS_ENDPOINTS[endpoint].primary_key
        assert [row[id_field] for row in rows] == expected_ids
        assert sent_params == [expected_params]
        manager.save_state.assert_not_called()

    @pytest.mark.parametrize("endpoint", list(LOOPS_ENDPOINTS.keys()))
    def test_source_response_primary_and_partition_keys(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        source_response = loops_source(
            api_key="test-key",
            endpoint=endpoint,
            team_id=123,
            job_id="test_job",
            resumable_source_manager=manager,
        )

        endpoint_config = LOOPS_ENDPOINTS[endpoint]
        assert source_response.name == endpoint
        assert source_response.primary_keys == [endpoint_config.primary_key]
        if endpoint_config.partition_key:
            assert source_response.partition_keys == [endpoint_config.partition_key]
            assert source_response.partition_mode == "datetime"
        else:
            assert source_response.partition_keys is None
            assert source_response.partition_mode is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_message_fragment"),
        [
            (200, True, None),
            (401, False, "Invalid Loops API key"),
            (500, False, "unexpected status code: 500"),
        ],
    )
    def test_status_code_mapping(
        self, status_code: int, expected_valid: bool, expected_message_fragment: str | None
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.loops.loops.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.return_value = _make_http_response({"success": True}, status_code)

            is_valid, message = validate_credentials("test-key")

        assert is_valid is expected_valid
        if expected_message_fragment is None:
            assert message is None
        else:
            assert message is not None and expected_message_fragment in message

    def test_network_error_returns_invalid(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.loops.loops.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.side_effect = ConnectionError("connection refused")

            is_valid, message = validate_credentials("test-key")

        assert is_valid is False
        assert message is not None and "connection refused" in message
