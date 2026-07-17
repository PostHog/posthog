from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.gocardless import (
    GoCardlessResumeConfig,
    _base_url,
    _build_params,
    _format_created_at,
    get_rows,
    gocardless_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.settings import (
    ENDPOINTS,
    GOCARDLESS_ENDPOINTS,
)


def _make_manager(resume_state: GoCardlessResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(data_key: str, items: list[dict[str, Any]], after: str | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {data_key: items, "meta": {"cursors": {"before": None, "after": after}, "limit": 500}}
    resp.status_code = 200
    resp.ok = True
    return resp


class TestBaseUrl:
    @pytest.mark.parametrize(
        "environment, expected",
        [
            ("live", "https://api.gocardless.com"),
            ("sandbox", "https://api-sandbox.gocardless.com"),
        ],
    )
    def test_known_environment_returns_host(self, environment, expected):
        assert _base_url(environment) == expected

    def test_invalid_environment_raises(self):
        with pytest.raises(ValueError):
            _base_url("evil.example.com")


class TestFormatCreatedAt:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, 123000, tzinfo=UTC), "2024-01-02T03:04:05.123Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05.000Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00.000Z"),
            ("2024-01-02T03:04:05.000Z", "2024-01-02T03:04:05.000Z"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_created_at(value) == expected


class TestBuildParams:
    def test_incremental_events_filters_on_created_at(self):
        params = _build_params(
            GOCARDLESS_ENDPOINTS["events"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            after=None,
        )

        assert params["created_at[gte]"] == "2024-01-02T00:00:00.000Z"
        assert params["limit"] == 500

    def test_full_refresh_has_no_filter(self):
        params = _build_params(
            GOCARDLESS_ENDPOINTS["payments"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            after="CU123",
        )

        assert "created_at[gte]" not in params
        assert params["after"] == "CU123"

    def test_non_incremental_endpoint_ignores_watermark(self):
        params = _build_params(
            GOCARDLESS_ENDPOINTS["payments"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            after=None,
        )

        assert "created_at[gte]" not in params


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.gocardless.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("live", "token") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.gocardless.make_tracked_session"
    )
    def test_validate_credentials_rejects_bad_environment_without_request(self, mock_session):
        assert validate_credentials("evil", "token") is False
        mock_session.return_value.get.assert_not_called()


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.gocardless.make_tracked_session"
    )
    def test_paginates_via_meta_cursors(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response("payments", [{"id": "PM1"}], after="PM1"),
            _response("payments", [{"id": "PM2"}], after=None),
        ]

        manager = _make_manager()
        batches = list(get_rows("live", "token", "payments", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["PM1", "PM2"]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].after == "PM1"
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(second_url).query)["after"] == ["PM1"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.gocardless.make_tracked_session"
    )
    def test_requests_carry_version_header(self, mock_session):
        mock_session.return_value.get.return_value = _response("payments", [])

        manager = _make_manager()
        list(get_rows("live", "token", "payments", mock.MagicMock(), manager))

        headers = mock_session.call_args.kwargs["headers"]
        assert headers["GoCardless-Version"] == "2015-07-06"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.gocardless.make_tracked_session"
    )
    def test_sandbox_uses_sandbox_host(self, mock_session):
        mock_session.return_value.get.return_value = _response("payments", [])

        manager = _make_manager()
        list(get_rows("sandbox", "token", "payments", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert urlparse(url).netloc == "api-sandbox.gocardless.com"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.gocardless.make_tracked_session"
    )
    def test_incremental_request_includes_filter(self, mock_session):
        mock_session.return_value.get.return_value = _response("events", [])

        manager = _make_manager()
        list(
            get_rows(
                "live",
                "token",
                "events",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["created_at[gte]"] == ["2024-01-02T00:00:00.000Z"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.gocardless.make_tracked_session"
    )
    def test_resumes_from_saved_cursor(self, mock_session):
        mock_session.return_value.get.return_value = _response("payments", [])

        manager = _make_manager(GoCardlessResumeConfig(after="PM_RESUME"))
        list(get_rows("live", "token", "payments", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["after"] == ["PM_RESUME"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.gocardless.make_tracked_session"
    )
    def test_empty_page_with_cursor_stops(self, mock_session):
        mock_session.return_value.get.return_value = _response("payments", [], after="PM_LOOP")

        manager = _make_manager()
        batches = list(get_rows("live", "token", "payments", mock.MagicMock(), manager))

        assert batches == []
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()


class TestGoCardlessSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = GOCARDLESS_ENDPOINTS[endpoint]
        response = gocardless_source("live", "token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        # Lists are reverse-chronological; only the incremental events stream
        # declares desc so the pipeline defers its watermark commit.
        if config.incremental_fields:
            assert response.sort_mode == "desc"
        else:
            assert response.sort_mode == "asc"

    @pytest.mark.parametrize("config", list(GOCARDLESS_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        assert config.partition_key == "created_at"
