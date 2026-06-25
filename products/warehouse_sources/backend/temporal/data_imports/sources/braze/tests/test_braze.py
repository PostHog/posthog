from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze import (
    BrazeHostNotAllowedError,
    BrazeResumeConfig,
    _build_params,
    _format_modified_after,
    _next_cursor,
    _normalize_items,
    braze_source,
    get_rows,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braze.settings import BRAZE_ENDPOINTS, ENDPOINTS

BASE_URL = "https://rest.iad-01.braze.com"


def _make_manager(resume_state: BrazeResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: dict[str, Any], status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 400
    return resp


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://rest.iad-01.braze.com", "https://rest.iad-01.braze.com"),
            ("https://rest.iad-01.braze.com/", "https://rest.iad-01.braze.com"),
            ("https://rest.iad-01.braze.com///", "https://rest.iad-01.braze.com"),
            # Plaintext is upgraded to https; a scheme-less host gets one.
            ("http://rest.iad-01.braze.com", "https://rest.iad-01.braze.com"),
            ("rest.iad-01.braze.com", "https://rest.iad-01.braze.com"),
            ("  https://rest.iad-01.braze.com  ", "https://rest.iad-01.braze.com"),
        ],
    )
    def test_normalizes_to_https(self, value, expected):
        assert normalize_base_url(value) == expected


class TestFormatModifiedAfter:
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
        assert _format_modified_after(value) == expected


class TestBuildParams:
    def test_page_pagination(self):
        params = _build_params(BRAZE_ENDPOINTS["campaigns"], cursor=3, modified_after=None)
        assert params == {"page": 3}

    def test_offset_pagination(self):
        params = _build_params(BRAZE_ENDPOINTS["email_templates"], cursor=200, modified_after=None)
        assert params == {"limit": 100, "offset": 200}

    def test_modified_after_added_only_for_incremental_endpoint(self):
        params = _build_params(BRAZE_ENDPOINTS["email_templates"], cursor=0, modified_after="2026-01-01T00:00:00+00:00")
        assert params["modified_after"] == "2026-01-01T00:00:00+00:00"

    def test_modified_after_ignored_for_full_refresh_endpoint(self):
        # campaigns has no modified_after_param, so the cutoff must never leak into params.
        params = _build_params(BRAZE_ENDPOINTS["campaigns"], cursor=0, modified_after="2026-01-01T00:00:00+00:00")
        assert "modified_after" not in params


class TestNextCursor:
    def test_page_increments_by_one(self):
        assert _next_cursor(BRAZE_ENDPOINTS["campaigns"], 4) == 5

    def test_offset_increments_by_page_size(self):
        assert _next_cursor(BRAZE_ENDPOINTS["email_templates"], 200) == 300


class TestNormalizeItems:
    def test_wraps_scalar_event_names(self):
        items = _normalize_items(BRAZE_ENDPOINTS["events"], ["purchase", "login"])
        assert items == [{"event_name": "purchase"}, {"event_name": "login"}]

    def test_drops_non_dict_rows_for_object_endpoints(self):
        items = _normalize_items(BRAZE_ENDPOINTS["campaigns"], [{"id": "a"}, "garbage", {"id": "b"}])
        assert items == [{"id": "a"}, {"id": "b"}]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Braze API key"),
            (403, False, "Your Braze API key does not have permission for this endpoint"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze.make_tracked_session")
    def test_status_mapping(self, mock_session, status_code, expected_valid, expected_message):
        mock_session.return_value.get.return_value = _response({"message": "x"}, status_code=status_code)

        valid, message = validate_credentials("key", BASE_URL)

        assert valid is expected_valid
        assert message == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze.make_tracked_session")
    def test_uses_no_redirect_session(self, mock_session):
        mock_session.return_value.get.return_value = _response({}, status_code=200)
        validate_credentials("key", BASE_URL)
        assert mock_session.call_args.kwargs["allow_redirects"] is False

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze.make_tracked_session")
    def test_swallows_request_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
        valid, message = validate_credentials("key", BASE_URL)
        assert valid is False
        assert message == "boom"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze._is_host_safe")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze.make_tracked_session")
    def test_blocks_internal_host_when_team_id_given(self, mock_session, mock_host_safe):
        mock_host_safe.return_value = (False, "host not allowed")

        valid, message = validate_credentials("key", "https://10.0.0.1", team_id=42)

        assert valid is False
        assert message == "host not allowed"
        # The host is rejected before any request is dispatched.
        mock_session.return_value.get.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze._is_host_safe")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze.make_tracked_session")
    def test_skips_host_check_when_team_id_omitted(self, mock_session, mock_host_safe):
        mock_session.return_value.get.return_value = _response({}, status_code=200)

        validate_credentials("key", BASE_URL)

        mock_host_safe.assert_not_called()


