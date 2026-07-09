from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.anthropic import (
    AnthropicResumeConfig,
    _build_url,
    _compute_starting_at,
    _flatten_report_buckets,
    _to_start_datetime,
    anthropic_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.settings import (
    ANTHROPIC_ENDPOINTS,
    ENDPOINTS,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.anthropic"


def _make_manager(resume_state: AnthropicResumeConfig | None = None) -> mock.MagicMock:
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


def _entity_page(items: list[dict[str, Any]], has_more: bool = False, last_id: Optional[str] = None) -> dict[str, Any]:
    return {"data": items, "has_more": has_more, "first_id": None, "last_id": last_id}


def _report_page(
    buckets: list[dict[str, Any]], has_more: bool = False, next_page: Optional[str] = None
) -> dict[str, Any]:
    return {"data": buckets, "has_more": has_more, "next_page": next_page}


def _requested_urls(mock_session: mock.MagicMock) -> list[str]:
    return [call.args[0] for call in mock_session.return_value.get.call_args_list]


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


class TestHelpers:
    @parameterized.expand(
        [
            ("none", None, None),
            ("aware_datetime", datetime(2026, 7, 1, 12, 0, tzinfo=UTC), datetime(2026, 7, 1, 12, 0, tzinfo=UTC)),
            ("naive_datetime", datetime(2026, 7, 1, 12, 0), datetime(2026, 7, 1, 12, 0, tzinfo=UTC)),
            ("date", date(2026, 7, 1), datetime(2026, 7, 1, tzinfo=UTC)),
            ("iso_z_string", "2026-07-01T12:00:00Z", datetime(2026, 7, 1, 12, 0, tzinfo=UTC)),
            ("iso_offset_string", "2026-07-01T12:00:00+00:00", datetime(2026, 7, 1, 12, 0, tzinfo=UTC)),
            ("garbage_string", "not-a-date", None),
            ("int", 12345, None),
        ]
    )
    def test_to_start_datetime(self, _name, value, expected):
        assert _to_start_datetime(value) == expected

    def test_compute_starting_at_defaults_on_first_sync(self):
        assert _compute_starting_at(None) == "2023-01-01T00:00:00Z"

    def test_compute_starting_at_applies_lookback_and_floors_to_midnight(self):
        assert _compute_starting_at("2026-07-08T15:30:00Z") == "2026-07-07T00:00:00Z"

    def test_compute_starting_at_never_predates_default(self):
        assert _compute_starting_at("2022-06-01T00:00:00Z") == "2023-01-01T00:00:00Z"

    def test_build_url_drops_none_values(self):
        url = _build_url("/v1/organizations/users", {"limit": 500, "after_id": None})
        assert url == "https://api.anthropic.com/v1/organizations/users?limit=500"

    def test_build_url_no_params(self):
        assert _build_url("/v1/organizations/users", {}) == "https://api.anthropic.com/v1/organizations/users"

    def test_build_url_expands_group_by_list(self):
        url = _build_url("/v1/organizations/cost_report", {"group_by[]": ["workspace_id", "description"]})
        assert _query(url)["group_by[]"] == ["workspace_id", "description"]

    def test_flatten_report_buckets_builds_rows_with_synthetic_id(self):
        config = ANTHROPIC_ENDPOINTS["cost_report"]
        buckets = [
            {
                "starting_at": "2026-07-01T00:00:00Z",
                "ending_at": "2026-07-02T00:00:00Z",
                "results": [
                    {
                        "amount": "123.45",
                        "currency": "USD",
                        "workspace_id": "wrkspc_1",
                        "description": "Claude Sonnet 4.5 Usage - Input Tokens",
                        "cost_type": "tokens",
                        "model": "claude-sonnet-4-5",
                        "service_tier": "standard",
                        "token_type": "uncached_input_tokens",
                        "context_window": "0-200k",
                        "inference_geo": "global",
                    },
                ],
            },
        ]

        rows = _flatten_report_buckets(buckets, config)

        assert len(rows) == 1
        row = rows[0]
        assert row["bucket_starting_at"] == "2026-07-01T00:00:00Z"
        assert row["bucket_ending_at"] == "2026-07-02T00:00:00Z"
        assert row["amount"] == "123.45"
        assert row["id"].startswith("2026-07-01T00:00:00Z|wrkspc_1|Claude Sonnet 4.5 Usage - Input Tokens|tokens")

    def test_flatten_report_buckets_distinguishes_rows_in_same_bucket(self):
        config = ANTHROPIC_ENDPOINTS["usage_report"]
        bucket = {
            "starting_at": "2026-07-01T00:00:00Z",
            "ending_at": "2026-07-02T00:00:00Z",
            "results": [
                {"model": "claude-sonnet-4-5", "workspace_id": "wrkspc_1", "output_tokens": 10},
                {"model": "claude-opus-4-6", "workspace_id": "wrkspc_1", "output_tokens": 20},
            ],
        }

        rows = _flatten_report_buckets([bucket], config)

        assert len(rows) == 2
        assert rows[0]["id"] != rows[1]["id"]

    def test_flatten_report_buckets_skips_empty_buckets(self):
        config = ANTHROPIC_ENDPOINTS["usage_report"]
        buckets = [{"starting_at": "2026-07-01T00:00:00Z", "ending_at": "2026-07-02T00:00:00Z", "results": []}]
        assert _flatten_report_buckets(buckets, config) == []


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_validate_credentials_status_mapping(self, _name, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code

        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = response
            assert validate_credentials("sk-ant-admin-test") is expected

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("sk-ant-admin-test") is False

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_validate_credentials_sends_admin_headers(self, mock_session):
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        validate_credentials("sk-ant-admin-test")

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["x-api-key"] == "sk-ant-admin-test"
        assert headers["anthropic-version"] == "2023-06-01"


class TestEntityEndpoints:
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_paginates_with_after_id_and_saves_state_after_each_page(self, mock_session):
        manager = _make_manager()
        mock_session.return_value.get.side_effect = [
            _response(_entity_page([{"id": "user_1"}], has_more=True, last_id="user_1")),
            _response(_entity_page([{"id": "user_2"}], has_more=False, last_id="user_2")),
        ]

        batches = list(get_rows("key", "users", mock.MagicMock(), manager))

        assert batches == [[{"id": "user_1"}], [{"id": "user_2"}]]
        urls = _requested_urls(mock_session)
        assert "after_id" not in _query(urls[0])
        assert _query(urls[1])["after_id"] == ["user_1"]
        # State is only saved when there is another page to fetch.
        manager.save_state.assert_called_once_with(AnthropicResumeConfig(after_id="user_1"))

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_resumes_entity_list_from_saved_cursor(self, mock_session):
        manager = _make_manager(AnthropicResumeConfig(after_id="user_5"))
        mock_session.return_value.get.side_effect = [
            _response(_entity_page([{"id": "user_6"}], has_more=False, last_id="user_6")),
        ]

        batches = list(get_rows("key", "users", mock.MagicMock(), manager))

        assert batches == [[{"id": "user_6"}]]
        assert _query(_requested_urls(mock_session)[0])["after_id"] == ["user_5"]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_workspaces_requests_archived_workspaces(self, mock_session):
        manager = _make_manager()
        mock_session.return_value.get.side_effect = [
            _response(_entity_page([{"id": "wrkspc_1"}], has_more=False, last_id="wrkspc_1")),
        ]

        list(get_rows("key", "workspaces", mock.MagicMock(), manager))

        assert _query(_requested_urls(mock_session)[0])["include_archived"] == ["true"]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_empty_list_yields_no_batches(self, mock_session):
        manager = _make_manager()
        mock_session.return_value.get.side_effect = [_response(_entity_page([], has_more=False))]

        assert list(get_rows("key", "invites", mock.MagicMock(), manager)) == []

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_stops_when_has_more_but_no_last_id(self, mock_session):
        manager = _make_manager()
        mock_session.return_value.get.side_effect = [
            _response(_entity_page([{"id": "user_1"}], has_more=True, last_id=None)),
        ]

        batches = list(get_rows("key", "users", mock.MagicMock(), manager))

        assert batches == [[{"id": "user_1"}]]
        assert mock_session.return_value.get.call_count == 1


class TestWorkspaceMembersFanOut:
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_fans_out_over_each_workspace(self, mock_session):
        manager = _make_manager()
        member_1 = {"type": "workspace_member", "user_id": "user_1", "workspace_id": "wrkspc_1"}
        member_2 = {"type": "workspace_member", "user_id": "user_1", "workspace_id": "wrkspc_2"}
        mock_session.return_value.get.side_effect = [
            _response(_entity_page([{"id": "wrkspc_1"}, {"id": "wrkspc_2"}], has_more=False, last_id="wrkspc_2")),
            _response(_entity_page([member_1], has_more=False)),
            _response(_entity_page([member_2], has_more=False)),
        ]

        batches = list(get_rows("key", "workspace_members", mock.MagicMock(), manager))

        assert batches == [[member_1], [member_2]]
        urls = _requested_urls(mock_session)
        assert urls[0].startswith("https://api.anthropic.com/v1/organizations/workspaces?")
        assert urls[1].startswith("https://api.anthropic.com/v1/organizations/workspaces/wrkspc_1/members")
        assert urls[2].startswith("https://api.anthropic.com/v1/organizations/workspaces/wrkspc_2/members")

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_fan_out_paginates_members_within_a_workspace(self, mock_session):
        manager = _make_manager()
        mock_session.return_value.get.side_effect = [
            _response(_entity_page([{"id": "wrkspc_1"}], has_more=False, last_id="wrkspc_1")),
            _response(_entity_page([{"user_id": "user_1", "workspace_id": "wrkspc_1"}], True, "user_1")),
            _response(_entity_page([{"user_id": "user_2", "workspace_id": "wrkspc_1"}], False, "user_2")),
        ]

        batches = list(get_rows("key", "workspace_members", mock.MagicMock(), manager))

        assert len(batches) == 2
        assert _query(_requested_urls(mock_session)[2])["after_id"] == ["user_1"]


class TestReportEndpoints:
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_usage_report_request_params(self, mock_session):
        manager = _make_manager()
        mock_session.return_value.get.side_effect = [_response(_report_page([], has_more=False))]

        list(get_rows("key", "usage_report", mock.MagicMock(), manager))

        query = _query(_requested_urls(mock_session)[0])
        assert query["starting_at"] == ["2023-01-01T00:00:00Z"]
        assert query["bucket_width"] == ["1d"]
        assert query["limit"] == ["31"]
        assert query["group_by[]"] == [
            "api_key_id",
            "workspace_id",
            "model",
            "service_tier",
            "context_window",
            "inference_geo",
        ]
        assert "page" not in query

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_cost_report_omits_bucket_width_and_groups_by_workspace_and_description(self, mock_session):
        manager = _make_manager()
        mock_session.return_value.get.side_effect = [_response(_report_page([], has_more=False))]

        list(get_rows("key", "cost_report", mock.MagicMock(), manager))

        query = _query(_requested_urls(mock_session)[0])
        # The cost report is daily-only; sending bucket_width is unnecessary.
        assert "bucket_width" not in query
        assert query["group_by[]"] == ["workspace_id", "description"]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_incremental_sync_starts_from_watermark_with_lookback(self, mock_session):
        manager = _make_manager()
        mock_session.return_value.get.side_effect = [_response(_report_page([], has_more=False))]

        list(
            get_rows(
                "key",
                "usage_report",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2026-07-08T00:00:00Z",
            )
        )

        assert _query(_requested_urls(mock_session)[0])["starting_at"] == ["2026-07-07T00:00:00Z"]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_paginates_with_page_token_and_saves_state_after_each_page(self, mock_session):
        manager = _make_manager()
        bucket_1 = {
            "starting_at": "2026-07-01T00:00:00Z",
            "ending_at": "2026-07-02T00:00:00Z",
            "results": [{"model": "claude-sonnet-4-5", "output_tokens": 10}],
        }
        bucket_2 = {
            "starting_at": "2026-07-02T00:00:00Z",
            "ending_at": "2026-07-03T00:00:00Z",
            "results": [{"model": "claude-sonnet-4-5", "output_tokens": 20}],
        }
        mock_session.return_value.get.side_effect = [
            _response(_report_page([bucket_1], has_more=True, next_page="page_2")),
            _response(_report_page([bucket_2], has_more=False)),
        ]

        batches = list(get_rows("key", "usage_report", mock.MagicMock(), manager))

        assert len(batches) == 2
        assert batches[0][0]["bucket_starting_at"] == "2026-07-01T00:00:00Z"
        assert batches[1][0]["bucket_starting_at"] == "2026-07-02T00:00:00Z"
        assert _query(_requested_urls(mock_session)[1])["page"] == ["page_2"]
        manager.save_state.assert_called_once_with(
            AnthropicResumeConfig(starting_at="2023-01-01T00:00:00Z", page="page_2")
        )

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_resumes_report_from_saved_window_and_page(self, mock_session):
        manager = _make_manager(AnthropicResumeConfig(starting_at="2026-06-01T00:00:00Z", page="page_9"))
        mock_session.return_value.get.side_effect = [_response(_report_page([], has_more=False))]

        list(get_rows("key", "usage_report", mock.MagicMock(), manager))

        query = _query(_requested_urls(mock_session)[0])
        assert query["starting_at"] == ["2026-06-01T00:00:00Z"]
        assert query["page"] == ["page_9"]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_stops_when_has_more_but_no_next_page(self, mock_session):
        manager = _make_manager()
        mock_session.return_value.get.side_effect = [_response(_report_page([], has_more=True, next_page=None))]

        assert list(get_rows("key", "usage_report", mock.MagicMock(), manager)) == []
        assert mock_session.return_value.get.call_count == 1


class TestErrorHandling:
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_client_error_raises(self, mock_session):
        manager = _make_manager()
        response = _response({}, status_code=400)
        response.raise_for_status.side_effect = Exception("400 Client Error")
        mock_session.return_value.get.return_value = response

        with pytest.raises(Exception, match="400 Client Error"):
            list(get_rows("key", "users", mock.MagicMock(), manager))


class TestAnthropicSource:
    @parameterized.expand(ENDPOINTS)
    def test_source_response_shape(self, endpoint):
        response = anthropic_source("key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == ANTHROPIC_ENDPOINTS[endpoint].primary_keys
        assert response.sort_mode == "asc"

    @parameterized.expand(["usage_report", "cost_report"])
    def test_report_endpoints_partition_on_bucket_start(self, endpoint):
        response = anthropic_source("key", endpoint, mock.MagicMock(), _make_manager())

        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["bucket_starting_at"]

    @parameterized.expand(["users", "invites", "workspaces", "workspace_members", "api_keys"])
    def test_entity_endpoints_are_not_partitioned(self, endpoint):
        response = anthropic_source("key", endpoint, mock.MagicMock(), _make_manager())

        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_workspace_members_uses_composite_primary_key(self):
        response = anthropic_source("key", "workspace_members", mock.MagicMock(), _make_manager())
        assert response.primary_keys == ["workspace_id", "user_id"]
