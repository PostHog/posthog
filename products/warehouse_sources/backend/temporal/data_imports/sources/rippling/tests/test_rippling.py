from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.rippling.rippling import (
    PAGE_SIZE,
    RipplingResumeConfig,
    _absolutize_next_url,
    _build_params,
    _build_url,
    _format_filter_timestamp,
    get_rows,
    rippling_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rippling.settings import (
    ENDPOINTS,
    RIPPLING_ENDPOINTS,
)


def _make_manager(resume_state: RipplingResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(items: list[dict[str, Any]], next_link: str | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {"results": items, "next_link": next_link}
    resp.status_code = 200
    resp.ok = True
    return resp


class TestFormatFilterTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 10, 1, 3, 4, 5, tzinfo=UTC), "2024-10-01T03:04:05"),
            (datetime(2024, 10, 1, 3, 4, 5), "2024-10-01T03:04:05"),
            (date(2024, 10, 1), "2024-10-01T00:00:00"),
            ("2024-10-01T00:00:00", "2024-10-01T00:00:00"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_filter_timestamp(value) == expected


class TestBuildParams:
    def test_incremental_builds_odata_filter_and_sort(self):
        params = _build_params(
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 10, 1, tzinfo=UTC),
            incremental_field="updated_at",
        )

        assert params["filter"] == "updated_at ge 2024-10-01T00:00:00"
        assert params["order_by"] == "updated_at"
        assert params["limit"] == PAGE_SIZE

    def test_incremental_honors_created_at_cursor(self):
        params = _build_params(
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 10, 1, tzinfo=UTC),
            incremental_field="created_at",
        )

        assert params["filter"] == "created_at ge 2024-10-01T00:00:00"
        assert params["order_by"] == "created_at"

    def test_incremental_without_last_value_falls_back_to_full_refresh_sort(self):
        params = _build_params(
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="updated_at",
        )

        assert "filter" not in params
        assert params["order_by"] == "created_at"

    def test_full_refresh_sorts_on_stable_creation_date(self):
        params = _build_params(
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )

        assert "filter" not in params
        assert params["order_by"] == "created_at"


class TestBuildUrl:
    def test_encodes_filter_expression(self):
        url = _build_url("/workers", {"limit": 100, "filter": "updated_at ge 2024-10-01T00:00:00"})
        parsed = urlparse(url)
        assert parsed.netloc == "rest.ripplingapis.com"
        assert parse_qs(parsed.query)["filter"] == ["updated_at ge 2024-10-01T00:00:00"]


class TestAbsolutizeNextUrl:
    @pytest.mark.parametrize(
        "next_link, expected",
        [
            ("/workers?cursor=abc", "https://rest.ripplingapis.com/workers?cursor=abc"),
            (
                "https://rest.ripplingapis.com/workers?cursor=xyz",
                "https://rest.ripplingapis.com/workers?cursor=xyz",
            ),
        ],
    )
    def test_allows_on_domain_links(self, next_link, expected):
        assert _absolutize_next_url(next_link) == expected

    @pytest.mark.parametrize(
        "next_link",
        [
            "https://attacker.example/workers",
            "//attacker.example/workers",
            "http://rest.ripplingapis.com/workers",
            "https://rest.ripplingapis.com.attacker.example/workers",
        ],
    )
    def test_rejects_off_domain_links(self, next_link):
        with pytest.raises(ValueError):
            _absolutize_next_url(next_link)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            # A valid token without the companies.read scope still 403s; only 401
            # means the token itself is bad.
            (403, True),
            (401, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.rippling.rippling.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("token") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.rippling.rippling.make_tracked_session"
    )
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.rippling.rippling.make_tracked_session"
    )
    def test_paginates_via_next_link_and_absolutizes_relative_urls(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "1"}], next_link="/workers?limit=100&cursor=abc"),
            _response([{"id": "2"}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "workers", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["1", "2"]
        manager.save_state.assert_called_once()
        saved_url = manager.save_state.call_args.args[0].next_url
        assert saved_url == "https://rest.ripplingapis.com/workers?limit=100&cursor=abc"
        assert mock_session.return_value.get.call_args_list[1].args[0] == saved_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.rippling.rippling.make_tracked_session"
    )
    def test_absolute_next_link_used_as_is(self, mock_session):
        absolute = "https://rest.ripplingapis.com/workers?cursor=xyz"
        mock_session.return_value.get.side_effect = [
            _response([{"id": "1"}], next_link=absolute),
            _response([]),
        ]

        manager = _make_manager()
        list(get_rows("token", "workers", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[1].args[0] == absolute

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.rippling.rippling.make_tracked_session"
    )
    def test_resumes_from_saved_state(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"id": "9"}])

        resume_url = "https://rest.ripplingapis.com/workers?cursor=resume"
        manager = _make_manager(RipplingResumeConfig(next_url=resume_url))

        list(get_rows("token", "workers", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[0].args[0] == resume_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.rippling.rippling.make_tracked_session"
    )
    def test_incremental_request_includes_filter(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        list(
            get_rows(
                "token",
                "workers",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 10, 1, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        query = parse_qs(urlparse(url).query)
        assert query["filter"] == ["updated_at ge 2024-10-01T00:00:00"]
        assert query["order_by"] == ["updated_at"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.rippling.rippling.make_tracked_session"
    )
    def test_empty_response_stops_without_saving_state(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        batches = list(get_rows("token", "workers", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()


class TestRipplingSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = RIPPLING_ENDPOINTS[endpoint]
        response = rippling_source("token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(RIPPLING_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "created_at"
