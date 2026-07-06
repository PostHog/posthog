import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.factorial.factorial import (
    BASE_URL,
    PAGE_SIZE,
    FactorialCursorPaginator,
    FactorialResumeConfig,
    factorial_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.factorial.settings import (
    ENDPOINTS,
    FACTORIAL_ENDPOINTS,
)

_SESSION_FACTORY = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.factorial.factorial.make_tracked_session"
)


def _full_page() -> list[dict[str, Any]]:
    return [{"id": i} for i in range(PAGE_SIZE)]


def _meta_response(meta: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"meta": meta, "data": []}
    return response


class TestFactorialCursorPaginator:
    def test_initial_state(self) -> None:
        paginator = FactorialCursorPaginator()
        assert paginator.has_next_page is True

    def test_init_request_emits_limit_only_when_fresh(self) -> None:
        paginator = FactorialCursorPaginator()
        request = Request(method="GET", url=f"{BASE_URL}/resources/employees/employees")
        paginator.init_request(request)
        assert request.params["limit"] == PAGE_SIZE
        assert "after_id" not in request.params

    def test_advances_after_id_on_non_terminal_page(self) -> None:
        paginator = FactorialCursorPaginator()
        paginator.update_state(_meta_response({"has_next_page": True, "end_cursor": "Mjc="}), _full_page())
        assert paginator.has_next_page is True

        request = Request(method="GET", url=f"{BASE_URL}/resources/employees/employees")
        paginator.update_request(request)
        assert request.params["after_id"] == "Mjc="

    def test_stops_when_has_next_page_false(self) -> None:
        paginator = FactorialCursorPaginator()
        paginator.update_state(_meta_response({"has_next_page": False, "end_cursor": "Mjc="}), _full_page())
        assert paginator.has_next_page is False

    def test_stops_when_no_end_cursor(self) -> None:
        paginator = FactorialCursorPaginator()
        paginator.update_state(_meta_response({"has_next_page": True}), _full_page())
        assert paginator.has_next_page is False

    def test_stops_on_empty_page_even_if_api_claims_more(self) -> None:
        # A misreported has_next_page must never loop us forever on an empty page.
        paginator = FactorialCursorPaginator()
        paginator.update_state(_meta_response({"has_next_page": True, "end_cursor": "Mjc="}), [])
        assert paginator.has_next_page is False

    def test_get_resume_state_when_next_page(self) -> None:
        paginator = FactorialCursorPaginator()
        paginator.update_state(_meta_response({"has_next_page": True, "end_cursor": "Mjc="}), _full_page())
        assert paginator.get_resume_state() == {"after_id": "Mjc="}

    def test_get_resume_state_none_on_terminal_page(self) -> None:
        paginator = FactorialCursorPaginator()
        paginator.update_state(_meta_response({"has_next_page": False}), [])
        assert paginator.get_resume_state() is None

    def test_set_resume_state_round_trip(self) -> None:
        paginator = FactorialCursorPaginator()
        paginator.set_resume_state({"after_id": "MTY="})
        assert paginator.has_next_page is True

        request = Request(method="GET", url=f"{BASE_URL}/resources/employees/employees")
        paginator.init_request(request)
        assert request.params["after_id"] == "MTY="
        assert request.params["limit"] == PAGE_SIZE

    def test_set_resume_state_ignores_missing_cursor(self) -> None:
        paginator = FactorialCursorPaginator()
        paginator.set_resume_state({})
        request = Request(method="GET", url=f"{BASE_URL}/resources/employees/employees")
        paginator.init_request(request)
        assert "after_id" not in request.params


class TestGetResource:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_resource_shape(self, endpoint: str) -> None:
        resource = get_resource(endpoint)
        config = FACTORIAL_ENDPOINTS[endpoint]

        assert resource["name"] == endpoint
        assert resource["table_name"] == endpoint
        assert resource["write_disposition"] == "replace"
        assert resource["table_format"] == "delta"

        endpoint_def = cast(dict[str, Any], resource["endpoint"])
        assert endpoint_def["path"] == config.path
        assert endpoint_def["path"].startswith("/resources/")
        # Every Factorial list endpoint wraps records under the top-level `data` key.
        assert endpoint_def["data_selector"] == "data"