class TestGetRows:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze.make_tracked_session")
    def test_page_pagination_walks_until_empty(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"campaigns": [{"id": "1"}, {"id": "2"}]}),
            _response({"campaigns": [{"id": "3"}]}),
            _response({"campaigns": []}),
        ]

        manager = _make_manager()
        batches = list(get_rows("key", BASE_URL, "campaigns", mock.MagicMock(), manager, team_id=1))

        assert [item["id"] for batch in batches for item in batch] == ["1", "2", "3"]
        # page param walked 0, 1, 2
        pages = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert "page=0" in pages[0]
        assert "page=1" in pages[1]
        assert "page=2" in pages[2]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze.make_tracked_session")
    def test_offset_pagination_advances_by_page_size(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"templates": [{"email_template_id": "a"}]}),
            _response({"templates": []}),
        ]

        manager = _make_manager()
        list(get_rows("key", BASE_URL, "email_templates", mock.MagicMock(), manager, team_id=1))

        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert "offset=0" in urls[0]
        assert "limit=100" in urls[0]
        assert "offset=100" in urls[1]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze.make_tracked_session")
    def test_saves_current_cursor_after_each_yield(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"campaigns": [{"id": "1"}]}),
            _response({"campaigns": [{"id": "2"}]}),
            _response({"campaigns": []}),
        ]

        manager = _make_manager()
        list(get_rows("key", BASE_URL, "campaigns", mock.MagicMock(), manager, team_id=1))

        saved = [call.args[0].cursor for call in manager.save_state.call_args_list]
        # Saves the cursor of the page just yielded (0, then 1), not the next page.
        assert saved == [0, 1]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze.make_tracked_session")
    def test_resumes_from_saved_cursor(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"campaigns": [{"id": "9"}]}),
            _response({"campaigns": []}),
        ]

        manager = _make_manager(BrazeResumeConfig(cursor=5))
        list(get_rows("key", BASE_URL, "campaigns", mock.MagicMock(), manager, team_id=1))

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "page=5" in first_url

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze.make_tracked_session")
    def test_empty_first_page_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _response({"campaigns": []})

        manager = _make_manager()
        batches = list(get_rows("key", BASE_URL, "campaigns", mock.MagicMock(), manager, team_id=1))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze.make_tracked_session")
    def test_incremental_applies_modified_after_filter(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"templates": [{"email_template_id": "a", "updated_at": "2026-02-01T00:00:00Z"}]}),
            _response({"templates": []}),
        ]

        manager = _make_manager()
        list(
            get_rows(
                "key",
                BASE_URL,
                "email_templates",
                mock.MagicMock(),
                manager,
                team_id=1,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "modified_after=2026-01-01" in first_url

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze.make_tracked_session")
    def test_full_refresh_endpoint_never_sends_modified_after(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"campaigns": [{"id": "1"}]}),
            _response({"campaigns": []}),
        ]

        manager = _make_manager()
        list(
            get_rows(
                "key",
                BASE_URL,
                "campaigns",
                mock.MagicMock(),
                manager,
                team_id=1,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field="created_at",
            )
        )

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "modified_after" not in first_url

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze.make_tracked_session")
    def test_events_endpoint_wraps_scalar_rows(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"events": ["purchase", "login"]}),
            _response({"events": []}),
        ]

        manager = _make_manager()
        batches = list(get_rows("key", BASE_URL, "events", mock.MagicMock(), manager, team_id=1))

        assert [item for batch in batches for item in batch] == [{"event_name": "purchase"}, {"event_name": "login"}]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze._is_host_safe")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze.make_tracked_session")
    def test_raises_when_host_not_allowed(self, mock_session, mock_host_safe):
        mock_host_safe.return_value = (False, "host not allowed")

        manager = _make_manager()
        with pytest.raises(BrazeHostNotAllowedError):
            list(get_rows("key", "https://10.0.0.1", "campaigns", mock.MagicMock(), manager, team_id=42))

        # No request is made once the host is rejected.
        mock_session.return_value.get.assert_not_called()


class TestBrazeSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = BRAZE_ENDPOINTS[endpoint]
        response = braze_source("key", BASE_URL, endpoint, mock.MagicMock(), _make_manager(), team_id=1)

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(BRAZE_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        # Partition keys must be immutable creation timestamps, never updated/last-edit fields.
        if config.partition_key:
            assert config.partition_key == "created_at"
