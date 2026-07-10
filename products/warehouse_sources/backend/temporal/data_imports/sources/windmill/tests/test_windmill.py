from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.settings import (
    ENDPOINTS,
    WINDMILL_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill import (
    PER_PAGE,
    WindmillHostNotAllowedError,
    WindmillResumeConfig,
    _build_params,
    _format_after,
    _workspace_url,
    get_rows,
    normalize_base_url,
    validate_credentials,
    windmill_source,
)

BASE_URL = "https://app.windmill.dev"
WORKSPACE = "my-workspace"


def _make_manager(resume_state: WindmillResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: Any, status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 400
    return resp


def _page(n: int) -> list[dict[str, Any]]:
    return [{"id": str(i)} for i in range(n)]


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://app.windmill.dev", "https://app.windmill.dev/api"),
            ("https://app.windmill.dev/", "https://app.windmill.dev/api"),
            # A user pasting the full API root must not produce /api/api.
            ("https://app.windmill.dev/api", "https://app.windmill.dev/api"),
            ("https://app.windmill.dev/api/", "https://app.windmill.dev/api"),
            # Plaintext is upgraded to https; a scheme-less host gets one.
            ("http://windmill.internal.example.com", "https://windmill.internal.example.com/api"),
            ("windmill.example.com", "https://windmill.example.com/api"),
            ("  https://app.windmill.dev  ", "https://app.windmill.dev/api"),
        ],
    )
    def test_normalizes(self, value, expected):
        assert normalize_base_url(value) == expected


class TestWorkspaceUrl:
    def test_builds_workspace_scoped_path(self):
        assert (
            _workspace_url(BASE_URL, WORKSPACE, "/jobs/completed/list")
            == "https://app.windmill.dev/api/w/my-workspace/jobs/completed/list"
        )

    def test_url_encodes_workspace(self):
        # A workspace id with a slash must not escape the /w/ path segment.
        assert "/w/a%2Fb/" in _workspace_url(BASE_URL, "a/b", "/users/list")


