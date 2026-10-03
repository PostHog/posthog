import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.companycam.companycam import (
    CompanycamCursorPaginator,
    CompanycamResumeConfig,
    _paginator_for,
    _to_iso8601,
    _to_unix_timestamp,
    companycam_source,
    get_resource,
    validate_credentials,
)


class TestCompanycamCursorPaginator:
    def test_initial_state(self) -> None:
        paginator = CompanycamCursorPaginator(per_page=100)
        assert paginator._cursor is None
        assert paginator.has_next_page is True

    def test_init_request_sends_per_page_and_no_cursor_when_fresh(self) -> None:
        paginator = CompanycamCursorPaginator(per_page=100)
        request = Request(method="GET", url="https://api.companycam.com/v2/photos")
        paginator.init_request(request)
        assert request.params == {"per_page": 100}

    def test_init_request_seeds_after_cursor_when_resumed(self) -> None:
        paginator = CompanycamCursorPaginator(per_page=100)
        paginator.set_resume_state({"cursor": "cursor-abc"})
        request = Request(method="GET", url="https://api.companycam.com/v2/photos")
        paginator.init_request(request)
        assert request.params == {"per_page": 100, "after": "cursor-abc"}

    @pytest.mark.parametrize(
        ("has_next_header", "next_cursor_header", "expected_has_next"),
        [
            ("true", "cursor-1", True),
            ("false", "", False),
            (None, "cursor-2", True),
            (None, "", False),
            ("true", "", False),  # header says more but no cursor to fetch it with
        ],
    )
    def test_update_state(self, has_next_header: str | None, next_cursor_header: str, expected_has_next: bool) -> None:
        paginator = CompanycamCursorPaginator(per_page=100)
        response = MagicMock()
        headers = {"X-Next-Cursor": next_cursor_header}
        if has_next_header is not None:
            headers["X-Has-Next"] = has_next_header
        response.headers = headers

        paginator.update_state(response)

        assert paginator.has_next_page is expected_has_next

    def test_get_resume_state_round_trip(self) -> None:
        paginator = CompanycamCursorPaginator(per_page=100)
        response = MagicMock()
        response.headers = {"X-Has-Next": "true", "X-Next-Cursor": "cursor-9"}
        paginator.update_state(response)

        assert paginator.get_resume_state() == {"cursor": "cursor-9"}

    def test_get_resume_state_none_on_terminal_page(self) -> None:
        paginator = CompanycamCursorPaginator(per_page=100)
        response = MagicMock()
        response.headers = {"X-Has-Next": "false", "X-Next-Cursor": ""}
        paginator.update_state(response)

        assert paginator.get_resume_state() is None


class TestPaginatorFor:
    def test_photos_uses_cursor_paginator(self) -> None:
        assert isinstance(_paginator_for("Photos"), CompanycamCursorPaginator)

    def test_checklist_templates_uses_single_page_paginator(self) -> None:
        assert isinstance(_paginator_for("ChecklistTemplates"), SinglePagePaginator)

    @pytest.mark.parametrize("endpoint", ["Projects", "Videos", "Users", "Tags", "Groups", "Checklists"])
    def test_other_endpoints_use_page_number_paginator(self, endpoint: str) -> None:
        assert isinstance(_paginator_for(endpoint), PageNumberPaginator)


class TestConverters:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1700000000, "2023-11-14T22:13:20+00:00"),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), "2023-11-14T22:13:20+00:00"),
            (None, None),
        ],
    )
    def test_to_iso8601(self, value: Any, expected: str | None) -> None:
        assert _to_iso8601(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1700000000, "1700000000"),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), "1700000000"),
            (None, None),
        ],
    )
    def test_to_unix_timestamp(self, value: Any, expected: str | None) -> None:
        assert _to_unix_timestamp(value) == expected


class TestGetResource:
    def test_full_refresh_uses_replace_disposition(self) -> None:
        resource = cast(dict[str, Any], get_resource("Users", should_use_incremental_field=False))
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["params"] == {"per_page": 100}

    def test_incremental_endpoint_sets_merge_disposition_and_incremental_param(self) -> None:
        resource = cast(dict[str, Any], get_resource("Projects", should_use_incremental_field=True))
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        assert "modified_since" in resource["endpoint"]["params"]
        assert resource["endpoint"]["params"]["modified_since"]["type"] == "incremental"

    def test_incremental_endpoint_without_incremental_flag_has_no_incremental_param(self) -> None:
        resource = cast(dict[str, Any], get_resource("Projects", should_use_incremental_field=False))
        assert "modified_since" not in resource["endpoint"]["params"]

    def test_full_refresh_endpoint_never_gets_incremental_param(self) -> None:
        # Users has no incremental_query_param at all, regardless of should_use_incremental_field.
        resource = cast(dict[str, Any], get_resource("Users", should_use_incremental_field=True))
        assert "modified_since" not in resource["endpoint"]["params"]
        assert "start_date" not in resource["endpoint"]["params"]

    def test_cursor_paginated_endpoint_has_no_static_per_page_param(self) -> None:
        # Photos' per_page is injected by CompanycamCursorPaginator itself.
        resource = cast(dict[str, Any], get_resource("Photos", should_use_incremental_field=False))
        assert "per_page" not in resource["endpoint"]["params"]


