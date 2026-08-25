import json
from collections.abc import Iterable
from typing import Any, Optional, cast

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.torii.settings import (
    ENDPOINTS,
    PARTITION_KEYS,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.torii.torii import (
    ToriiResumeConfig,
    torii_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the torii module.
TORII_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.torii.torii.make_tracked_session"
)

_DATA_SELECTOR = {
    "Apps": "apps",
    "Users": "users",
    "Contracts": "contracts",
    "Transactions": "transactions",
}


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _make_manager(resume_cursor: Optional[str] = None) -> mock.MagicMock:
    manager = mock.MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume_cursor is not None
    manager.load_state.return_value = ToriiResumeConfig(cursor=resume_cursor) if resume_cursor else None
    return manager


class TestToriiSourceResumeBehavior:
    """End-to-end pagination/resume behaviour of ``torii_source`` via ``rest_api_resource``."""

    def _drive(
        self, endpoint: str, manager: mock.MagicMock, responses: list[Response]
    ) -> tuple[mock.MagicMock, list[dict[str, Any]]]:
        """Drive ``torii_source`` with a mocked HTTP session.

        Returns ``(mock_session, sent_params)`` where ``sent_params`` is a list of shallow
        copies of ``request.params`` captured at send-time — the underlying Request object is
        mutated in-place by the paginator between pages, so we can't rely on mock
        ``call_args_list`` to preserve history.
        """
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            response = torii_source(
                api_key="test-key",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                api_version="1.1",
            )
            list(cast("Iterable[Any]", response.items()))
            return mock_session, sent_params

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_fresh_run_saves_cursor_after_each_non_terminal_page(self, endpoint: str) -> None:
        manager = _make_manager()
        key = _DATA_SELECTOR[endpoint]

        responses = [
            _make_http_response({key: [{"id": "1"}], "count": 1, "total": 3, "nextCursor": "cursor-1"}),
            _make_http_response({key: [{"id": "2"}], "count": 1, "total": 3, "nextCursor": "cursor-2"}),
            _make_http_response({key: [{"id": "3"}], "count": 1, "total": 3}),
        ]
        _, sent_params = self._drive(endpoint, manager, responses)

        cursors_sent = [p.get("cursor") for p in sent_params]
        assert cursors_sent == [None, "cursor-1", "cursor-2"]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            ToriiResumeConfig(cursor="cursor-1"),
            ToriiResumeConfig(cursor="cursor-2"),
        ]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        manager = _make_manager(resume_cursor="cursor-resumed")
        responses = [_make_http_response({"apps": [{"id": "only"}]})]
        _, sent_params = self._drive("Apps", manager, responses)

        assert [p.get("cursor") for p in sent_params] == ["cursor-resumed"]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = _make_manager()
        responses = [_make_http_response({"apps": [{"id": "only"}]})]
        self._drive("Apps", manager, responses)
        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = _make_manager()
        responses = [_make_http_response({"apps": [{"id": "a"}]})]
        self._drive("Apps", manager, responses)
        manager.load_state.assert_not_called()

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_sends_pinned_api_version_header(self, endpoint: str) -> None:
        manager = _make_manager()
        key = _DATA_SELECTOR[endpoint]
        responses = [_make_http_response({key: [{"id": "1"}]})]
        mock_session, _ = self._drive(endpoint, manager, responses)
        assert mock_session.headers == {"X-API-Version": "1.1"}


class TestToriiSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, MockSession: mock.MagicMock, endpoint: str) -> None:
        manager = _make_manager()

        response = torii_source(
            api_key="test-key",
            endpoint=endpoint,
            team_id=123,
            job_id="test_job",
            resumable_source_manager=manager,
            api_version="1.1",
        )

        assert response.name == endpoint
        assert response.primary_keys == PRIMARY_KEYS[endpoint]

        partition_key = PARTITION_KEYS[endpoint]
        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_format is None
            assert response.partition_keys is None


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(TORII_SESSION_PATCH)
    def test_status_mapping(self, mock_session: mock.MagicMock, status_code: int, expected: bool) -> None:
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response
        assert validate_credentials("test-key") is expected

    @mock.patch(TORII_SESSION_PATCH)
    def test_swallows_exceptions(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("test-key") is False
