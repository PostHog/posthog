import json
from collections.abc import Iterable
from typing import Any, cast

from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.paystack.paystack import (
    PAGE_SIZE,
    PaystackPaginator,
    PaystackResumeConfig,
    paystack_source,
    validate_credentials,
)


def _meta(page: int, page_count: int) -> dict[str, Any]:
    return {"total": page_count * PAGE_SIZE, "perPage": PAGE_SIZE, "page": page, "pageCount": page_count}


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestPaystackPaginator:
    def test_update_state_stops_on_empty_page_without_meta(self) -> None:
        # No usable meta: fall back to Paystack's documented "stop when a page is empty" signal.
        paginator = PaystackPaginator()
        paginator.update_state(_response({"data": []}), [])
        assert paginator.has_next_page is False

    def test_get_resume_state_returns_none_on_terminal_page(self) -> None:
        paginator = PaystackPaginator(page=2)
        paginator.update_state(_response({"data": [{"id": 1}], "meta": _meta(page=2, page_count=2)}), [{"id": 1}])
        assert paginator.get_resume_state() is None


class TestValidateCredentials:
    def test_sends_bearer_header(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.paystack.paystack.make_tracked_session"
        ) as mock_session:
            mock_session.return_value.get.return_value = _response({"status": True})
            validate_credentials("sk_test_secret")
            _, kwargs = mock_session.return_value.get.call_args
            assert kwargs["headers"]["Authorization"] == "Bearer sk_test_secret"


class TestPaystackSourceResumeBehavior:
    """End-to-end resume behaviour of ``paystack_source`` via ``rest_api_resource``."""

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

            resource = paystack_source(
                secret_api_key="sk_test_x",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            list(cast(Iterable[Any], resource))
            return mock_session, sent_params

    def test_fresh_run_saves_next_page_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _response({"data": [{"id": 1}], "meta": _meta(page=1, page_count=3)}),
            _response({"data": [{"id": 2}], "meta": _meta(page=2, page_count=3)}),
            _response({"data": [{"id": 3}], "meta": _meta(page=3, page_count=3)}),
        ]
        _, sent_params = self._drive("Transactions", manager, responses)

        assert [p.get("page") for p in sent_params] == [1, 2, 3]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [PaystackResumeConfig(next_page=2), PaystackResumeConfig(next_page=3)]

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = PaystackResumeConfig(next_page=5)

        responses = [_response({"data": [{"id": 50}], "meta": _meta(page=5, page_count=5)})]
        _, sent_params = self._drive("Customers", manager, responses)

        assert [p.get("page") for p in sent_params] == [5]
        manager.load_state.assert_called_once()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_response({"data": [{"id": 1}], "meta": _meta(page=1, page_count=1)})]
        self._drive("Refunds", manager, responses)

        manager.load_state.assert_not_called()