def _make_http_response(
    body: list[dict[str, Any]], headers: dict[str, str] | None = None, status_code: int = 200
) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    for key, value in (headers or {}).items():
        resp.headers[key] = value
    return resp


class TestCompanycamSourceResumeBehavior:
    """End-to-end resume behaviour of ``companycam_source`` via ``rest_api_resource``."""

    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
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

            resource = companycam_source(
                api_key="test-key",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
                api_version="v2",
            )
            list(cast(Iterable[Any], resource.items()))
            return mock_session, sent_params

    def test_page_number_endpoint_saves_page_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response([{"id": "1"}]),
            _make_http_response([{"id": "2"}]),
            _make_http_response([]),
        ]
        _, sent_params = self._drive("Users", manager, responses)

        pages_sent = [p.get("page") for p in sent_params]
        assert pages_sent == [1, 2, 3]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            CompanycamResumeConfig(page=2),
            CompanycamResumeConfig(page=3),
        ]

    def test_page_number_endpoint_resumes_from_saved_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = CompanycamResumeConfig(page=5)

        responses = [_make_http_response([])]
        _, sent_params = self._drive("Users", manager, responses)

        assert sent_params[0]["page"] == 5

    def test_cursor_endpoint_saves_cursor_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response([{"id": "p1"}], headers={"X-Has-Next": "true", "X-Next-Cursor": "cursor-1"}),
            _make_http_response([{"id": "p2"}], headers={"X-Has-Next": "false", "X-Next-Cursor": ""}),
        ]
        _, sent_params = self._drive("Photos", manager, responses)

        cursors_sent = [p.get("after") for p in sent_params]
        assert cursors_sent == [None, "cursor-1"]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [CompanycamResumeConfig(cursor="cursor-1")]

    def test_cursor_endpoint_resumes_from_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = CompanycamResumeConfig(cursor="cursor-resumed")

        responses = [_make_http_response([], headers={"X-Has-Next": "false"})]
        _, sent_params = self._drive("Photos", manager, responses)

        assert sent_params[0]["after"] == "cursor-resumed"

    def test_single_page_endpoint_never_saves_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{"id": "t1"}])]
        self._drive("ChecklistTemplates", manager, responses)

        manager.save_state.assert_not_called()

    def test_incremental_sync_omits_filter_param_on_first_sync(self) -> None:
        # No watermark yet (first sync): the framework drops a None-valued param entirely,
        # so the request is an unfiltered full pull.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([])]
        _, sent_params = self._drive("Projects", manager, responses, should_use_incremental_field=True)

        assert "modified_since" not in sent_params[0]

    def test_incremental_sync_sends_filter_param_once_watermark_exists(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([])]
        _, sent_params = self._drive(
            "Projects",
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
        )

        assert sent_params[0]["modified_since"] == "2023-11-14T22:13:20+00:00"

    def test_incremental_sync_sends_unix_timestamp_filter_for_photos(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([], headers={"X-Has-Next": "false"})]
        _, sent_params = self._drive(
            "Photos",
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
        )

        assert sent_params[0]["start_date"] == "1700000000"

    def test_source_response_sort_mode(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.return_value = _make_http_response([])

            response = companycam_source(
                api_key="test-key",
                endpoint="Projects",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
                api_version="v2",
            )
        assert response.sort_mode == "desc"
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created_at"]

    def test_source_response_sort_mode_defaults_to_asc_on_full_refresh(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.return_value = _make_http_response([])

            response = companycam_source(
                api_key="test-key",
                endpoint="Projects",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
                api_version="v2",
            )
        assert response.sort_mode == "asc"


class TestValidateCredentials:
    @pytest.mark.parametrize(("status_code", "expected"), [(200, True), (401, False), (403, False)])
    def test_validate_credentials(self, status_code: int, expected: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.companycam.companycam.make_tracked_session"
        ) as mock_make_session:
            mock_session = mock_make_session.return_value
            mock_session.get.return_value = MagicMock(status_code=status_code)

            assert validate_credentials("test-key", "v2") is expected

    def test_validate_credentials_transport_error_returns_false(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.companycam.companycam.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.side_effect = ConnectionError("boom")

            assert validate_credentials("test-key", "v2") is False
