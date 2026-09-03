import json
from collections.abc import Iterable
from typing import Any, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.nuntly import (
    NuntlyResumeConfig,
    nuntly_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.settings import ENDPOINTS


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestNuntlySourceResumeBehavior:
    """End-to-end cursor pagination + resume behaviour of ``nuntly_source``."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[MagicMock, list[dict[str, Any]], list[str]]:
        """Drive ``nuntly_source`` with a mocked HTTP session.

        Returns ``(mock_session, sent_params, sent_urls)``. Params/urls are captured at
        send-time since the underlying Request object is mutated in-place between pages.
        """
        sent_params: list[dict[str, Any]] = []
        sent_urls: list[str] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            sent_urls.append(request.url)
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            response = nuntly_source(
                api_key="apk_test",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            list(cast(Iterable[Any], response.items()))
            return mock_session, sent_params, sent_urls

    @parameterized.expand([("Emails",), ("Messages",), ("Inboxes",), ("Domains",), ("Webhooks",)])
    def test_fresh_run_walks_pages_and_saves_cursor_after_each_non_terminal_page(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"data": [{"id": "1"}], "nextCursor": "cursor-1"}),
            _make_http_response({"data": [{"id": "2"}], "nextCursor": "cursor-2"}),
            _make_http_response({"data": [{"id": "3"}], "nextCursor": None}),
        ]
        _, sent_params, sent_urls = self._drive(endpoint, manager, responses)

        cursors_sent = [p.get("cursor") for p in sent_params]
        assert cursors_sent == [None, "cursor-1", "cursor-2"]
        assert all(p.get("limit") == 30 for p in sent_params)
        assert all(url.startswith(f"https://api.nuntly.com{ENDPOINTS[endpoint].path}") for url in sent_urls)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            NuntlyResumeConfig(cursor="cursor-1"),
            NuntlyResumeConfig(cursor="cursor-2"),
        ]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = NuntlyResumeConfig(cursor="cursor-resumed")

        responses = [_make_http_response({"data": [{"id": "4"}], "nextCursor": None})]
        _, sent_params, _ = self._drive("Emails", manager, responses)

        assert [p.get("cursor") for p in sent_params] == ["cursor-resumed"]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [{"id": "only"}], "nextCursor": None})]
        self._drive("Emails", manager, responses)

        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [{"id": "a"}], "nextCursor": None})]
        self._drive("Emails", manager, responses)

        manager.load_state.assert_not_called()

    @parameterized.expand([("Emails",), ("Messages",), ("Inboxes",), ("Domains",), ("Webhooks",)])
    def test_source_response_uses_declared_primary_keys_and_partitioning(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.return_value = _make_http_response({"data": [], "nextCursor": None})

            response = nuntly_source(
                api_key="apk_test",
                endpoint=endpoint,
                team_id=1,
                job_id="job",
                resumable_source_manager=manager,
            )

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]


class TestValidateCredentials:
    @parameterized.expand([(200, True), (401, False), (403, False), (500, False)])
    def test_status_mapping(self, status_code: int, expected_valid: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.nuntly.make_tracked_session"
        ) as mock_make_session:
            mock_session = mock_make_session.return_value
            mock_session.get.return_value = MagicMock(status_code=status_code)

            is_valid, code = validate_credentials("apk_test")

        assert (is_valid, code) == (expected_valid, status_code)

    def test_transport_error_maps_to_false_none(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.nuntly.make_tracked_session"
        ) as mock_make_session:
            mock_session = mock_make_session.return_value
            mock_session.get.side_effect = ConnectionError("boom")

            assert validate_credentials("apk_test") == (False, None)


class TestEndpointSettings:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_every_declared_endpoint_has_a_settings_entry(self, endpoint: str) -> None:
        assert ENDPOINTS[endpoint].path.startswith("/")
        assert ENDPOINTS[endpoint].primary_keys == ["id"]
