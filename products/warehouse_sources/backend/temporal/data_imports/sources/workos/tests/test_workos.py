import json
import dataclasses
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.settings import ENDPOINTS, WORKOS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.workos import (
    WorkOSPaginator,
    WorkOSResumeConfig,
    get_resource,
    validate_credentials,
    workos_source,
)


class TestWorkOSPaginator:
    def test_initial_state(self) -> None:
        paginator = WorkOSPaginator()
        assert paginator._after is None
        assert paginator.has_next_page is True

    @pytest.mark.parametrize(
        ("label", "response_body", "has_next", "expected_after"),
        [
            (
                "more_pages",
                {"data": [{"id": "org_1"}], "list_metadata": {"before": None, "after": "org_1"}},
                True,
                "org_1",
            ),
            (
                "last_page",
                {"data": [{"id": "org_2"}], "list_metadata": {"before": "org_1", "after": None}},
                False,
                None,
            ),
            ("no_metadata", {"data": []}, False, None),
            ("empty_dict", {}, False, None),
        ],
    )
    def test_update_state(self, label: str, response_body: Any, has_next: bool, expected_after: str | None) -> None:
        paginator = WorkOSPaginator()
        response = MagicMock()
        response.json.return_value = response_body
        paginator.update_state(response)
        assert paginator._has_next_page is has_next
        assert paginator._after == expected_after

    @pytest.mark.parametrize(
        ("label", "seeded_after", "expected_after_param"),
        [
            ("fresh_run_omits_after", None, None),
            ("resumed_sets_after", "org_50", "org_50"),
        ],
    )
    def test_init_request(self, label: str, seeded_after: str | None, expected_after_param: str | None) -> None:
        paginator = WorkOSPaginator()
        if seeded_after is not None:
            paginator.set_resume_state({"after": seeded_after})

        request = Request(method="GET", url="https://api.workos.com/organizations", params={"limit": 100})
        paginator.init_request(request)

        if expected_after_param is None:
            assert "after" not in (request.params or {})
        else:
            assert request.params["after"] == expected_after_param

    def test_update_request_sets_after_when_next_page(self) -> None:
        paginator = WorkOSPaginator()
        response = MagicMock()
        response.json.return_value = {"data": [{"id": "org_1"}], "list_metadata": {"after": "org_1"}}
        paginator.update_state(response)

        request = Request(method="GET", url="https://api.workos.com/organizations", params={"limit": 100})
        paginator.update_request(request)

        assert request.params["after"] == "org_1"

    def test_get_resume_state_returns_current_cursor(self) -> None:
        paginator = WorkOSPaginator()
        response = MagicMock()
        response.json.return_value = {"data": [{"id": "org_1"}], "list_metadata": {"after": "org_1"}}
        paginator.update_state(response)
        assert paginator.get_resume_state() == {"after": "org_1"}

    def test_get_resume_state_none_when_no_cursor(self) -> None:
        paginator = WorkOSPaginator()
        assert paginator.get_resume_state() is None

    def test_get_resume_state_none_on_terminal_page(self) -> None:
        # A terminal page leaves the previous cursor in ``_after``; resume state
        # must still be None so we don't re-fetch an already-processed page.
        paginator = WorkOSPaginator()
        first = MagicMock()
        first.json.return_value = {"data": [{"id": "org_1"}], "list_metadata": {"after": "org_1"}}
        paginator.update_state(first)
        terminal = MagicMock()
        terminal.json.return_value = {"data": [{"id": "org_2"}], "list_metadata": {"after": None}}
        paginator.update_state(terminal)
        assert paginator.has_next_page is False
        assert paginator.get_resume_state() is None

    def test_set_resume_state_round_trip(self) -> None:
        paginator = WorkOSPaginator()
        paginator.set_resume_state({"after": "org_99"})
        assert paginator._after == "org_99"
        assert paginator.has_next_page is True
        assert paginator.get_resume_state() == {"after": "org_99"}

    def test_set_resume_state_ignores_missing_cursor(self) -> None:
        paginator = WorkOSPaginator()
        paginator.set_resume_state({})
        assert paginator._after is None


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _page(ids: list[str], after: str | None) -> dict[str, Any]:
    return {"data": [{"id": i} for i in ids], "list_metadata": {"before": None, "after": after}}


class TestWorkOSEndpoints:
    def test_all_endpoints_registered(self) -> None:
        assert set(ENDPOINTS) == set(WORKOS_ENDPOINTS)
        # Every endpoint partitions on the immutable created_at field.
        assert all(cfg.partition_key == "created_at" for cfg in WORKOS_ENDPOINTS.values())

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_resource_request_params_are_valid(self, endpoint: str) -> None:
        # directory_users and directory_groups reject ``order=asc`` with a 422; every
        # WorkOS list endpoint accepts ``order=desc`` (the WorkOS SDK default). Guard
        # against regressing back to the rejected value on any endpoint.
        endpoint_config = cast(dict[str, Any], get_resource(endpoint)["endpoint"])
        params = cast(dict[str, Any], endpoint_config["params"])
        assert params["order"] == "desc"
        assert params["limit"] == WORKOS_ENDPOINTS[endpoint].page_size

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_response_shape(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        response = workos_source(
            api_key="sk_test_123",
            endpoint=endpoint,
            team_id=123,
            job_id="job_1",
            resumable_source_manager=manager,
        )

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"


class TestWorkOSSourceResumeBehavior:
    """End-to-end resume behaviour through the shared ``rest_api_resource`` path."""

    def _drive(self, manager: MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source_response = workos_source(
                api_key="sk_test_123",
                endpoint="organizations",
                team_id=123,
                job_id="job_1",
                resumable_source_manager=manager,
            )
            list(cast(Iterable[Any], source_response.items()))
            return sent_params

    def test_fresh_run_saves_cursor_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_page(["org_1", "org_2"], after="org_2")),
            _make_http_response(_page(["org_3", "org_4"], after="org_4")),
            _make_http_response(_page(["org_5"], after=None)),
        ]
        sent_params = self._drive(manager, responses)

        # First request omits the cursor (fresh run); subsequent requests carry it.
        assert [p.get("after") for p in sent_params] == [None, "org_2", "org_4"]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [WorkOSResumeConfig(after="org_2"), WorkOSResumeConfig(after="org_4")]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = WorkOSResumeConfig(after="org_4")

        responses = [
            _make_http_response(_page(["org_5"], after=None)),
        ]
        sent_params = self._drive(manager, responses)

        # First request goes out at the resumed cursor — no re-fetch of synced pages.
        assert [p.get("after") for p in sent_params] == ["org_4"]

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_page(["org_only"], after=None)),
        ]
        self._drive(manager, responses)

        manager.save_state.assert_not_called()


class TestWorkOSValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "body", "expected_valid"),
        [
            (200, {"data": [], "list_metadata": {}}, True),
            # A valid key lacking the Organizations scope still proves authenticity at source-create.
            (403, {"message": "forbidden"}, True),
            (401, {"message": "unauthorized"}, False),
            (500, {"message": "server error"}, False),
        ],
    )
    def test_validate_credentials(self, status_code: int, body: Any, expected_valid: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.workos.workos.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.return_value = _make_http_response(body, status_code=status_code)
            is_valid, _ = validate_credentials("sk_test_123")
            assert is_valid is expected_valid

    def test_resume_config_serialization_round_trip(self) -> None:
        cfg = WorkOSResumeConfig(after="org_1500")
        reconstituted = WorkOSResumeConfig(**json.loads(json.dumps(dataclasses.asdict(cfg))))
        assert reconstituted == cfg
