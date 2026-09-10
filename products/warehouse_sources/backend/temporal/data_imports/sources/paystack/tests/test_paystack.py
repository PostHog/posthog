import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.paystack.paystack import (
    PAGE_SIZE,
    PaystackPaginator,
    PaystackResumeConfig,
    get_resource,
    paystack_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paystack.settings import ENDPOINTS


def _meta(page: int, page_count: int) -> dict[str, Any]:
    return {"total": page_count * PAGE_SIZE, "perPage": PAGE_SIZE, "page": page, "pageCount": page_count}


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestPaystackPaginator:
    def test_initial_state(self) -> None:
        paginator = PaystackPaginator()
        # BasePaginator starts has_next_page=True so the first request fires; the page begins at 1.
        assert paginator._page == 1
        assert paginator.has_next_page is True

    def test_init_request_sets_page_and_per_page(self) -> None:
        paginator = PaystackPaginator()
        request = Request(method="GET", url="https://api.paystack.co/transaction")
        paginator.init_request(request)
        assert request.params["page"] == 1
        assert request.params["perPage"] == PAGE_SIZE

    def test_update_state_has_more_pages_via_page_count(self) -> None:
        paginator = PaystackPaginator()
        paginator.update_state(_response({"data": [{"id": 1}], "meta": _meta(page=1, page_count=3)}), [{"id": 1}])
        assert paginator.has_next_page is True
        assert paginator._page == 2

    def test_update_state_stops_on_last_page_via_page_count(self) -> None:
        paginator = PaystackPaginator(page=3)
        paginator.update_state(_response({"data": [{"id": 9}], "meta": _meta(page=3, page_count=3)}), [{"id": 9}])
        assert paginator.has_next_page is False

    def test_update_state_stops_on_empty_page_without_meta(self) -> None:
        # No usable meta: fall back to Paystack's documented "stop when a page is empty" signal.
        paginator = PaystackPaginator()
        paginator.update_state(_response({"data": []}), [])
        assert paginator.has_next_page is False

    def test_update_state_advances_without_meta_when_page_full(self) -> None:
        paginator = PaystackPaginator()
        paginator.update_state(_response({"data": [{"id": 1}]}), [{"id": 1}])
        assert paginator.has_next_page is True
        assert paginator._page == 2

    def test_update_request_targets_current_page(self) -> None:
        paginator = PaystackPaginator()
        paginator.update_state(_response({"data": [{"id": 1}], "meta": _meta(page=1, page_count=2)}), [{"id": 1}])
        request = Request(method="GET", url="https://api.paystack.co/transaction")
        paginator.update_request(request)
        assert request.params["page"] == 2

    def test_get_resume_state_returns_next_page_when_more(self) -> None:
        paginator = PaystackPaginator()
        paginator.update_state(_response({"data": [{"id": 1}], "meta": _meta(page=1, page_count=2)}), [{"id": 1}])
        assert paginator.get_resume_state() == {"next_page": 2}

    def test_get_resume_state_returns_none_on_terminal_page(self) -> None:
        paginator = PaystackPaginator(page=2)
        paginator.update_state(_response({"data": [{"id": 1}], "meta": _meta(page=2, page_count=2)}), [{"id": 1}])
        assert paginator.get_resume_state() is None

    def test_set_resume_state_round_trip(self) -> None:
        paginator = PaystackPaginator()
        paginator.set_resume_state({"next_page": 7})
        assert paginator._page == 7
        assert paginator.has_next_page is True
        # init_request must target the resumed page.
        request = Request(method="GET", url="https://api.paystack.co/transaction")
        paginator.init_request(request)
        assert request.params["page"] == 7

    def test_set_resume_state_coerces_to_int(self) -> None:
        paginator = PaystackPaginator()
        paginator.set_resume_state({"next_page": "4"})
        assert paginator._page == 4

    def test_set_resume_state_ignores_missing_page(self) -> None:
        paginator = PaystackPaginator()
        paginator.set_resume_state({})
        assert paginator._page == 1


class TestPaystackResources:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_get_resource_shape(self, endpoint: str) -> None:
        resource = get_resource(endpoint)
        assert resource["name"] == endpoint
        assert resource["table_name"] == endpoint.lower()
        # Full refresh — no verified server-side updated-at filter on Paystack.
        assert resource["write_disposition"] == "replace"
        assert resource["table_format"] == "delta"
        endpoint_config = cast(dict[str, Any], resource["endpoint"])
        assert endpoint_config["data_selector"] == "data"
        assert endpoint_config["path"].startswith("/")


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [(200, True), (401, False), (403, False), (500, False)],
    )
    def test_status_mapping(self, status_code: int, expected: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.paystack.paystack.make_tracked_session"
        ) as mock_session:
            mock_session.return_value.get.return_value = _response({"status": True}, status_code=status_code)
            assert validate_credentials("sk_test_x") is expected

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

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_response({"data": [{"id": 1}], "meta": _meta(page=1, page_count=1)})]
        self._drive("Plans", manager, responses)

        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_response({"data": [{"id": 1}], "meta": _meta(page=1, page_count=1)})]
        self._drive("Refunds", manager, responses)

        manager.load_state.assert_not_called()
