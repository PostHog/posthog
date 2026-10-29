from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms import canvas_lms as canvas_lms_module
from products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.canvas_lms import (
    CanvasHostNotAllowedError,
    CanvasLmsResumeConfig,
    _format_canvas_datetime,
    _incremental_window,
    normalize_domain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.source import CanvasLmsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.canvaslms import (
    CanvasLmsSourceConfig,
)

DOMAIN = "yourschool.instructure.com"
BASE_URL = f"https://{DOMAIN}/api/v1"


def _driver(account_id: str = "1") -> SourceDriver:
    return SourceDriver(
        CanvasLmsSource(), CanvasLmsSourceConfig(canvas_domain=DOMAIN, account_id=account_id, api_key="tok")
    )


def _page(rows: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    headers = {"Link": f'<{next_url}>; rel="next"'} if next_url else {}
    return ScriptedResponse(json=rows, headers=headers)


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
    def test_success(self):
        with scripted_network([ScriptedResponse(status=200, json=[])]) as network:
            assert validate_credentials("yourschool.instructure.com", "1", "tok") == (True, None)
        assert network.requests_log[0].path == "/api/v1/accounts/1/courses"
        assert network.requests_log[0].param("per_page") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer tok"
        assert network.session_options[0]["redact_values"] == ("tok",)
        assert network.session_options[0]["capture"] is False

    def test_unknown_account_is_rejected(self):
        with scripted_network([ScriptedResponse(status=404)]):
            valid, msg = validate_credentials("yourschool.instructure.com", "999", "tok")
        assert valid is False
        assert msg == "Canvas account not found. Check the account ID and try again."

    def test_403_at_source_create_is_accepted(self):
        with scripted_network([ScriptedResponse(status=403)]):
            assert validate_credentials("yourschool.instructure.com", "1", "tok", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with scripted_network([ScriptedResponse(status=403)]):
            valid, msg = validate_credentials("yourschool.instructure.com", "1", "tok", schema_name="courses")
        assert valid is False
        assert msg is not None

    @pytest.mark.parametrize("bad_domain", ["", "not a domain!", "https://"])
    def test_invalid_domain_short_circuits(self, bad_domain):
        valid, msg = validate_credentials(bad_domain, "1", "tok")
        assert valid is False
        assert msg is not None

    def test_rejects_redirect_response(self):
        response = ScriptedResponse(status=302, headers={"Location": "http://169.254.169.254/"})
        with scripted_network([response]) as network:
            valid, msg = validate_credentials("yourschool.instructure.com", "1", "tok")
        assert valid is False
        assert msg == canvas_lms_module.HOST_NOT_ALLOWED_ERROR
        assert len(network.requests_log) == 1

    def test_blocks_unsafe_host(self):
        with patch.object(canvas_lms_module, "_is_host_safe", return_value=(False, "internal address")):
            with scripted_network([]) as network:
                valid, msg = validate_credentials("10.0.0.1", "1", "tok", team_id=99)
        assert valid is False
        assert msg == "internal address"
        assert network.requests_log == []


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
        result = _driver().run(endpoint, [_page([])])
        assert result.raised is None
        response = result.response
        assert response is not None
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
    def test_follows_link_header_across_pages(self):
        result = _driver().run(
            "courses",
            [
                _page(
                    [{"id": "1"}, {"id": "2"}],
                    f"{BASE_URL}/accounts/1/courses?page=bookmark",
                ),
                _page([{"id": "3"}]),
            ],
        )

        assert result.raised is None
        assert [r["id"] for r in result.rows] == ["1", "2", "3"]
        assert result.requests[0].path == "/api/v1/accounts/1/courses"
        assert result.requests[0].param("per_page") == "100"
        assert result.requests[1].param("page") == "bookmark"

    def test_saves_state_after_yielding(self):
        next_url = f"{BASE_URL}/accounts/1/courses?page=bookmark"
        result = _driver().run(
            "courses",
            [
                _page([{"id": "1"}], next_url),
                _page([{"id": "2"}]),
            ],
        )

        assert result.raised is None
        assert result.saved_states == [CanvasLmsResumeConfig(next_url=next_url)]

    def test_resumes_from_saved_state(self):
        resume_url = f"{BASE_URL}/accounts/1/courses?page=resume"
        result = _driver().run(
            "courses", [_page([{"id": "9"}])], resume_state=CanvasLmsResumeConfig(next_url=resume_url)
        )

        assert result.raised is None
        assert result.requests[0].url.startswith(resume_url)
        assert [r["id"] for r in result.rows] == ["9"]

    def test_does_not_follow_next_url_on_foreign_host(self):
        result = _driver().run("courses", [_page([{"id": "1"}], "http://169.254.169.254/latest/meta-data/")])

        assert result.raised is None
        assert [r["id"] for r in result.rows] == ["1"]
        assert len(result.requests) == 1

    def test_ignores_resume_url_on_foreign_host(self):
        result = _driver().run(
            "courses",
            [_page([{"id": "1"}])],
            resume_state=CanvasLmsResumeConfig(next_url="http://169.254.169.254/latest/meta-data/"),
        )

        assert result.raised is None
        assert result.requests[0].path == "/api/v1/accounts/1/courses"
        assert [r["id"] for r in result.rows] == ["1"]

    def test_runtime_host_check_blocks_unsafe_domain(self):
        with patch.object(canvas_lms_module, "_is_host_safe", return_value=(False, "internal address")):
            result = _driver().run("courses", [])
        assert isinstance(result.raised, CanvasHostNotAllowedError)
        assert result.requests == []

    def test_users_endpoint_builds_correct_path(self):
        result = _driver().run("users", [_page([{"id": "1"}])])

        assert result.raised is None
        assert result.requests[0].path == "/api/v1/accounts/1/users"


class TestCanvasLmsFanout:
    def test_submissions_injects_course_id_from_parent(self):
        result = _driver().run(
            "submissions",
            [_page([{"id": "1000"}]), _page([{"assignment_id": "1", "user_id": "2"}])],
        )

        assert result.raised is None
        assert len(result.rows) == 1
        row = result.rows[0]
        assert row["course_id"] == "1000"
        assert "_courses_id" not in row

    def test_enrollments_fanout_pins_account_id_and_page_size_param(self):
        result = _driver(account_id="42").run(
            "enrollments", [_page([{"id": "7"}]), _page([{"id": "1", "course_id": "7"}])]
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/accounts/42/courses", "/api/v1/courses/7/enrollments"]
        assert result.params("per_page") == ["100", "100"]

    def test_submissions_incremental_maps_field_to_query_param(self):
        graded = _driver().run(
            "submissions",
            [
                _page([{"id": "7"}]),
                _page([{"assignment_id": "1", "user_id": "2", "graded_at": "2024-01-02T00:00:00Z"}]),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="graded_at",
        )
        submitted = _driver().run(
            "submissions",
            [
                _page([{"id": "7"}]),
                _page([{"assignment_id": "1", "user_id": "2", "submitted_at": "2024-01-02T00:00:00Z"}]),
            ],
            incremental_field="submitted_at",
        )

        assert graded.raised is None
        assert submitted.raised is None
        assert graded.requests[1].param("graded_since") == "2024-01-01T00:00:00Z"
        assert graded.requests[1].param("submitted_since") is None
        assert submitted.requests[1].param("submitted_since") == "1970-01-01T00:00:00Z"
        assert submitted.requests[1].param("graded_since") is None

    def test_fanout_seeds_resume_state_and_wires_hook(self):
        resume_url = f"{BASE_URL}/courses/2/enrollments?page=resume"
        result = _driver().run(
            "enrollments",
            [_page([{"id": "1"}, {"id": "2"}]), _page([{"id": "9", "course_id": "2"}])],
            resume_state=CanvasLmsResumeConfig(
                completed=["/courses/1/enrollments"],
                current="/courses/2/enrollments",
                child_state={"next_url": resume_url},
            ),
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/accounts/1/courses", "/api/v1/courses/2/enrollments"]
        assert result.requests[1].param("page") == "resume"
        assert result.saved_states[-1] == (
            CanvasLmsResumeConfig(
                completed=["/courses/1/enrollments", "/courses/2/enrollments"], current=None, child_state=None
            )
        )

    def test_fanout_does_not_load_state_when_cannot_resume(self):
        result = _driver().run("assignments", [_page([{"id": "2"}]), _page([{"id": "9"}])])

        assert result.raised is None
        assert result.paths == ["/api/v1/accounts/1/courses", "/api/v1/courses/2/assignments"]
        assert result.requests[1].param("page") is None

    def test_fanout_runtime_host_check_blocks_unsafe_domain(self):
        with patch.object(canvas_lms_module, "_is_host_safe", return_value=(False, "internal address")):
            result = _driver().run("assignments", [])
        assert isinstance(result.raised, CanvasHostNotAllowedError)
        assert result.requests == []
