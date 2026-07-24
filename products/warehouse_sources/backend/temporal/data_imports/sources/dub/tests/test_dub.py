import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dub.dub import (
    DubCursorPaginator,
    DubResumeConfig,
    _make_session,
    _scrub_link_password,
    check_endpoint_access,
    dub_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dub.settings import DUB_ENDPOINTS, ENDPOINTS


def _rows(n: int, prefix: str = "row") -> list[dict[str, Any]]:
    return [{"id": f"{prefix}-{i}", "createdAt": "2026-01-01T00:00:00.000Z"} for i in range(n)]


def _params(resource: EndpointResource) -> dict[str, Any]:
    endpoint = resource["endpoint"]
    assert isinstance(endpoint, dict)
    params = endpoint.get("params")
    assert params is not None
    return params


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestDubCursorPaginator:
    def test_full_page_advances_cursor_to_last_row_id(self) -> None:
        paginator = DubCursorPaginator(page_size=3)
        paginator.update_state(MagicMock(), data=_rows(3))

        assert paginator.has_next_page is True

        request = Request(method="GET", url="https://api.dub.co/links", params={})
        paginator.update_request(request)
        assert request.params["startingAfter"] == "row-2"

    @pytest.mark.parametrize(
        ("label", "rows"),
        [
            ("short_page", _rows(2)),
            ("empty_page", []),
            ("non_list_body", cast(list[Any], None)),
        ],
    )
    def test_terminal_pages_stop_pagination(self, label: str, rows: list[Any]) -> None:
        paginator = DubCursorPaginator(page_size=3)
        response = MagicMock()
        response.json.return_value = rows
        paginator.update_state(response, data=rows if isinstance(rows, list) else None)

        assert paginator.has_next_page is False

    def test_fresh_paginator_does_not_inject_cursor_on_first_request(self) -> None:
        paginator = DubCursorPaginator(page_size=100)
        request = Request(method="GET", url="https://api.dub.co/links", params={})
        paginator.init_request(request)

        assert "startingAfter" not in request.params

    def test_resume_state_round_trip(self) -> None:
        paginator = DubCursorPaginator(page_size=3)
        paginator.update_state(MagicMock(), data=_rows(3))

        state = paginator.get_resume_state()
        assert state == {"starting_after": "row-2"}

        resumed = DubCursorPaginator(page_size=3)
        resumed.set_resume_state(state or {})
        request = Request(method="GET", url="https://api.dub.co/links", params={})
        resumed.init_request(request)

        assert request.params["startingAfter"] == "row-2"
        assert resumed.has_next_page is True

    def test_no_resume_state_on_terminal_page(self) -> None:
        paginator = DubCursorPaginator(page_size=3)
        paginator.update_state(MagicMock(), data=_rows(1))

        assert paginator.get_resume_state() is None


class TestGetResource:
    def test_event_endpoint_defaults_to_full_history(self) -> None:
        # /events defaults to a 24h window server-side; without interval=all a first
        # sync would silently import only the last day.
        resource = get_resource("click_events", False, None)
        params = _params(resource)

        assert params["interval"] == "all"
        assert "start" not in params
        assert params["event"] == "clicks"
        assert params["sortOrder"] == "asc"

    def test_event_endpoint_uses_watermark_as_start(self) -> None:
        watermark = datetime(2026, 5, 1, 12, 30, tzinfo=UTC)
        resource = get_resource("lead_events", True, watermark)
        params = _params(resource)

        assert params["start"] == watermark.isoformat()
        assert "interval" not in params

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_every_endpoint_builds_a_resource(self, endpoint: str) -> None:
        resource = get_resource(endpoint, False, None)

        assert resource["name"] == endpoint
        assert resource["write_disposition"] == "replace"
        params = _params(resource)
        config = DUB_ENDPOINTS[endpoint]
        assert params[config.page_size_param] == config.page_size

    def test_incremental_run_uses_merge_disposition(self) -> None:
        resource = get_resource("sale_events", True, None)

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_every_resource_scrubs_link_passwords(self, endpoint: str) -> None:
        # Link passwords are a credential to the short link's destination, not analytics data;
        # without this map they'd land in a warehouse column any viewer could read.
        assert get_resource(endpoint, False, None)["data_map"] is _scrub_link_password


class TestScrubLinkPassword:
    def test_strips_top_level_and_nested_link_password(self) -> None:
        row = {
            "id": "l1",
            "password": "top-secret",
            "url": "https://example.com",
            "link": {"id": "l2", "password": "nested-secret", "domain": "dub.sh"},
        }

        scrubbed = _scrub_link_password(row)

        assert "password" not in scrubbed
        assert "password" not in scrubbed["link"]
        assert scrubbed["url"] == "https://example.com"
        assert scrubbed["link"]["domain"] == "dub.sh"

    def test_leaves_rows_without_passwords_untouched(self) -> None:
        row = {"id": "l1", "url": "https://example.com", "link": {"id": "l2"}}

        assert _scrub_link_password(row) == row


class TestDubSourceResumeBehavior:
    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> list[dict[str, Any]]:
        """Drive ``dub_source`` with a mocked HTTP session; returns per-request params."""
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.dub.dub.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source_response = dub_source(
                api_key="dub_test",
                endpoint=endpoint,
                team_id=1,
                job_id="job",
                resumable_source_manager=manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )
            list(cast(Iterable[Any], source_response.items()))
            return sent_params

    def test_cursor_endpoint_saves_cursor_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_rows(100, "a")),
            _make_http_response(_rows(100, "b")),
            _make_http_response(_rows(1, "c")),
        ]
        sent_params = self._drive("links", manager, responses)

        assert [p.get("startingAfter") for p in sent_params] == [None, "a-99", "b-99"]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            DubResumeConfig(starting_after="a-99"),
            DubResumeConfig(starting_after="b-99"),
        ]

    def test_cursor_endpoint_resumes_from_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = DubResumeConfig(starting_after="a-42")

        sent_params = self._drive("links", manager, [_make_http_response(_rows(1))])

        assert [p.get("startingAfter") for p in sent_params] == ["a-42"]

    def test_page_endpoint_saves_page_number(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_rows(100, "a")),
            _make_http_response([]),
        ]
        sent_params = self._drive("partners", manager, responses)

        assert [p.get("page") for p in sent_params] == [1, 2]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [DubResumeConfig(page=2)]

    def test_incremental_event_sync_ignores_saved_page_state(self) -> None:
        # On incremental runs the timestamp watermark is the resume cursor; replaying a
        # saved page number against a fresher `start` filter would skip rows.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = DubResumeConfig(page=7)

        sent_params = self._drive(
            "click_events",
            manager,
            [_make_http_response(_rows(1)), _make_http_response([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-05-01T00:00:00",
        )

        manager.load_state.assert_not_called()
        manager.save_state.assert_not_called()
        assert sent_params[0]["page"] == 1
        assert sent_params[0]["start"] == "2026-05-01T00:00:00"

    def test_full_refresh_event_sync_still_uses_page_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = DubResumeConfig(page=7)

        sent_params = self._drive("click_events", manager, [_make_http_response(_rows(1)), _make_http_response([])])

        assert sent_params[0]["page"] == 7


class TestMakeSession:
    def test_disables_sample_capture(self) -> None:
        # Every Dub path (sync + both credential probes) builds its session here. Dub payloads
        # carry imported customer data the name-based scrubbers can't recognise, so capture must
        # stay off or sampling would leak it into the shared sample bucket.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.dub.dub.make_tracked_session"
        ) as make_session:
            _make_session("secret-key")
        assert make_session.call_args.kwargs["capture"] is False
        assert make_session.call_args.kwargs["redact_values"] == ("secret-key",)


class TestCredentialValidation:
    def _mock_session(self, response: Response) -> Any:
        session = MagicMock()
        session.get.return_value = response
        return session

    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (401, False),
            (403, False),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected_valid: bool) -> None:
        response = _make_http_response({"error": {"code": "forbidden", "message": "Nope"}}, status_code)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.dub.dub.make_tracked_session",
            return_value=self._mock_session(response),
        ):
            valid, message = validate_credentials("dub_test")

        assert valid is expected_valid
        assert (message is None) is expected_valid

    def test_check_endpoint_access_surfaces_api_denial_message(self) -> None:
        response = _make_http_response(
            {"error": {"code": "forbidden", "message": "Requires a Business plan or higher."}}, 403
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.dub.dub.make_tracked_session",
            return_value=self._mock_session(response),
        ):
            assert check_endpoint_access("dub_test", "click_events") == "Requires a Business plan or higher."

    @pytest.mark.parametrize("status_code", [200, 429, 500])
    def test_check_endpoint_access_only_denials_block(self, status_code: int) -> None:
        # A throttle or transient 5xx must never hide a table from the schema picker.
        response = _make_http_response({"error": {"code": "x", "message": "x"}}, status_code)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.dub.dub.make_tracked_session",
            return_value=self._mock_session(response),
        ):
            assert check_endpoint_access("dub_test", "payouts") is None
