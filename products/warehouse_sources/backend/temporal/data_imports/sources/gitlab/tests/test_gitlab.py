from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.gitlab import gitlab as gitlab_module
from products.warehouse_sources.backend.temporal.data_imports.sources.gitlab.gitlab import (
    HOST_NOT_ALLOWED_ERROR,
    GitLabResumeConfig,
    _build_initial_params,
    _build_initial_url,
    _format_incremental_value,
    _get_headers,
    _parse_next_url,
    get_rows,
    gitlab_source,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitlab.settings import GITLAB_ENDPOINTS


def _response(
    *, status_code: int = 200, json_data: Any = None, link: Optional[str] = None, text: str = ""
) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (301, 302, 303, 307, 308)
    response.is_permanent_redirect = status_code in (301, 308)
    response.text = text
    response.json.return_value = json_data
    response.headers = {"Link": link} if link else {}
    return response


class _FakeBatcher:
    """Yields whatever is buffered on every ``should_yield`` check, so the per-item save_state
    path in ``get_rows`` is exercised without needing thousands of rows."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._buf: list[Any] = []

    def batch(self, item: Any) -> None:
        self._buf.append(item)

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        return len(self._buf) > 0

    def get_table(self) -> list[Any]:
        rows, self._buf = self._buf, []
        return rows


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, "https://gitlab.com"),
            ("", "https://gitlab.com"),
            ("gitlab.com", "https://gitlab.com"),
            ("https://gitlab.com", "https://gitlab.com"),
            ("https://gitlab.com/", "https://gitlab.com"),
            ("  gitlab.example.com  ", "https://gitlab.example.com"),
            ("https://gitlab.example.com/api/v4", "https://gitlab.example.com"),
            ("http://gitlab.example.com:8080/api/v4/", "http://gitlab.example.com:8080"),
        ],
    )
    def test_normalize_host(self, raw, expected):
        assert normalize_host(raw) == expected


class TestGetHeaders:
    def test_uses_authorization_bearer_not_private_token(self):
        # The token must ride the `Authorization` header so the tracked transport's sample scrubber
        # redacts it; `PRIVATE-TOKEN` is not on the scrubber's denylist and would leak the token.
        headers = _get_headers("glpat-secret")
        assert headers["Authorization"] == "Bearer glpat-secret"
        assert "PRIVATE-TOKEN" not in headers


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_incremental_value(value) == expected


class TestBuildInitialParams:
    def test_unsupported_incremental_field_raises(self):
        with pytest.raises(ValueError):
            _build_initial_params(
                GITLAB_ENDPOINTS["issues"],
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
                incremental_field="merged_at",
            )


class TestBuildInitialUrl:
    def test_builds_url_without_params(self):
        url = _build_initial_url("gitlab.example.com", GITLAB_ENDPOINTS["branches"], "42", {})
        assert url == "https://gitlab.example.com/api/v4/projects/42/repository/branches"


class TestParseNextUrl:
    @pytest.mark.parametrize(
        "header, expected",
        [
            ("", None),
            ('<https://gitlab.com/api/v4/projects/1/issues?page=1>; rel="first"', None),
            (
                '<https://gitlab.com/api/v4/projects/1/issues?page=2>; rel="next", '
                '<https://gitlab.com/api/v4/projects/1/issues?page=1>; rel="first"',
                "https://gitlab.com/api/v4/projects/1/issues?page=2",
            ),
        ],
    )
    def test_parse(self, header, expected):
        assert _parse_next_url(header) == expected


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(gitlab_module, "make_tracked_session", return_value=session)

    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_msg_substr",
        [
            (200, True, None),
            (401, False, "Invalid GitLab personal access token"),
            # A 404 can't tell a missing project from one the token can't see, so the message has to
            # carry the next step rather than dead-ending on "not accessible".
            (404, False, "not accessible with this token. Check the spelling and that your token has read access"),
        ],
    )
    def test_status_code_mapping(self, status_code, expected_valid, expected_msg_substr):
        with self._patch_session(_response(status_code=status_code)):
            valid, msg = validate_credentials("https://gitlab.com", "tok", "group/project")
            assert valid is expected_valid
            if expected_msg_substr is None:
                assert msg is None
            else:
                assert expected_msg_substr in (msg or "")

    def test_403_maps_to_scope_guidance_without_echoing_raw_body(self):
        # GitLab answers an under-scoped token with a raw OAuth JSON body that has no "message" field;
        # it must be replaced with actionable scope guidance, never echoed back verbatim.
        body = {"error": "insufficient_scope", "error_description": "requires higher privileges"}
        with self._patch_session(_response(status_code=403, json_data=body, text=str(body))):
            valid, msg = validate_credentials("https://gitlab.com", "tok", "group/project")
            assert valid is False
            assert "read_api" in (msg or "")
            assert "insufficient_scope" not in (msg or "")

    def test_unmapped_error_does_not_echo_raw_response_body(self):
        with self._patch_session(_response(status_code=500, json_data={}, text="<html>internal details</html>")):
            valid, msg = validate_credentials("https://gitlab.com", "tok", "group/project")
            assert valid is False
            assert "internal details" not in (msg or "")
            assert "HTTP 500" in (msg or "")

    @pytest.mark.parametrize(
        "host, token, project, expected_msg",
        [
            ("https://gitlab.com", "", "group/project", "Missing personal access token"),
            ("https://gitlab.com", "tok", "  ", "Missing project id or path"),
        ],
    )
    def test_missing_inputs_short_circuit(self, host, token, project, expected_msg):
        valid, msg = validate_credentials(host, token, project)
        assert valid is False
        assert msg == expected_msg

    @pytest.mark.parametrize(
        "project",
        [
            "https://gitlab.com/mygroup/",  # pasted URL naming a group rather than a project
            "mygroup",  # bare group, no project and not a numeric id
            "some-dashboard",  # bare name
            "/myproject",  # leading slash: encodes to an empty group segment
            "mygroup/",  # trailing slash: encodes to an empty project segment
            "mygroup//myproject",  # doubled slash: encodes to an empty middle segment
        ],
    )
    def test_malformed_project_gets_format_guidance(self, project):
        # Guards the pre-request format check: without it these URL-encode into a nonsense path,
        # 404, and get the misleading "not found or not accessible" message.
        valid, msg = validate_credentials("https://gitlab.com", "tok", project)
        assert valid is False
        assert "group/project" in (msg or "")

    @pytest.mark.parametrize(
        "project",
        [
            "https://gitlab.com/mygroup/myproject",
            "https://gitlab.com/mygroup/myproject/-/issues",
            "https://gitlab.com/mygroup/myproject.git",
        ],
    )
    def test_pasted_project_url_reaches_the_api(self, project):
        # The URL names the project unambiguously, so it must resolve rather than dead-end on the
        # format check.
        with self._patch_session(_response(status_code=200)) as patched:
            valid, _ = validate_credentials("https://gitlab.com", "tok", project)
            assert valid is True
            assert patched.return_value.get.call_args.args[0].endswith("/projects/mygroup%2Fmyproject")

    def test_numeric_project_id_is_not_rejected_as_malformed(self):
        # A bare numeric id is a valid GitLab project reference, so it must reach the API rather
        # than trip the format check for bare names.
        with self._patch_session(_response(status_code=200)) as patched:
            valid, _ = validate_credentials("https://gitlab.com", "tok", "114682853")
            assert valid is True
            patched.return_value.get.assert_called_once()

    def test_request_exception_returns_failure(self):
        import requests

        with self._patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials("https://gitlab.com", "tok", "group/project")
            assert valid is False
            assert "boom" in (msg or "")

    def test_rejects_redirect_response(self):
        with self._patch_session(_response(status_code=302)) as patched:
            valid, msg = validate_credentials("https://gitlab.com", "tok", "group/project")
            assert valid is False
            assert "unexpected redirect" in (msg or "")
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(gitlab_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(_response(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("https://10.0.0.1", "tok", "group/project", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()

    @pytest.mark.parametrize("host", ["http://gitlab.example.com", "http://gitlab.example.com:8080/api/v4"])
    def test_rejects_plaintext_http(self, host):
        # The token rides the Authorization header, so a plaintext HTTP host must be refused before
        # any request is issued.
        with self._patch_session(_response(status_code=200)) as patched:
            valid, msg = validate_credentials(host, "tok", "group/project")
            assert valid is False
            assert msg == gitlab_module.HTTP_NOT_ALLOWED_ERROR
            patched.return_value.get.assert_not_called()


class TestGitLabSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_keys, partition_key, sort_mode",
        [
            ("issues", ["id"], "created_at", "asc"),
            ("merge_requests", ["id"], "created_at", "asc"),
            ("commits", ["id"], "created_at", "desc"),
            ("pipelines", ["id"], "created_at", "asc"),
            ("releases", ["tag_name"], "created_at", "asc"),
            ("milestones", ["id"], "created_at", "asc"),
            ("branches", ["name"], None, "asc"),
            ("tags", ["name"], None, "asc"),
            ("labels", ["id"], None, "asc"),
            ("members", ["id"], None, "asc"),
            ("issue_notes", ["issue_iid", "id"], "created_at", "desc"),
            ("merge_request_state_events", ["merge_request_iid", "id"], "created_at", "desc"),
        ],
    )
    def test_response_shape(self, endpoint, primary_keys, partition_key, sort_mode):
        response = gitlab_source(
            host="https://gitlab.com",
            personal_access_token="tok",
            project="group/project",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
            team_id=1,
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None


class TestGetRows:
    def _run(self, manager, responses, endpoint="issues", **kwargs):
        session = mock.MagicMock()
        session.get.side_effect = responses
        with (
            mock.patch.object(gitlab_module, "make_tracked_session", return_value=session),
            mock.patch.object(gitlab_module, "Batcher", _FakeBatcher),
        ):
            rows: list[Any] = []
            for table in get_rows(
                host="https://gitlab.com",
                personal_access_token="tok",
                project="group/project",
                endpoint=endpoint,
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                team_id=1,
                **kwargs,
            ):
                rows.extend(table)
        return rows, session

    def test_resumes_from_saved_state(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = GitLabResumeConfig(
            next_url="https://gitlab.com/api/v4/projects/1/issues?page=5"
        )
        rows, session = self._run(manager, [_response(json_data=[{"id": 9}])])

        first_url = session.get.call_args_list[0].args[0]
        assert first_url == "https://gitlab.com/api/v4/projects/1/issues?page=5"
        assert [r["id"] for r in rows] == [9]

    def test_fan_out_bounds_parent_walk_and_tags_children_with_parent_iid(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        parents = _response(json_data=[{"iid": 7}, {"iid": 8}, {"iid": 9}])
        notes_7 = _response(json_data=[{"id": 70}])
        deleted_parent = _response(status_code=404)
        notes_9 = _response(json_data=[{"id": 90}, {"id": 91}])
        rows, session = self._run(
            manager,
            [parents, notes_7, deleted_parent, notes_9],
            endpoint="issue_notes",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="created_at",
        )

        urls = [call.args[0] for call in session.get.call_args_list]
        assert urls[0] == (
            "https://gitlab.com/api/v4/projects/group%2Fproject/issues"
            "?per_page=100&updated_after=2024-01-01T00%3A00%3A00Z&order_by=updated_at&sort=asc"
        )
        assert urls[1].startswith("https://gitlab.com/api/v4/projects/group%2Fproject/issues/7/notes?")
        assert urls[3].startswith("https://gitlab.com/api/v4/projects/group%2Fproject/issues/9/notes?")
        assert [(r["issue_iid"], r["id"]) for r in rows] == [(7, 70), (9, 90), (9, 91)]
        saved = manager.save_state.call_args.args[0]
        assert saved.next_url == urls[0]

    def test_fan_out_stops_child_pagination_at_page_cap(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        parents = _response(json_data=[{"iid": 1}])
        child_page = _response(
            json_data=[{"id": 1}],
            link='<https://gitlab.com/api/v4/projects/1/issues/1/notes?page=2>; rel="next"',
        )
        with mock.patch.object(gitlab_module, "MAX_PAGES_PER_PARENT", 2):
            _rows, session = self._run(manager, [parents, child_page, child_page], endpoint="issue_notes")

        assert session.get.call_count == 3

    def test_fan_out_flushes_sparse_rows_so_later_empty_parents_reach_a_safe_point(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        parents = _response(json_data=[{"iid": 1}, {"iid": 2}, {"iid": 3}])
        responses = [parents, _response(json_data=[{"id": 10}]), _response(json_data=[]), _response(json_data=[])]
        session = mock.MagicMock()
        session.get.side_effect = responses
        batcher = gitlab_module.Batcher(logger=mock.MagicMock(), chunk_size=2000)
        with (
            mock.patch.object(gitlab_module, "make_tracked_session", return_value=session),
            mock.patch.object(gitlab_module, "Batcher", return_value=batcher),
            mock.patch.object(gitlab_module, "PARTIAL_FLUSH_INTERVAL_SECONDS", 0.0),
        ):
            tables = list(
                get_rows(
                    host="https://gitlab.com",
                    personal_access_token="tok",
                    project="group/project",
                    endpoint="issue_state_events",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    team_id=1,
                )
            )

        assert [table.num_rows for table in tables] == [1]
        assert manager.save_state.call_args.args[0].next_url == session.get.call_args_list[0].args[0]
        assert manager.safe_point.call_count == 2

    def test_does_not_follow_next_url_on_foreign_host(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        page1 = _response(
            json_data=[{"id": 1}],
            link='<http://169.254.169.254/latest/meta-data/>; rel="next"',
        )
        rows, session = self._run(manager, [page1])

        assert [r["id"] for r in rows] == [1]
        assert session.get.call_count == 1

    def test_ignores_resume_url_on_foreign_host(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = GitLabResumeConfig(next_url="http://169.254.169.254/latest/meta-data/")
        rows, session = self._run(manager, [_response(json_data=[{"id": 1}])])

        first_url = session.get.call_args_list[0].args[0]
        assert first_url.startswith("https://gitlab.com/api/v4/projects/group%2Fproject/issues")
        assert [r["id"] for r in rows] == [1]

    def test_ignores_plaintext_resume_url_on_same_host(self):
        # A saved resume URL that downgraded to http must be ignored in favour of the https initial URL.
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = GitLabResumeConfig(
            next_url="http://gitlab.com/api/v4/projects/1/issues?page=5"
        )
        rows, session = self._run(manager, [_response(json_data=[{"id": 1}])])

        first_url = session.get.call_args_list[0].args[0]
        assert first_url.startswith("https://gitlab.com/api/v4/projects/group%2Fproject/issues")
        assert [r["id"] for r in rows] == [1]

    def test_does_not_follow_redirects(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        with pytest.raises(gitlab_module.GitLabHostNotAllowedError) as exc:
            self._run(manager, [_response(status_code=302)])
        # Message carries the non-retryable marker so the workflow fails fast on SSRF/redirect.
        assert HOST_NOT_ALLOWED_ERROR in str(exc.value)

    def test_unsafe_host_error_is_marked_non_retryable(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        with (
            mock.patch.object(gitlab_module, "_is_host_safe", return_value=(False, "internal address")),
            pytest.raises(gitlab_module.GitLabHostNotAllowedError) as exc,
        ):
            self._run(manager, [_response(json_data=[{"id": 1}])])
        assert HOST_NOT_ALLOWED_ERROR in str(exc.value)

    def test_rejects_plaintext_http_before_request(self):
        # A plaintext HTTP host must be refused at run time (host could have been edited after
        # source creation) before the token-bearing request goes out.
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        session = mock.MagicMock()
        with (
            mock.patch.object(gitlab_module, "make_tracked_session", return_value=session),
            mock.patch.object(gitlab_module, "Batcher", _FakeBatcher),
            pytest.raises(gitlab_module.GitLabHostNotAllowedError) as exc,
        ):
            list(
                get_rows(
                    host="http://gitlab.example.com",
                    personal_access_token="tok",
                    project="group/project",
                    endpoint="issues",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    team_id=1,
                )
            )
        assert gitlab_module.HTTP_NOT_ALLOWED_ERROR in str(exc.value)
        session.get.assert_not_called()

    def test_passes_allow_redirects_false(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        _rows, session = self._run(manager, [_response(json_data=[{"id": 1}])])
        assert session.get.call_args.kwargs["allow_redirects"] is False


class TestRetryAfter:
    @pytest.mark.parametrize(
        "header, expected",
        [
            ({"Retry-After": "5"}, 5.0),
            ({"Retry-After": "  9 "}, 9.0),
            ({"Retry-After": "100000"}, 60.0),  # capped
            ({"Retry-After": "Wed, 21 Oct 2025 07:28:00 GMT"}, None),  # HTTP-date ignored
            ({}, None),
        ],
    )
    def test_parse_retry_after(self, header, expected):
        from products.warehouse_sources.backend.temporal.data_imports.sources.gitlab.gitlab import _parse_retry_after

        response = mock.MagicMock()
        response.headers = header
        assert _parse_retry_after(response) == expected

    def test_retry_wait_prefers_retry_after(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.gitlab.gitlab import (
            GitLabRetryableError,
            _retry_wait,
        )

        state = mock.MagicMock()
        state.outcome.exception.return_value = GitLabRetryableError("rate limited", retry_after=7.0)
        assert _retry_wait(state) == 7.0