class TestSourceResponsePartitioning:
    def _build(self, endpoint: str) -> Any:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        with patch(_SESSION_FACTORY):
            return factorial_source(
                api_key="test-key",
                endpoint=endpoint,
                team_id=123,
                job_id="job-1",
                resumable_source_manager=manager,
            )

    @pytest.mark.parametrize(
        "endpoint",
        [e for e, c in FACTORIAL_ENDPOINTS.items() if c.partition_key],
    )
    def test_partitioned_endpoints_use_datetime_partitioning(self, endpoint: str) -> None:
        response = self._build(endpoint)
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.partition_format == "week"
        assert response.sort_mode == "asc"

    @pytest.mark.parametrize(
        "endpoint",
        [e for e, c in FACTORIAL_ENDPOINTS.items() if not c.partition_key],
    )
    def test_unpartitioned_endpoints_skip_partitioning(self, endpoint: str) -> None:
        response = self._build(endpoint)
        assert response.partition_mode is None
        assert response.partition_keys is None
        assert response.partition_count is None

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_primary_keys_are_id(self, endpoint: str) -> None:
        response = self._build(endpoint)
        assert response.primary_keys == ["id"]


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestFactorialSourceResumeBehavior:
    """End-to-end resume behaviour of ``factorial_source`` via ``rest_api_resource``."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[MagicMock, list[dict[str, Any]]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(_SESSION_FACTORY) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source = factorial_source(
                api_key="test-key",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            list(cast(Iterable[Any], source.items()))
            return mock_session, sent_params

    def _page_body(self, items: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
        return {"data": items, "meta": meta}

    def test_fresh_run_saves_cursor_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(self._page_body(_full_page(), {"has_next_page": True, "end_cursor": "Mjc="})),
            _make_http_response(self._page_body([{"id": 999}], {"has_next_page": False, "end_cursor": None})),
        ]
        _, sent_params = self._drive("employees", manager, responses)

        # First request starts without a cursor; the second carries the advanced after_id.
        assert "after_id" not in sent_params[0]
        assert sent_params[1].get("after_id") == "Mjc="
        assert all(p.get("limit") == PAGE_SIZE for p in sent_params)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [FactorialResumeConfig(after_id="Mjc=")]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = FactorialResumeConfig(after_id="MTY=")

        responses = [
            _make_http_response(self._page_body([{"id": 17}], {"has_next_page": False, "end_cursor": None})),
        ]
        _, sent_params = self._drive("employees", manager, responses)

        assert sent_params[0].get("after_id") == "MTY="
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(self._page_body([{"id": 1}], {"has_next_page": False, "end_cursor": None})),
        ]
        self._drive("employees", manager, responses)

        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(self._page_body([{"id": 1}], {"has_next_page": False, "end_cursor": None})),
        ]
        self._drive("employees", manager, responses)

        manager.load_state.assert_not_called()


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        with patch(_SESSION_FACTORY) as MockSession:
            mock_session = MockSession.return_value
            response = MagicMock()
            response.status_code = status_code
            mock_session.get.return_value = response

            valid, error = validate_credentials("test-key")
            assert valid is expected_valid
            if expected_valid:
                assert error is None
            else:
                assert error is not None

    def test_probes_employees_endpoint_with_api_key_header(self) -> None:
        with patch(_SESSION_FACTORY) as MockSession:
            mock_session = MockSession.return_value
            response = MagicMock()
            response.status_code = 200
            mock_session.get.return_value = response

            validate_credentials("test-key")

            call = mock_session.get.call_args
            assert call.args[0] == f"{BASE_URL}/resources/employees/employees"
            assert call.kwargs["headers"] == {"x-api-key": "test-key"}
            assert call.kwargs["params"] == {"limit": 1}
            assert call.kwargs["allow_redirects"] is False

    def test_network_error_returns_message(self) -> None:
        with patch(_SESSION_FACTORY) as MockSession:
            MockSession.return_value.get.side_effect = Exception("boom")
            valid, error = validate_credentials("test-key")
            assert valid is False
            assert error == "boom"
