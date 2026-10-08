import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.spotlercrm.spotlercrm import (
    SpotlerCRMPaginator,
    SpotlerCRMResumeConfig,
    get_endpoint_permissions,
    spotlercrm_source,
    validate_credentials,
)


def _page_body(records: list[dict[str, Any]], has_more: bool | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {"url": "/accounts", "object_type": "list"}
    if has_more is not None:
        metadata["has_more"] = has_more
    return {"metadata": metadata, "list": [{"metadata": {}, "record": record} for record in records]}


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestSpotlerCRMPaginator:
    def _json_response(self, body: dict[str, Any]) -> MagicMock:
        response = MagicMock()
        response.json.return_value = body
        return response

    def test_no_resume_state_on_terminal_page(self) -> None:
        paginator = SpotlerCRMPaginator()
        paginator.update_state(self._json_response(_page_body([], has_more=False)), [])

        assert paginator.get_resume_state() is None


class TestSpotlerCRMSourceBehavior:
    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[list[dict[str, Any]], list[str], list[list[dict[str, Any]]]]:
        """Drive ``spotlercrm_source`` with a mocked HTTP session.

        Returns ``(sent_params, sent_urls, pages)`` where ``sent_params`` are shallow
        copies of ``request.params`` captured at send-time (the Request object is
        mutated in place between pages) and ``pages`` are the yielded row batches.
        """
        sent_params: list[dict[str, Any]] = []
        sent_urls: list[str] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            sent_urls.append(request.url)
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.spotlercrm.spotlercrm.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source_response = spotlercrm_source(
                access_token="test-token",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            pages = [list(page) for page in cast(Iterable[Any], source_response.items())]
            return sent_params, sent_urls, pages

    def test_fresh_run_pages_forward_and_checkpoints_after_each_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_page_body([{"id": 1}], has_more=True)),
            _make_http_response(_page_body([{"id": 2}], has_more=True)),
            _make_http_response(_page_body([{"id": 3}], has_more=False)),
        ]
        sent_params, _, pages = self._drive("Accounts", manager, responses)

        assert [p.get("page") for p in sent_params] == [1, 2, 3]
        assert [p.get("limit") for p in sent_params] == [100, 100, 100]
        assert pages == [[{"id": 1}], [{"id": 2}], [{"id": 3}]]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            SpotlerCRMResumeConfig(next_page=2),
            SpotlerCRMResumeConfig(next_page=3),
        ]

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = SpotlerCRMResumeConfig(next_page=5)

        responses = [_make_http_response(_page_body([{"id": 42}], has_more=False))]
        sent_params, _, _ = self._drive("Contacts", manager, responses)

        assert [p.get("page") for p in sent_params] == [5]
        manager.load_state.assert_called_once()


class TestSpotlerCRMCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (402, False),
            (403, False),
            (500, False),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected_valid: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.spotlercrm.spotlercrm.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.return_value = _make_http_response({}, status_code=status_code)

            valid, error = validate_credentials("test-token")

        assert valid is expected_valid
        assert (error is None) is expected_valid

    @pytest.mark.parametrize(
        ("status_code", "expects_reason"),
        [
            (200, False),
            (402, True),
            (403, True),
            (404, True),
            (500, False),  # transient failures must not read as missing permissions
        ],
    )
    def test_get_endpoint_permissions_status_mapping(self, status_code: int, expects_reason: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.spotlercrm.spotlercrm.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.return_value = _make_http_response({}, status_code=status_code)

            permissions = get_endpoint_permissions("test-token", ["Cases"])

        assert (permissions["Cases"] is not None) is expects_reason

    def test_get_endpoint_permissions_treats_network_errors_as_reachable(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.spotlercrm.spotlercrm.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.side_effect = ConnectionError("boom")

            permissions = get_endpoint_permissions("test-token", ["Accounts"])

        assert permissions["Accounts"] is None
