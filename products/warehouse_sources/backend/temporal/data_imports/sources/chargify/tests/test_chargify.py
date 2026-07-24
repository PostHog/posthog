import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.chargify.chargify import (
    ChargifyPaginator,
    ChargifyResumeConfig,
    base_url,
    chargify_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chargify.settings import (
    CHARGIFY_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class TestChargifyPaginator:
    def test_initial_state_is_page_one(self) -> None:
        paginator = ChargifyPaginator()
        assert paginator.page == 1
        # BasePaginator starts with _has_next_page=True so the first request runs.
        assert paginator.has_next_page is True

    def test_update_state_advances_page_when_data(self) -> None:
        paginator = ChargifyPaginator()
        response = MagicMock()
        paginator.update_state(response, data=[{"id": 1}])
        assert paginator.page == 2
        assert paginator.has_next_page is True

    def test_update_state_stops_on_empty_page(self) -> None:
        paginator = ChargifyPaginator()
        response = MagicMock()
        paginator.update_state(response, data=[])
        # Page is not advanced past the empty terminal page.
        assert paginator.page == 1
        assert paginator.has_next_page is False

    def test_get_resume_state_returns_next_page(self) -> None:
        paginator = ChargifyPaginator()
        paginator.update_state(MagicMock(), data=[{"id": 1}])
        assert paginator.get_resume_state() == {"page": 2}

    def test_get_resume_state_returns_none_on_terminal_page(self) -> None:
        paginator = ChargifyPaginator()
        paginator.update_state(MagicMock(), data=[])
        assert paginator.get_resume_state() is None

    def test_set_resume_state_round_trip(self) -> None:
        paginator = ChargifyPaginator()
        paginator.set_resume_state({"page": 7})
        assert paginator.page == 7
        assert paginator.has_next_page is True

    def test_set_resume_state_coerces_to_int(self) -> None:
        # A Redis round-trip can return the page as a string; the request needs an int.
        paginator = ChargifyPaginator()
        paginator.set_resume_state({"page": "9"})
        assert paginator.page == 9

    def test_set_resume_state_ignores_missing_page(self) -> None:
        paginator = ChargifyPaginator()
        paginator.set_resume_state({})
        assert paginator.page == 1

    @pytest.mark.parametrize(("seeded_page", "expected"), [(None, 1), (4, 4)])
    def test_init_request_targets_current_page(self, seeded_page: int | None, expected: int) -> None:
        paginator = ChargifyPaginator()
        if seeded_page is not None:
            paginator.set_resume_state({"page": seeded_page})

        request = Request(method="GET", url="https://acme.chargify.com/customers.json")
        paginator.init_request(request)

        assert request.params["page"] == expected


class TestGetResource:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_resource_matches_settings(self, endpoint: str) -> None:
        resource = get_resource(endpoint)
        config = CHARGIFY_ENDPOINTS[endpoint]

        assert resource["name"] == endpoint
        assert resource["table_format"] == "delta"
        # Every endpoint is full refresh today.
        assert resource["write_disposition"] == "replace"
        endpoint_config = cast(dict[str, Any], resource["endpoint"])
        assert endpoint_config["path"] == config.path
        assert endpoint_config["data_selector"] == config.data_selector

    def test_bare_array_endpoints_unwrap_the_payload_key(self) -> None:
        # Chargify wraps each row under a single object key, so the selector must unwrap it.
        endpoint_config = cast(dict[str, Any], get_resource("Customers")["endpoint"])
        assert endpoint_config["data_selector"] == "[*].customer"

    def test_invoices_selects_the_wrapped_list(self) -> None:
        # The Invoices API nests its list under an "invoices" key alongside "meta".
        endpoint_config = cast(dict[str, Any], get_resource("Invoices")["endpoint"])
        assert endpoint_config["data_selector"] == "invoices"


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
    ) -> tuple[MagicMock, list[dict[str, Any]]]:
        """Drive ``chargify_source`` with a mocked HTTP session.

        Returns ``(mock_session, sent_params)`` where ``sent_params`` captures a shallow
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
            list(cast(Iterable[Any], resource))
            return mock_session, sent_params

    @pytest.mark.parametrize("endpoint", ["Customers", "Subscriptions", "Events", "Transactions"])
    def test_fresh_run_saves_page_after_each_non_terminal_page(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        selector_key = CHARGIFY_ENDPOINTS[endpoint].data_selector.split(".")[-1]
        responses = [
            _make_http_response([{selector_key: {"id": 1}}]),
            _make_http_response([{selector_key: {"id": 2}}]),
            _make_http_response([]),
        ]
        _, sent_params = self._drive(endpoint, manager, responses)

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
        _, sent_params = self._drive("Customers", manager, responses)

        assert [p.get("page") for p in sent_params] == [5, 6]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        # A single empty page terminates immediately, so no resumable checkpoint is persisted.
        responses = [_make_http_response([])]
        self._drive("Customers", manager, responses)

        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{"customer": {"id": 1}}]), _make_http_response([])]
        self._drive("Customers", manager, responses)

        manager.load_state.assert_not_called()


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


def test_base_url_is_per_site_subdomain() -> None:
    assert base_url("acme") == "https://acme.chargify.com"
