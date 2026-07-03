from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.lightspeed_retail import (
    LightspeedRetailResumeConfig,
    _base_url,
    _build_url,
    _clean_domain_prefix,
    _to_version,
    get_rows,
    lightspeed_retail_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.settings import (
    ENDPOINTS,
    LIGHTSPEED_RETAIL_ENDPOINTS,
)


def _make_manager(resume_state: LightspeedRetailResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(items: list[dict[str, Any]], max_version: int | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    body: dict[str, Any] = {"data": items}
    if max_version is not None:
        body["version"] = {"min": 0, "max": max_version}
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


class TestCleanDomainPrefix:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("mystore", "mystore"),
            (" mystore ", "mystore"),
            ("https://mystore.retail.lightspeed.app", "mystore"),
            ("mystore.retail.lightspeed.app/api/2.0", "mystore"),
            ("my-store", "my-store"),
        ],
    )
    def test_valid_prefixes(self, value, expected):
        assert _clean_domain_prefix(value) == expected

    @pytest.mark.parametrize("value", ["", "my store", "store?x=1", "../evil"])
    def test_invalid_prefixes_raise(self, value):
        with pytest.raises(ValueError):
            _clean_domain_prefix(value)

    def test_base_url(self):
        assert _base_url("mystore") == "https://mystore.retail.lightspeed.app/api/2.0"


class TestToVersion:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (12345, 12345),
            ("12345", 12345),
            (123.9, 123),
            ("not-a-number", None),
            (True, None),
        ],
    )
    def test_to_version_values(self, value, expected):
        assert _to_version(value) == expected


class TestBuildUrl:
    def test_without_after(self):
        url = _build_url("mystore", "/sales", None)
        assert url == "https://mystore.retail.lightspeed.app/api/2.0/sales?page_size=200"

    def test_with_after(self):
        url = _build_url("mystore", "/sales", 999)
        query = parse_qs(urlparse(url).query)
        assert query["after"] == ["999"]
        assert query["page_size"] == ["200"]


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
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.lightspeed_retail.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("mystore", "token") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.lightspeed_retail.make_tracked_session"
    )
    def test_validate_credentials_rejects_bad_prefix_without_request(self, mock_session):
        assert validate_credentials("my store!", "token") is False
        mock_session.return_value.get.assert_not_called()


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.lightspeed_retail.make_tracked_session"
    )
    def test_paginates_via_version_keyset(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "1", "version": 10}, {"id": "2", "version": 20}], max_version=20),
            _response([{"id": "3", "version": 30}], max_version=30),
            _response([]),
        ]

        manager = _make_manager()
        batches = list(get_rows("mystore", "token", "sales", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["1", "2", "3"]
        # State saved after each non-final page with the next keyset cursor.
        assert [call.args[0].after for call in manager.save_state.call_args_list] == [20, 30]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert "after" not in parse_qs(urlparse(urls[0]).query)
        assert parse_qs(urlparse(urls[1]).query)["after"] == ["20"]
        assert parse_qs(urlparse(urls[2]).query)["after"] == ["30"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.lightspeed_retail.make_tracked_session"
    )
    def test_resumes_from_saved_version(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager(LightspeedRetailResumeConfig(after=555))
        list(get_rows("mystore", "token", "sales", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["after"] == ["555"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.lightspeed_retail.make_tracked_session"
    )
    def test_incremental_starts_from_watermark_version(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        list(
            get_rows(
                "mystore",
                "token",
                "sales",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=777,
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["after"] == ["777"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.lightspeed_retail.make_tracked_session"
    )
    def test_full_refresh_starts_without_after(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        list(get_rows("mystore", "token", "sales", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert "after" not in parse_qs(urlparse(url).query)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.lightspeed_retail.make_tracked_session"
    )
    def test_missing_version_block_falls_back_to_page_max(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "1", "version": 10}]),
            _response([]),
        ]

        manager = _make_manager()
        batches = list(get_rows("mystore", "token", "sales", mock.MagicMock(), manager))

        assert len(batches) == 1
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(second_url).query)["after"] == ["10"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.lightspeed_retail.make_tracked_session"
    )
    def test_non_advancing_cursor_stops_instead_of_looping(self, mock_session):
        # Page with no version block and versions <= the current cursor must
        # terminate rather than refetch the same window forever.
        mock_session.return_value.get.return_value = _response([{"id": "1", "version": 5}])

        manager = _make_manager(LightspeedRetailResumeConfig(after=5))
        batches = list(get_rows("mystore", "token", "sales", mock.MagicMock(), manager))

        assert len(batches) == 1
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.lightspeed_retail.make_tracked_session"
    )
    def test_first_page_advances_when_fallback_version_is_zero(self, mock_session):
        # First page (no saved cursor) with no version block and page max of 0
        # must still advance: the `after or 0` floor used to break prematurely.
        mock_session.return_value.get.side_effect = [
            _response([{"id": "1", "version": 0}]),
            _response([]),
        ]

        manager = _make_manager()
        batches = list(get_rows("mystore", "token", "sales", mock.MagicMock(), manager))

        assert len(batches) == 1
        assert mock_session.return_value.get.call_count == 2
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(second_url).query)["after"] == ["0"]


class TestLightspeedRetailSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = LIGHTSPEED_RETAIL_ENDPOINTS[endpoint]
        response = lightspeed_retail_source("mystore", "token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(LIGHTSPEED_RETAIL_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key in {"sale_date", "created_at"}
