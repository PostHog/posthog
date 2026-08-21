import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.pipeliner import pipeliner as pipeliner_module
from products.warehouse_sources.backend.temporal.data_imports.sources.pipeliner.pipeliner import (
    PAGE_SIZE,
    PipelinerHostNotAllowedError,
    PipelinerResumeConfig,
    _format_incremental_value,
    normalize_service_url,
    pipeliner_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pipeliner.settings import ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(
    items: Optional[list[dict[str, Any]]],
    *,
    end_cursor: Optional[str] = None,
    has_next_page: bool = False,
    include_page_info: bool = True,
    status_code: int = 200,
    location: Optional[str] = None,
) -> Response:
    payload: dict[str, Any] = {"success": True, "data": items or []}
    if include_page_info and (end_cursor is not None or has_next_page):
        payload["page_info"] = {"end_cursor": end_cursor, "has_next_page": has_next_page}
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(payload).encode()
    if location is not None:
        resp.headers["Location"] = location
    return resp


def _manager(resume: Optional[PipelinerResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages (the paginator appends the
    ``after`` cursor), so snapshot a copy when each request is prepared instead of after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _run(manager, responses, **kwargs) -> tuple[list[dict[str, Any]], mock.MagicMock, list[dict[str, Any]]]:
    with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        params = _wire(session, responses)
        response = pipeliner_source(
            service_url="us-east.api.pipelinersales.com",
            space_id="space-1",
            username="user",
            password="pass",
            endpoint="accounts",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
            **kwargs,
        )
        rows = [row for page in cast("Iterable[Any]", response.items()) for row in page]
    return rows, session, params


class TestNormalizeServiceUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("us-east.api.pipelinersales.com", "us-east.api.pipelinersales.com"),
            ("https://us-east.api.pipelinersales.com", "us-east.api.pipelinersales.com"),
            ("http://us-east.api.pipelinersales.com/", "us-east.api.pipelinersales.com"),
            ("  eu-central.api.pipelinersales.com  ", "eu-central.api.pipelinersales.com"),
            (
                "https://us-east.api.pipelinersales.com/api/v100/rest/spaces/abc",
                "us-east.api.pipelinersales.com",
            ),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_service_url(raw) == expected


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04 02:58:14"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04 02:58:14"),
            (date(2026, 3, 4), "2026-03-04 00:00:00"),
            ("2026-03-04 00:00:00", "2026-03-04 00:00:00"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_incremental_value(value) == expected


class TestPipelinerSourceTransport:
    def test_paginates_with_after_cursor_until_last_page(self):
        rows, session, params = _run(
            _manager(),
            [
                _response([{"id": "1"}, {"id": "2"}], end_cursor="cur1", has_next_page=True),
                _response([{"id": "3"}], end_cursor="cur2", has_next_page=False),
            ],
        )

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        assert "after" not in params[0]
        assert params[0]["first"] == PAGE_SIZE
        # `end_cursor` is still present on the last page — termination is driven by has_next_page.
        assert params[1]["after"] == "cur1"
        assert session.send.call_count == 2

    def test_requests_target_space_scoped_entity_url(self):
        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            urls: list[str] = []

            def _prepare(request):
                urls.append(request.url)
                return mock.MagicMock()

            session.headers = {}
            session.prepare_request.side_effect = _prepare
            session.send.side_effect = [_response([{"id": "1"}])]

            response = pipeliner_source(
                service_url="us-east.api.pipelinersales.com",
                space_id="space-1",
                username="user",
                password="pass",
                endpoint="accounts",
                team_id=1,
                job_id="job-1",
                resumable_source_manager=_manager(),
            )
            list(cast("Iterable[Any]", response.items()))

        assert urls[0] == "https://us-east.api.pipelinersales.com/api/v100/rest/spaces/space-1/entities/Accounts"

    def test_incremental_run_sends_server_side_filter_and_matching_sort(self):
        _rows, _session, params = _run(
            _manager(),
            [_response([{"id": "1"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field="modified",
        )

        assert params[0]["filter[modified]"] == "2026-01-01 00:00:00"
        assert params[0]["filter-op[modified]"] == "gte"
        assert params[0]["order-by"] == "modified"

    def test_incremental_first_sync_has_no_filter_but_sorts_by_cursor_field(self):
        _rows, _session, params = _run(
            _manager(),
            [_response([{"id": "1"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="modified",
        )

        assert "filter[modified]" not in params[0]
        assert params[0]["order-by"] == "modified"

    def test_full_refresh_has_no_filter_and_sorts_by_created(self):
        _rows, _session, params = _run(
            _manager(),
            [_response([{"id": "1"}])],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert not any(key.startswith("filter") for key in params[0])
        assert params[0]["order-by"] == "created"

    def test_saves_state_after_yielding_each_page(self):
        manager = _manager()
        _run(
            manager,
            [
                _response([{"id": "1"}], end_cursor="cur1", has_next_page=True),
                _response([{"id": "2"}], end_cursor="cur2", has_next_page=False),
            ],
        )

        # State is saved once per followed page boundary — after page 1 yielded, not for the last page.
        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, PipelinerResumeConfig)
        assert saved.cursor == "cur1"

    def test_resumes_from_saved_cursor_and_reapplies_saved_filter(self):
        manager = _manager(PipelinerResumeConfig(cursor="resume-cur", filter_value="2026-01-01 00:00:00"))
        _rows, _session, params = _run(
            manager,
            [_response([{"id": "9"}])],
            should_use_incremental_field=True,
            # A watermark that advanced mid-job must not replace the filter the cursor was minted under.
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
            incremental_field="modified",
        )

        assert params[0]["after"] == "resume-cur"
        assert params[0]["filter[modified]"] == "2026-01-01 00:00:00"

    def test_empty_page_terminates_even_when_has_next_page(self):
        rows, session, _params = _run(
            _manager(),
            [_response([], end_cursor="cur1", has_next_page=True)],
        )

        assert rows == []
        assert session.send.call_count == 1

    def test_missing_page_info_terminates(self):
        rows, session, _params = _run(
            _manager(),
            [_response([{"id": "1"}], include_page_info=False)],
        )

        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 1

    def test_redirect_response_is_rejected(self):
        # The service URL is user-controlled; a 3xx could point at an internal address (SSRF).
        with pytest.raises(ValueError, match="redirect"):
            _run(_manager(), [_response([], status_code=302, location="https://evil.example.com")])

    def test_blocks_unsafe_host_before_any_request(self):
        manager = _manager()
        with (
            mock.patch.object(pipeliner_module, "_is_host_safe", return_value=(False, "internal address")),
            mock.patch(CLIENT_SESSION_PATCH) as MockSession,
        ):
            session = MockSession.return_value
            session.send.side_effect = [_response([{"id": "1"}])]
            response = pipeliner_source(
                service_url="10.0.0.1",
                space_id="space-1",
                username="user",
                password="pass",
                endpoint="accounts",
                team_id=1,
                job_id="job-1",
                resumable_source_manager=manager,
            )
            with pytest.raises(PipelinerHostNotAllowedError):
                list(cast("Iterable[Any]", response.items()))
            session.send.assert_not_called()


class TestPipelinerSourceResponse:
    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_response_shape(self, endpoint):
        response = pipeliner_source(
            service_url="us-east.api.pipelinersales.com",
            space_id="space-1",
            username="user",
            password="pass",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=mock.MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        # `created` never changes; partitioning on `modified` would rewrite partitions on every edit.
        assert response.partition_keys == ["created"]
        assert response.partition_mode == "datetime"


class TestValidateCredentials:
    def _validate_response(
        self, *, status_code: int = 200, json_data: Any = None, text: str = "", json_raises: bool = False
    ) -> mock.MagicMock:
        response = mock.MagicMock()
        response.status_code = status_code
        response.ok = 200 <= status_code < 400
        response.is_redirect = status_code in (302, 303, 307)
        response.is_permanent_redirect = status_code in (301, 308)
        response.text = text
        if json_raises:
            response.json.side_effect = ValueError("not json")
        else:
            response.json.return_value = json_data
        return response

    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(pipeliner_module, "make_tracked_session", return_value=session)

    def test_success(self):
        with self._patch_session(self._validate_response(status_code=200, json_data={"success": True, "data": []})):
            assert validate_credentials("us-east.api.pipelinersales.com", "space-1", "user", "pass") == (True, None)

    def test_invalid_credentials(self):
        with self._patch_session(self._validate_response(status_code=401)):
            valid, msg = validate_credentials("us-east.api.pipelinersales.com", "space-1", "user", "pass")
            assert valid is False
            assert msg == "Invalid Pipeliner API credentials"

    def test_403_at_source_create_is_accepted(self):
        with self._patch_session(self._validate_response(status_code=403)):
            assert validate_credentials(
                "us-east.api.pipelinersales.com", "space-1", "user", "pass", schema_name=None
            ) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with self._patch_session(self._validate_response(status_code=403)):
            valid, msg = validate_credentials(
                "us-east.api.pipelinersales.com", "space-1", "user", "pass", schema_name="accounts"
            )
            assert valid is False
            assert msg is not None

    @pytest.mark.parametrize("bad_service_url", ["", "not a host!", "https://"])
    def test_invalid_service_url_short_circuits(self, bad_service_url):
        valid, msg = validate_credentials(bad_service_url, "space-1", "user", "pass")
        assert valid is False
        assert msg == "Invalid Pipeliner service URL"

    @pytest.mark.parametrize("bad_space_id", ["", "  ", "space/../../etc"])
    def test_invalid_space_id_short_circuits(self, bad_space_id):
        valid, msg = validate_credentials("us-east.api.pipelinersales.com", bad_space_id, "user", "pass")
        assert valid is False
        assert msg == "Invalid Pipeliner space ID"

    def test_error_message_surfaced_from_api_envelope(self):
        body = {"code": 404, "name": "ERROR_NOT_FOUND", "message": "Space not found.", "success": False}
        with self._patch_session(self._validate_response(status_code=404, json_data=body)):
            valid, msg = validate_credentials("us-east.api.pipelinersales.com", "space-1", "user", "pass")
            assert valid is False
            assert msg == "Space not found."

    def test_request_exception_returns_failure(self):
        import requests

        with self._patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials("us-east.api.pipelinersales.com", "space-1", "user", "pass")
            assert valid is False
            assert "boom" in (msg or "")

    def test_rejects_redirect_response(self):
        with self._patch_session(self._validate_response(status_code=302)):
            valid, msg = validate_credentials("us-east.api.pipelinersales.com", "space-1", "user", "pass")
            assert valid is False
            assert msg == pipeliner_module.HOST_NOT_ALLOWED_ERROR

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(pipeliner_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(self._validate_response(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("10.0.0.1", "space-1", "user", "pass", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()