class TestFormatAfter:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            (date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_after(value) == expected


class TestBuildParams:
    def test_paginated_endpoint_sends_page_and_order(self):
        params = _build_params(WINDMILL_ENDPOINTS["completed_jobs"], page=2, incremental_field=None, after_value=None)
        assert params["page"] == 2
        assert params["per_page"] == PER_PAGE
        # Ascending so mid-sync inserts don't shift already-walked pages.
        assert params["order_desc"] == "false"

    def test_unpaginated_endpoint_omits_page_params(self):
        params = _build_params(WINDMILL_ENDPOINTS["users"], page=1, incremental_field=None, after_value=None)
        assert "page" not in params
        assert "per_page" not in params
        assert "order_desc" not in params

    @pytest.mark.parametrize(
        "incremental_field, expected_param",
        [("created_at", "created_after"), ("started_at", "started_after")],
    )
    def test_incremental_field_maps_to_after_param(self, incremental_field, expected_param):
        params = _build_params(
            WINDMILL_ENDPOINTS["completed_jobs"],
            page=1,
            incremental_field=incremental_field,
            after_value="2026-01-01T00:00:00+00:00",
        )
        assert params[expected_param] == "2026-01-01T00:00:00+00:00"

    def test_after_value_ignored_for_full_refresh_endpoint(self):
        # scripts has no server-side timestamp filter, so a cutoff must never leak into params.
        params = _build_params(
            WINDMILL_ENDPOINTS["scripts"],
            page=1,
            incremental_field="created_at",
            after_value="2026-01-01T00:00:00+00:00",
        )
        assert "created_after" not in params
        assert "started_after" not in params


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Windmill API token"),
            (403, False, "Could not access Windmill workspace 'my-workspace' with this token"),
            (404, False, "Could not access Windmill workspace 'my-workspace' with this token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill.make_tracked_session"
    )
    def test_status_mapping(self, mock_session, status_code, expected_valid, expected_message):
        mock_session.return_value.get.return_value = _response({"message": "x"}, status_code=status_code)

        valid, message = validate_credentials("token", BASE_URL, WORKSPACE)

        assert valid is expected_valid
        assert message == expected_message

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill.make_tracked_session"
    )
    def test_uses_no_redirect_session(self, mock_session):
        mock_session.return_value.get.return_value = _response({}, status_code=200)
        validate_credentials("token", BASE_URL, WORKSPACE)
        assert mock_session.call_args.kwargs["allow_redirects"] is False

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill.make_tracked_session"
    )
    def test_swallows_request_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
        valid, message = validate_credentials("token", BASE_URL, WORKSPACE)
        assert valid is False
        assert message == "boom"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill._is_host_safe")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill.make_tracked_session"
    )
    def test_blocks_internal_host_when_team_id_given(self, mock_session, mock_host_safe):
        mock_host_safe.return_value = (False, "host not allowed")

        valid, message = validate_credentials("token", "https://10.0.0.1", WORKSPACE, team_id=42)

        assert valid is False
        assert message == "host not allowed"
        mock_session.return_value.get.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill._is_host_safe")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill.make_tracked_session"
    )
    def test_skips_host_check_when_team_id_omitted(self, mock_session, mock_host_safe):
        mock_session.return_value.get.return_value = _response({}, status_code=200)
        validate_credentials("token", BASE_URL, WORKSPACE)
        mock_host_safe.assert_not_called()


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill.make_tracked_session"
    )
    def test_walks_pages_until_short_page(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(_page(PER_PAGE)),
            _response(_page(3)),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", BASE_URL, WORKSPACE, "completed_jobs", mock.MagicMock(), manager, team_id=1))

        assert [len(b) for b in batches] == [PER_PAGE, 3]
        pages = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert "page=1" in pages[0]
        assert "page=2" in pages[1]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill.make_tracked_session"
    )
    def test_stops_on_empty_full_page_boundary(self, mock_session):
        # A full final page is followed by one more request that comes back empty.
        mock_session.return_value.get.side_effect = [
            _response(_page(PER_PAGE)),
            _response([]),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", BASE_URL, WORKSPACE, "completed_jobs", mock.MagicMock(), manager, team_id=1))

        assert [len(b) for b in batches] == [PER_PAGE]
        assert mock_session.return_value.get.call_count == 2

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill.make_tracked_session"
    )
    def test_empty_first_page_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        batches = list(get_rows("token", BASE_URL, WORKSPACE, "completed_jobs", mock.MagicMock(), manager, team_id=1))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill.make_tracked_session"
    )
    def test_unpaginated_endpoint_makes_single_request(self, mock_session):
        # listUsers ignores page params, so paging would loop forever on the same full list.
        mock_session.return_value.get.return_value = _response([{"email": "a@x.com"}, {"email": "b@x.com"}])

        manager = _make_manager()
        batches = list(get_rows("token", BASE_URL, WORKSPACE, "users", mock.MagicMock(), manager, team_id=1))

        assert mock_session.return_value.get.call_count == 1
        assert [item["email"] for batch in batches for item in batch] == ["a@x.com", "b@x.com"]
        manager.save_state.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill.make_tracked_session"
    )
    def test_saves_current_page_after_each_yield(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(_page(PER_PAGE)),
            _response(_page(PER_PAGE)),
            _response(_page(1)),
        ]

        manager = _make_manager()
        list(get_rows("token", BASE_URL, WORKSPACE, "completed_jobs", mock.MagicMock(), manager, team_id=1))

        saved = [call.args[0].page for call in manager.save_state.call_args_list]
        assert saved == [1, 2, 3]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill.make_tracked_session"
    )
    def test_resumes_from_saved_page(self, mock_session):
        mock_session.return_value.get.side_effect = [_response(_page(2))]

        manager = _make_manager(WindmillResumeConfig(page=7))
        list(get_rows("token", BASE_URL, WORKSPACE, "completed_jobs", mock.MagicMock(), manager, team_id=1))

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "page=7" in first_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill.make_tracked_session"
    )
    def test_incremental_applies_after_filter(self, mock_session):
        mock_session.return_value.get.side_effect = [_response(_page(1))]

        manager = _make_manager()
        list(
            get_rows(
                "token",
                BASE_URL,
                WORKSPACE,
                "completed_jobs",
                mock.MagicMock(),
                manager,
                team_id=1,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field="started_at",
            )
        )

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "started_after=2026-01-01" in first_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill.make_tracked_session"
    )
    def test_full_refresh_endpoint_never_sends_after_filter(self, mock_session):
        mock_session.return_value.get.side_effect = [_response(_page(1))]

        manager = _make_manager()
        list(
            get_rows(
                "token",
                BASE_URL,
                WORKSPACE,
                "scripts",
                mock.MagicMock(),
                manager,
                team_id=1,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field="created_at",
            )
        )

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "after=" not in first_url

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill._is_host_safe")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill.make_tracked_session"
    )
    def test_raises_when_host_not_allowed(self, mock_session, mock_host_safe):
        mock_host_safe.return_value = (False, "host not allowed")

        manager = _make_manager()
        with pytest.raises(WindmillHostNotAllowedError):
            list(
                get_rows(
                    "token", "https://10.0.0.1", WORKSPACE, "completed_jobs", mock.MagicMock(), manager, team_id=42
                )
            )

        mock_session.return_value.get.assert_not_called()


class TestWindmillSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = WINDMILL_ENDPOINTS[endpoint]
        response = windmill_source("token", BASE_URL, WORKSPACE, endpoint, mock.MagicMock(), _make_manager(), team_id=1)

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(WINDMILL_ENDPOINTS.values()))
    def test_partition_keys_are_stable_fields(self, config):
        # Partition keys must be immutable creation timestamps, never edited/last-* fields.
        if config.partition_key:
            assert config.partition_key in {"created_at", "timestamp"}
