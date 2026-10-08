import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.chargify.chargify import (
    ChargifyPaginator,
    ChargifyResumeConfig,
    chargify_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chargify.settings import CHARGIFY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class TestChargifyPaginator:
    def test_get_resume_state_returns_none_on_terminal_page(self) -> None:
        paginator = ChargifyPaginator()
        paginator.update_state(MagicMock(), data=[])
        assert paginator.get_resume_state() is None


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestChargifySourceResumeBehavior:
    """End-to-end resume behaviour of ``chargify_source`` via ``rest_api_resource``."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[MagicMock, list[dict[str, Any]], list[Any]]:
        """Drive ``chargify_source`` with a mocked HTTP session.

        Returns ``(mock_session, sent_params, rows)`` where ``sent_params`` captures a shallow
        copy of ``request.params`` at send-time — the Request object is mutated in place
        by the paginator between pages, so mock call history can't be trusted for it.
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

            resource = chargify_source(
                api_key="test-key",
                subdomain="acme",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=None,
                should_use_incremental_field=False,
            )
            rows = list(cast(Iterable[Any], resource))
            return mock_session, sent_params, rows

    @pytest.mark.parametrize(
        "endpoint", ["Customers", "Subscriptions", "Events", "Transactions", "Coupons", "ReasonCodes"]
    )
    def test_fresh_run_saves_page_after_each_non_terminal_page(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        selector_key = CHARGIFY_ENDPOINTS[endpoint].data_selector.split(".")[-1]
        responses = [
            _make_http_response([{selector_key: {"id": 1}}]),
            _make_http_response([{selector_key: {"id": 2}}]),
            _make_http_response([]),
        ]
        _, sent_params, _ = self._drive(endpoint, manager, responses)

        assert [p.get("page") for p in sent_params] == [1, 2, 3]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [ChargifyResumeConfig(next_page=2), ChargifyResumeConfig(next_page=3)]

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ChargifyResumeConfig(next_page=5)

        responses = [
            _make_http_response([{"customer": {"id": 1}}]),
            _make_http_response([]),
        ]
        _, sent_params, _ = self._drive("Customers", manager, responses)

        assert [p.get("page") for p in sent_params] == [5, 6]
        manager.load_state.assert_called_once()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{"customer": {"id": 1}}]), _make_http_response([])]
        self._drive("Customers", manager, responses)

        manager.load_state.assert_not_called()

    @pytest.mark.parametrize(
        ("endpoint", "first_page", "empty_page", "expected_row"),
        [
            ("Coupons", [{"coupon": {"id": 1, "code": "FREE"}}], [], {"id": 1, "code": "FREE"}),
            ("ReasonCodes", [{"reason_code": {"id": 2, "code": "LARGE"}}], [], {"id": 2, "code": "LARGE"}),
            (
                "CreditNotes",
                {"credit_notes": [{"uid": "cn_1", "total_amount": "10.0"}]},
                {"credit_notes": []},
                {"uid": "cn_1", "total_amount": "10.0"},
            ),
        ],
    )
    def test_rows_are_unwrapped_and_pagination_terminates(
        self, endpoint: str, first_page: Any, empty_page: Any, expected_row: dict[str, Any]
    ) -> None:
        # Chargify mixes bare arrays of single-key-wrapped objects with payloads nested under a
        # plural key, so the selector has to strip the right wrapper and the paginator has to
        # recognise an empty page in either shape.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response(first_page), _make_http_response(empty_page)]
        _, sent_params, rows = self._drive(endpoint, manager, responses)

        # The resource yields one list per page.
        assert rows == [[expected_row]]
        assert [p.get("page") for p in sent_params] == [1, 2]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.chargify.chargify.make_tracked_session")
    def test_status_maps_to_validity(self, mock_session_factory: MagicMock, status_code: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        mock_session_factory.return_value.get.return_value = response

        assert validate_credentials("api-key", "acme") is expected

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.chargify.chargify.make_tracked_session")
    def test_probes_the_site_subdomain_host(self, mock_session_factory: MagicMock) -> None:
        mock_get = mock_session_factory.return_value.get
        mock_get.return_value = MagicMock(status_code=200)

        validate_credentials("api-key", "acme")

        called_url = mock_get.call_args.args[0]
        assert called_url.startswith("https://acme.chargify.com")
