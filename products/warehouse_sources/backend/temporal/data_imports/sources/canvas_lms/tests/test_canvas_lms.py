import json
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms import canvas_lms as canvas_lms_module
from products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.canvas_lms import (
    CanvasHostNotAllowedError,
    CanvasLmsResumeConfig,
    _format_canvas_datetime,
    _incremental_window,
    canvas_lms_source,
    normalize_domain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(items: Optional[list[dict[str, Any]]], *, status_code: int = 200, link: Optional[str] = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(items if items is not None else []).encode()
    if link:
        resp.headers["Link"] = link
    return resp


def _make_manager(resume_state: Optional[CanvasLmsResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        # Mirror `requests.Session.prepare_request`: the real prepared request's `.url`
        # is what `RESTClient._check_allowed_host` inspects (host/scheme/port pinning), so
        # a bare `MagicMock()` here -- whose `.url` is an unconfigured child mock -- fails
        # `urlparse`/`urlsplit` with a `MagicMock`-vs-`int` `TypeError` once that host check
        # runs, rather than exercising it.
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestNormalizeDomain:
    @parameterized.expand(
        [
            ("yourschool.instructure.com", "yourschool.instructure.com"),
            ("https://yourschool.instructure.com", "yourschool.instructure.com"),
            ("http://yourschool.instructure.com/", "yourschool.instructure.com"),
            ("  yourschool.instructure.com  ", "yourschool.instructure.com"),
            ("yourschool.instructure.com/api/v1", "yourschool.instructure.com"),
            ("canvas.university.edu", "canvas.university.edu"),
        ]
    )
    def test_normalize_domain(self, raw, expected):
        assert normalize_domain(raw) == expected


class TestFormatCanvasDatetime:
    def test_formats_naive_datetime_as_utc(self):
        assert _format_canvas_datetime(datetime(2024, 1, 15, 9, 30, 0)) == "2024-01-15T09:30:00Z"

    def test_formats_aware_datetime(self):
        assert _format_canvas_datetime(datetime(2024, 1, 15, 9, 30, 0, tzinfo=UTC)) == "2024-01-15T09:30:00Z"

    def test_formats_date(self):
        assert _format_canvas_datetime(date(2024, 1, 15)) == "2024-01-15T00:00:00Z"

    def test_caps_future_datetime_to_now(self):
        far_future = datetime(2999, 1, 1, tzinfo=UTC)
        formatted = _format_canvas_datetime(far_future)
        assert formatted != "2999-01-01T00:00:00Z"
        assert datetime.strptime(formatted, "%Y-%m-%dT%H:%M:%SZ") <= datetime.now(UTC).replace(tzinfo=None)

    def test_passes_through_already_formatted_string(self):
        assert _format_canvas_datetime("1970-01-01T00:00:00Z") == "1970-01-01T00:00:00Z"


class TestIncrementalWindow:
    @parameterized.expand(
        [
            ("submitted_at", "submitted_since"),
            ("graded_at", "graded_since"),
        ]
    )
    def test_shape(self, field_name, query_param):
        window = _incremental_window(field_name, query_param)

        assert window["cursor_path"] == field_name
        assert window["start_param"] == query_param
        assert window["initial_value"] == "1970-01-01T00:00:00Z"
        assert window["convert"] is _format_canvas_datetime


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(canvas_lms_module, "make_tracked_session", return_value=session)

    def _resp(self, *, status_code=200, text=""):
        response = mock.MagicMock()
        response.status_code = status_code
        response.is_redirect = status_code in (301, 302, 303, 307, 308)
        response.is_permanent_redirect = status_code in (301, 308)
        response.text = text
        return response

    def test_success(self):
        with self._patch_session(self._resp(status_code=200)):
            assert validate_credentials("yourschool.instructure.com", "1", "tok") == (True, None)

    def test_invalid_token(self):
        with self._patch_session(self._resp(status_code=401)):
            valid, msg = validate_credentials("yourschool.instructure.com", "1", "tok")
            assert valid is False
            assert msg == "Invalid Canvas access token"

    def test_unknown_account_is_rejected(self):
        with self._patch_session(self._resp(status_code=404)):
            valid, msg = validate_credentials("yourschool.instructure.com", "999", "tok")
            assert valid is False
            assert msg == "Canvas account not found. Check the account ID and try again."

    def test_403_at_source_create_is_accepted(self):
        with self._patch_session(self._resp(status_code=403)):
            assert validate_credentials("yourschool.instructure.com", "1", "tok", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with self._patch_session(self._resp(status_code=403)):
            valid, msg = validate_credentials("yourschool.instructure.com", "1", "tok", schema_name="courses")
            assert valid is False
            assert msg is not None

    @pytest.mark.parametrize("bad_domain", ["", "not a domain!", "https://"])
    def test_invalid_domain_short_circuits(self, bad_domain):
        valid, msg = validate_credentials(bad_domain, "1", "tok")
        assert valid is False
        assert msg is not None

    def test_request_exception_returns_failure(self):
        import requests

        with self._patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials("yourschool.instructure.com", "1", "tok")
            assert valid is False
            assert "boom" in (msg or "")

    def test_rejects_redirect_response(self):
        with self._patch_session(self._resp(status_code=302)) as patched:
            valid, msg = validate_credentials("yourschool.instructure.com", "1", "tok")
            assert valid is False
            assert msg == canvas_lms_module.HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(canvas_lms_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(self._resp(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("10.0.0.1", "1", "tok", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()


class TestCanvasLmsSourceResponse:
    @parameterized.expand(
        [
            ("courses", ["id"], "created_at"),
            ("users", ["id"], None),
            ("enrollments", ["id", "course_id"], "created_at"),
            ("assignments", ["id", "course_id"], "created_at"),
            ("submissions", ["assignment_id", "user_id"], None),
        ]
    )
    def test_response_shape(self, endpoint, primary_keys, partition_key):
        response = canvas_lms_source(
            domain="yourschool.instructure.com",
            account_id="1",
            api_key="tok",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None


class TestCanvasLmsTopLevelPagination:
    def _source(self, endpoint="courses", manager=None, **kwargs):
        return canvas_lms_source(
            domain="yourschool.instructure.com",
            account_id="1",
            api_key="tok",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=manager if manager is not None else _make_manager(),
            **kwargs,
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_link_header_across_pages(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _response(
                    [{"id": "1"}, {"id": "2"}],
                    link='<https://yourschool.instructure.com/api/v1/accounts/1/courses?page=bookmark>; rel="next"',
                ),
                _response([{"id": "3"}]),
            ],
        )
        rows = _rows(self._source())

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        assert snaps[0]["url"] == "https://yourschool.instructure.com/api/v1/accounts/1/courses"
        assert snaps[0]["params"]["per_page"] == 100
        assert snaps[1]["url"] == "https://yourschool.instructure.com/api/v1/accounts/1/courses?page=bookmark"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_yielding(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    [{"id": "1"}],
                    link='<https://yourschool.instructure.com/api/v1/accounts/1/courses?page=bookmark>; rel="next"',
                ),
                _response([{"id": "2"}]),
            ],
        )
        manager = _make_manager()
        _rows(self._source(manager=manager))

        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, CanvasLmsResumeConfig)
        assert saved.next_url == "https://yourschool.instructure.com/api/v1/accounts/1/courses?page=bookmark"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"id": "9"}])])
        manager = _make_manager(
            CanvasLmsResumeConfig(next_url="https://yourschool.instructure.com/api/v1/accounts/1/courses?page=resume")
        )
        rows = _rows(self._source(manager=manager))

        assert snaps[0]["url"] == "https://yourschool.instructure.com/api/v1/accounts/1/courses?page=resume"
        assert [r["id"] for r in rows] == ["9"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_does_not_follow_next_url_on_foreign_host(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1"}], link='<http://169.254.169.254/latest/meta-data/>; rel="next"')])
        rows = _rows(self._source())

        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_ignores_resume_url_on_foreign_host(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"id": "1"}])])
        manager = _make_manager(CanvasLmsResumeConfig(next_url="http://169.254.169.254/latest/meta-data/"))
        rows = _rows(self._source(manager=manager))

        assert snaps[0]["url"].startswith("https://yourschool.instructure.com/api/v1/accounts/1/courses")
        assert [r["id"] for r in rows] == ["1"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_runtime_host_check_blocks_unsafe_domain(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1"}])])
        with mock.patch.object(canvas_lms_module, "_is_host_safe", return_value=(False, "internal address")):
            with pytest.raises(CanvasHostNotAllowedError):
                _rows(self._source())
        session.send.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_users_endpoint_builds_correct_path(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"id": "1"}])])
        _rows(self._source(endpoint="users"))

        assert snaps[0]["url"] == "https://yourschool.instructure.com/api/v1/accounts/1/users"


