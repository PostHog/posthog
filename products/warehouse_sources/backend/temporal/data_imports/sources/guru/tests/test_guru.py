from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.guru.guru import (
    GuruResumeConfig,
    _build_params,
    _build_url,
    _format_last_modified,
    _normalize_member,
    get_rows,
    guru_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.guru.settings import ENDPOINTS, GURU_ENDPOINTS


def _make_manager(resume_state: GuruResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(items: list[dict[str, Any]], next_link: str | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = items
    resp.status_code = 200
    resp.ok = True
    resp.is_redirect = False
    resp.is_permanent_redirect = False
    resp.links = {"next-page": {"url": next_link}} if next_link else {}
    return resp


class TestFormatLastModified:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05+00:00"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05+00:00"),
            (date(2024, 1, 2), "2024-01-02T00:00:00+00:00"),
            ("2024-01-02T03:04:05+00:00", "2024-01-02T03:04:05+00:00"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_last_modified(value) == expected


class TestBuildParams:
    def test_incremental_cards_filters_and_sorts_on_cursor_field(self):
        params = _build_params(
            GURU_ENDPOINTS["cards"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="lastModified",
        )

        assert params["q"] == "lastModified >= 2024-01-01T00:00:00+00:00"
        assert params["sortField"] == "lastModified"
        assert params["sortOrder"] == "asc"
        assert params["queryType"] == "cards"

    def test_incremental_without_last_value_falls_back_to_full_refresh_sort(self):
        params = _build_params(
            GURU_ENDPOINTS["cards"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="lastModified",
        )

        assert "q" not in params
        assert params["sortField"] == "dateCreated"
        assert params["sortOrder"] == "asc"

    def test_full_refresh_cards_sorts_on_stable_creation_date(self):
        params = _build_params(
            GURU_ENDPOINTS["cards"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )

        assert "q" not in params
        assert params["sortField"] == "dateCreated"
        assert params["sortOrder"] == "asc"

    @pytest.mark.parametrize("endpoint", ["collections", "groups", "members"])
    def test_non_incremental_endpoints_have_no_search_params(self, endpoint):
        params = _build_params(
            GURU_ENDPOINTS[endpoint],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )

        assert params == {}


class TestBuildUrl:
    def test_no_params(self):
        assert _build_url("/collections", {}) == "https://api.getguru.com/api/v1/collections"

    def test_encodes_gql_query(self):
        url = _build_url("/search/query", {"q": "lastModified >= 2024-01-01T00:00:00+00:00"})
        parsed = urlparse(url)
        assert parse_qs(parsed.query)["q"] == ["lastModified >= 2024-01-01T00:00:00+00:00"]


class TestNormalizeMember:
    def test_copies_nested_user_email_to_top_level(self):
        item = {"user": {"email": "jane@company.com", "firstName": "Jane"}, "groups": []}
        assert _normalize_member(item)["email"] == "jane@company.com"

    def test_keeps_existing_top_level_email(self):
        item = {"email": "top@company.com", "user": {"email": "nested@company.com"}}
        assert _normalize_member(item)["email"] == "top@company.com"

    @pytest.mark.parametrize(
        "item",
        [
            {"user": None},
            {},
        ],
    )
    def test_leaves_items_without_email_untouched(self, item):
        assert _normalize_member(item) == item

    def test_missing_nested_email_raises_keyerror(self):
        # email is the primary key, so a member nesting a user dict without an email must
        # fail loudly rather than produce a row with a null primary key.
        with pytest.raises(KeyError):
            _normalize_member({"user": {"firstName": "Jane"}})


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
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.guru.guru.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("user@company.com", "token") is expected

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.guru.guru.make_tracked_session")
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("user@company.com", "token") is False


class TestGetRows:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.guru.guru.make_tracked_session")
    def test_paginates_via_link_header(self, mock_session):
        next_url = "https://api.getguru.com/api/v1/collections?token=abc"
        mock_session.return_value.get.side_effect = [
            _response([{"id": "1"}, {"id": "2"}], next_link=next_url),
            _response([{"id": "3"}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("user@company.com", "token", "collections", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["1", "2", "3"]
        # State is saved only while a next page exists, after the page is yielded.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_url == next_url

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.guru.guru.make_tracked_session")
    def test_resumes_from_saved_state(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"id": "9"}])

        resume_url = "https://api.getguru.com/api/v1/collections?token=resume"
        manager = _make_manager(GuruResumeConfig(next_url=resume_url))

        list(get_rows("user@company.com", "token", "collections", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[0].args[0] == resume_url

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.guru.guru.make_tracked_session")
    def test_stops_pagination_when_next_url_host_differs(self, mock_session):
        # A tampered Link header pointing off-host must not move the credentialed request.
        evil_url = "http://169.254.169.254/latest/meta-data"
        mock_session.return_value.get.side_effect = [
            _response([{"id": "1"}], next_link=evil_url),
        ]

        manager = _make_manager()
        batches = list(get_rows("user@company.com", "token", "collections", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["1"]
        # Only one request was made; the off-host next URL was neither followed nor saved.
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.guru.guru.make_tracked_session")
    def test_ignores_resume_url_with_foreign_host(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager(GuruResumeConfig(next_url="http://169.254.169.254/latest/meta-data"))
        list(get_rows("user@company.com", "token", "collections", mock.MagicMock(), manager))

        # Falls back to the canonical built URL rather than the foreign resume URL.
        assert mock_session.return_value.get.call_args.args[0].startswith("https://api.getguru.com/api/v1/collections")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.guru.guru.make_tracked_session")
    def test_members_rows_are_normalized(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"user": {"email": "jane@company.com"}}])

        manager = _make_manager()
        batches = list(get_rows("user@company.com", "token", "members", mock.MagicMock(), manager))

        assert batches == [[{"user": {"email": "jane@company.com"}, "email": "jane@company.com"}]]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.guru.guru.make_tracked_session")
    def test_incremental_request_includes_gql_filter(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        list(
            get_rows(
                "user@company.com",
                "token",
                "cards",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
                incremental_field="lastModified",
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        query = parse_qs(urlparse(url).query)
        assert query["q"] == ["lastModified >= 2024-01-01T00:00:00+00:00"]
        assert query["sortField"] == ["lastModified"]
        assert query["sortOrder"] == ["asc"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.guru.guru.make_tracked_session")
    def test_empty_response_stops_without_saving_state(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        batches = list(get_rows("user@company.com", "token", "cards", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.guru.guru.make_tracked_session")
    def test_non_list_response_yields_nothing(self, mock_session):
        resp = _response([])
        resp.json.return_value = {"error": "unexpected"}
        mock_session.return_value.get.return_value = resp

        manager = _make_manager()
        batches = list(get_rows("user@company.com", "token", "cards", mock.MagicMock(), manager))

        assert batches == []


class TestGuruSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = GURU_ENDPOINTS[endpoint]
        response = guru_source("user@company.com", "token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(GURU_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "dateCreated"
