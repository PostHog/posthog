from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.stytch.settings import ENDPOINTS, STYTCH_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.stytch.stytch import (
    StytchAPIError,
    StytchResumeConfig,
    base_url_for_project,
    build_users_search_body,
    check_endpoint_access,
    get_rows,
    stytch_source,
    validate_credentials,
)

MOCK_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.stytch.stytch.make_tracked_session"


def _make_manager(resume_state: StytchResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(payload: dict[str, Any], status_code: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = payload
    return response


def _search_page(data_key: str, items: list[dict[str, Any]], next_cursor: str | None) -> dict[str, Any]:
    return {data_key: items, "results_metadata": {"total": len(items), "next_cursor": next_cursor}}


class TestBaseUrl:
    @pytest.mark.parametrize(
        "project_id, expected",
        [
            ("project-live-11111111-1111-1111-1111-111111111111", "https://api.stytch.com"),
            ("project-test-11111111-1111-1111-1111-111111111111", "https://test.stytch.com"),
        ],
    )
    def test_environment_routing(self, project_id, expected):
        assert base_url_for_project(project_id) == expected


class TestBuildUsersSearchBody:
    @pytest.mark.parametrize(
        "value, expected_filter_value",
        [
            (datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05Z"),
            (datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05Z"),
            (date(2026, 1, 2), "2026-01-02T00:00:00Z"),
            ("2026-01-02T03:04:05Z", "2026-01-02T03:04:05Z"),
        ],
    )
    def test_incremental_body_uses_rfc3339_created_at_filter(self, value, expected_filter_value):
        body = build_users_search_body(should_use_incremental_field=True, db_incremental_field_last_value=value)
        assert body["query"] == {
            "operator": "AND",
            "operands": [{"filter_name": "created_at_greater_than", "filter_value": expected_filter_value}],
        }

    @pytest.mark.parametrize("should_use, last_value", [(False, datetime(2026, 1, 2, tzinfo=UTC)), (True, None)])
    def test_no_query_without_watermark(self, should_use, last_value):
        body = build_users_search_body(
            should_use_incremental_field=should_use, db_incremental_field_last_value=last_value
        )
        assert "query" not in body


class TestValidateCredentials:
    @mock.patch(MOCK_PATH)
    def test_consumer_project_valid(self, mock_session):
        mock_session.return_value.post.return_value = _response({}, 200)
        assert validate_credentials("project-live-x", "secret") is True
        # The consumer probe succeeding must short-circuit the B2B probe.
        assert mock_session.return_value.post.call_count == 1

    @mock.patch(MOCK_PATH)
    def test_b2b_project_valid_despite_consumer_surface_failing(self, mock_session):
        mock_session.return_value.post.side_effect = [_response({}, 400), _response({}, 200)]
        assert validate_credentials("project-live-x", "secret") is True

    @mock.patch(MOCK_PATH)
    def test_invalid_credentials(self, mock_session):
        mock_session.return_value.post.return_value = _response({"error_type": "unauthorized_credentials"}, 401)
        assert validate_credentials("project-live-x", "secret") is False

    @mock.patch(MOCK_PATH)
    def test_network_errors_swallowed(self, mock_session):
        mock_session.return_value.post.side_effect = Exception("boom")
        assert validate_credentials("project-live-x", "secret") is False


class TestGetRowsUsers:
    @mock.patch(MOCK_PATH)
    def test_paginates_via_body_cursor_and_saves_state_after_yield(self, mock_session):
        mock_session.return_value.request.side_effect = [
            _response(_search_page("results", [{"user_id": "u1"}, {"user_id": "u2"}], "cursor-2")),
            _response(_search_page("results", [{"user_id": "u3"}], None)),
        ]

        manager = _make_manager()
        batches = list(get_rows("project-live-x", "secret", "users", mock.MagicMock(), manager))

        assert [item["user_id"] for batch in batches for item in batch] == ["u1", "u2", "u3"]
        second_call = mock_session.return_value.request.call_args_list[1]
        assert second_call.kwargs["json"]["cursor"] == "cursor-2"
        # State saved only while a next page exists, so a completed run restarts cleanly.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].cursor == "cursor-2"

    @mock.patch(MOCK_PATH)
    def test_resumes_from_saved_cursor(self, mock_session):
        mock_session.return_value.request.return_value = _response(_search_page("results", [{"user_id": "u9"}], None))

        manager = _make_manager(StytchResumeConfig(cursor="cursor-5"))
        list(get_rows("project-live-x", "secret", "users", mock.MagicMock(), manager))

        first_call = mock_session.return_value.request.call_args_list[0]
        assert first_call.kwargs["json"]["cursor"] == "cursor-5"

    @mock.patch(MOCK_PATH)
    def test_incremental_filter_sent_on_every_page(self, mock_session):
        mock_session.return_value.request.side_effect = [
            _response(_search_page("results", [{"user_id": "u1"}], "cursor-2")),
            _response(_search_page("results", [{"user_id": "u2"}], None)),
        ]

        list(
            get_rows(
                "project-live-x",
                "secret",
                "users",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
            )
        )

        for call in mock_session.return_value.request.call_args_list:
            operands = call.kwargs["json"]["query"]["operands"]
            assert operands[0]["filter_name"] == "created_at_greater_than"

    @mock.patch(MOCK_PATH)
    def test_uses_test_host_for_test_project(self, mock_session):
        mock_session.return_value.request.return_value = _response(_search_page("results", [], None))

        list(get_rows("project-test-x", "secret", "users", mock.MagicMock(), _make_manager()))

        url = mock_session.return_value.request.call_args.args[1]
        assert url == "https://test.stytch.com/v1/users/search"

    @mock.patch(MOCK_PATH)
    def test_auth_error_raises_with_error_type(self, mock_session):
        mock_session.return_value.request.return_value = _response({"error_type": "invalid_secret_authentication"}, 401)

        with pytest.raises(StytchAPIError, match="error_type=invalid_secret_authentication"):
            list(get_rows("project-live-x", "secret", "users", mock.MagicMock(), _make_manager()))


class TestGetRowsSessions:
    @mock.patch(MOCK_PATH)
    def test_fans_out_one_sessions_request_per_user(self, mock_session):
        mock_session.return_value.request.side_effect = [
            _response(_search_page("results", [{"user_id": "u1"}, {"user_id": "u2"}], None)),
            _response({"sessions": [{"session_id": "s1", "user_id": "u1"}]}),
            _response({"sessions": [{"session_id": "s2", "user_id": "u2"}, {"session_id": "s3", "user_id": "u2"}]}),
        ]

        manager = _make_manager()
        batches = list(get_rows("project-live-x", "secret", "sessions", mock.MagicMock(), manager))

        assert [item["session_id"] for batch in batches for item in batch] == ["s1", "s2", "s3"]
        session_calls = [call for call in mock_session.return_value.request.call_args_list if call.args[0] == "GET"]
        assert [call.kwargs["params"]["user_id"] for call in session_calls] == ["u1", "u2"]
        manager.save_state.assert_not_called()

    @mock.patch(MOCK_PATH)
    def test_saves_users_cursor_between_pages(self, mock_session):
        mock_session.return_value.request.side_effect = [
            _response(_search_page("results", [{"user_id": "u1"}], "cursor-2")),
            _response({"sessions": [{"session_id": "s1", "user_id": "u1"}]}),
            _response(_search_page("results", [], None)),
        ]

        manager = _make_manager()
        list(get_rows("project-live-x", "secret", "sessions", mock.MagicMock(), manager))

        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].cursor == "cursor-2"


class TestGetRowsMembers:
    @mock.patch(MOCK_PATH)
    def test_fans_out_over_sorted_org_chunks(self, mock_session):
        mock_session.return_value.request.side_effect = [
            # Org enumeration returns unsorted ids across two pages.
            _response(_search_page("organizations", [{"organization_id": "org-b"}], "org-cursor-2")),
            _response(_search_page("organizations", [{"organization_id": "org-a"}], None)),
            _response(_search_page("members", [{"member_id": "m1"}], None)),
        ]

        batches = list(get_rows("project-live-x", "secret", "members", mock.MagicMock(), _make_manager()))

        assert [item["member_id"] for batch in batches for item in batch] == ["m1"]
        member_call = mock_session.return_value.request.call_args_list[2]
        assert member_call.kwargs["json"]["organization_ids"] == ["org-a", "org-b"]

    @mock.patch(MOCK_PATH)
    def test_resume_bookmark_skips_completed_chunks(self, mock_session):
        org_pages = [
            _response(
                _search_page(
                    "organizations",
                    [{"organization_id": f"org-{i}"} for i in range(150)],
                    None,
                )
            ),
            _response(_search_page("members", [{"member_id": "m-late"}], None)),
        ]
        mock_session.return_value.request.side_effect = org_pages

        # 150 sorted orgs chunk into [0..99] and [100..149]; the bookmark points at chunk two.
        sorted_ids = sorted(f"org-{i}" for i in range(150))
        manager = _make_manager(StytchResumeConfig(cursor="member-cursor-3", org_bookmark=sorted_ids[100]))
        list(get_rows("project-live-x", "secret", "members", mock.MagicMock(), manager))

        member_calls = [
            call
            for call in mock_session.return_value.request.call_args_list
            if call.args[1].endswith("/members/search")
        ]
        assert len(member_calls) == 1
        assert member_calls[0].kwargs["json"]["organization_ids"] == sorted_ids[100:]
        assert member_calls[0].kwargs["json"]["cursor"] == "member-cursor-3"


class TestStytchSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = STYTCH_ENDPOINTS[endpoint]
        response = stytch_source("project-live-x", "secret", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Stytch search ordering is undocumented, so the watermark must only persist at job end.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(STYTCH_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "created_at"


class TestHttpSampleCaptureDisabled:
    """Stytch responses carry end-user PII, so every credentialed request path must build its
    tracked session with capture disabled and the secret redacted — reverting either leaks PII
    into the shared HTTP sample bucket."""

    def _drive_validate(self, session: mock.MagicMock) -> None:
        session.post.return_value = _response({}, 200)
        validate_credentials("project-live-x", "secret")

    def _drive_check_access(self, session: mock.MagicMock) -> None:
        session.post.return_value = _response({}, 200)
        check_endpoint_access("project-live-x", "secret", "/v1/users/search")

    def _drive_get_rows(self, session: mock.MagicMock) -> None:
        session.request.return_value = _response(_search_page("results", [], None))
        list(get_rows("project-live-x", "secret", "users", mock.MagicMock(), _make_manager()))

    @pytest.mark.parametrize("driver", ["_drive_validate", "_drive_check_access", "_drive_get_rows"])
    @mock.patch(MOCK_PATH)
    def test_credentialed_paths_disable_capture_and_redact_secret(self, mock_session, driver):
        getattr(self, driver)(mock_session.return_value)

        mock_session.assert_called_with(capture=False, redact_values=("secret",))