class _FakeDltResource:
    """Stand-in for a DltResource returned by ``rest_api_resources``."""

    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper: Any) -> "_FakeDltResource":
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


class TestCanvasLmsFanout:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_submissions_injects_course_id_from_parent(self, mock_rest_api_resources):
        mock_rest_api_resources.return_value = [
            _FakeDltResource("courses", [{"id": "1000"}]),
            _FakeDltResource("submissions", [{"assignment_id": "1", "user_id": "2", "_courses_id": "1000"}]),
        ]
        manager = _make_manager()

        resp = canvas_lms_source(
            domain="yourschool.instructure.com",
            account_id="1",
            api_key="tok",
            endpoint="submissions",
            team_id=1,
            job_id="j",
            resumable_source_manager=manager,
        )

        rows = list(cast(Any, resp.items()))
        assert len(rows) == 1
        row = rows[0]
        assert row["course_id"] == "1000"
        assert "_courses_id" not in row

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.canvas_lms.build_dependent_resource"
    )
    def test_enrollments_fanout_pins_account_id_and_page_size_param(self, mock_build):
        mock_build.return_value = iter([])
        manager = _make_manager()

        canvas_lms_source(
            domain="yourschool.instructure.com",
            account_id="42",
            api_key="tok",
            endpoint="enrollments",
            team_id=1,
            job_id="j",
            resumable_source_manager=manager,
        )

        _, kwargs = mock_build.call_args
        assert kwargs["path_format_values"] == {"account_id": "42"}
        assert kwargs["page_size_param"] == "per_page"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.canvas_lms.build_dependent_resource"
    )
    def test_submissions_incremental_maps_field_to_query_param(self, mock_build):
        mock_build.return_value = iter([])
        manager = _make_manager()

        canvas_lms_source(
            domain="yourschool.instructure.com",
            account_id="1",
            api_key="tok",
            endpoint="submissions",
            team_id=1,
            job_id="j",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="graded_at",
        )

        _, kwargs = mock_build.call_args
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["incremental_field"] == "graded_at"
        window = kwargs["incremental_config_factory"]("submitted_at")
        assert window["start_param"] == "submitted_since"
        window = kwargs["incremental_config_factory"]("graded_at")
        assert window["start_param"] == "graded_since"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.canvas_lms.build_dependent_resource"
    )
    def test_fanout_seeds_resume_state_and_wires_hook(self, mock_build):
        mock_build.return_value = iter([])
        manager = _make_manager(
            CanvasLmsResumeConfig(
                completed=["/courses/1/enrollments"], current="/courses/2/enrollments", child_state={"next_url": "x"}
            )
        )

        canvas_lms_source(
            domain="yourschool.instructure.com",
            account_id="1",
            api_key="tok",
            endpoint="enrollments",
            team_id=1,
            job_id="j",
            resumable_source_manager=manager,
        )

        _, kwargs = mock_build.call_args
        assert kwargs["initial_paginator_state"] == {
            "completed": ["/courses/1/enrollments"],
            "current": "/courses/2/enrollments",
            "child_state": {"next_url": "x"},
        }

        kwargs["resume_hook"](
            {"completed": ["/courses/1/enrollments", "/courses/2/enrollments"], "current": None, "child_state": None}
        )
        manager.save_state.assert_called_once_with(
            CanvasLmsResumeConfig(
                completed=["/courses/1/enrollments", "/courses/2/enrollments"], current=None, child_state=None
            )
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.canvas_lms.build_dependent_resource"
    )
    def test_fanout_does_not_load_state_when_cannot_resume(self, mock_build):
        mock_build.return_value = iter([])
        manager = _make_manager()

        canvas_lms_source(
            domain="yourschool.instructure.com",
            account_id="1",
            api_key="tok",
            endpoint="assignments",
            team_id=1,
            job_id="j",
            resumable_source_manager=manager,
        )

        manager.load_state.assert_not_called()
        _, kwargs = mock_build.call_args
        assert kwargs["initial_paginator_state"] is None

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.canvas_lms._is_host_safe")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.canvas_lms.build_dependent_resource"
    )
    def test_fanout_runtime_host_check_blocks_unsafe_domain(self, mock_build, mock_is_host_safe):
        mock_build.return_value = iter([[{"id": "1"}]])
        mock_is_host_safe.return_value = (False, "internal address")
        manager = _make_manager()

        resp = canvas_lms_source(
            domain="yourschool.instructure.com",
            account_id="1",
            api_key="tok",
            endpoint="assignments",
            team_id=1,
            job_id="j",
            resumable_source_manager=manager,
        )

        with pytest.raises(CanvasHostNotAllowedError):
            _rows(resp)
