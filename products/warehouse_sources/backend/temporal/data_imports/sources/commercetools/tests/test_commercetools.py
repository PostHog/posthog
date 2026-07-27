from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.commercetools import (
    MAX_OFFSET,
    PAGE_SIZE,
    CommercetoolsResumeConfig,
    _api_base_url,
    _auth_url,
    _build_url,
    _format_last_modified,
    _validate_path_component,
    commercetools_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.settings import (
    COMMERCETOOLS_ENDPOINTS,
    ENDPOINTS,
)


def _make_manager(resume_state: CommercetoolsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _token_response() -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {"access_token": "the-token", "token_type": "Bearer", "expires_in": 172800}
    resp.status_code = 200
    resp.ok = True
    return resp


def _page_response(items: list[dict[str, Any]]) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {"limit": PAGE_SIZE, "offset": 0, "count": len(items), "results": items}
    resp.status_code = 200
    resp.ok = True
    return resp


class TestUrlHelpers:
    def test_auth_and_api_urls(self):
        assert _auth_url("europe-west1.gcp") == "https://auth.europe-west1.gcp.commercetools.com/oauth/token"
        assert _api_base_url("us-central1.gcp", "my-project") == (
            "https://api.us-central1.gcp.commercetools.com/my-project"
        )

    @pytest.mark.parametrize("value", ["", "bad value", "x/y", "x?y", "../up"])
    def test_invalid_path_components_raise(self, value):
        with pytest.raises(ValueError):
            _validate_path_component(value, "test")

    def test_build_url_full_refresh(self):
        url = _build_url("https://api.x.commercetools.com/p", COMMERCETOOLS_ENDPOINTS["orders"], None, 0)
        query = parse_qs(urlparse(url).query)
        assert query["limit"] == [str(PAGE_SIZE)]
        assert query["offset"] == ["0"]
        assert query["sort"] == ["lastModifiedAt asc"]
        assert query["withTotal"] == ["false"]
        assert "where" not in query

    def test_build_url_with_anchor(self):
        url = _build_url(
            "https://api.x.commercetools.com/p", COMMERCETOOLS_ENDPOINTS["orders"], "2024-01-02T03:04:05.000Z", 500
        )
        query = parse_qs(urlparse(url).query)
        assert query["where"] == ['lastModifiedAt >= "2024-01-02T03:04:05.000Z"']
        assert query["offset"] == ["500"]


class TestFormatLastModified:
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
        assert _format_last_modified(value) == expected


class TestValidateCredentials:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.commercetools.make_tracked_session"
    )
    def test_valid_when_token_mints(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        assert validate_credentials("us-central1.gcp", "my-project", "id", "secret") is True

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.commercetools.make_tracked_session"
    )
    def test_invalid_when_token_mint_fails(self, mock_session):
        resp = mock.MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=mock.MagicMock())
        mock_session.return_value.post.return_value = resp
        assert validate_credentials("us-central1.gcp", "my-project", "id", "secret") is False

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.commercetools.make_tracked_session"
    )
    def test_invalid_project_key_rejected_without_request(self, mock_session):
        assert validate_credentials("us-central1.gcp", "bad key!", "id", "secret") is False
        mock_session.return_value.post.assert_not_called()


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.commercetools.make_tracked_session"
    )
    def test_paginates_with_offset_until_short_page(self, mock_session):
        full_page = [{"id": str(i), "lastModifiedAt": "2024-01-01T00:00:00.000Z"} for i in range(PAGE_SIZE)]
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [
            _page_response(full_page),
            _page_response([{"id": "last", "lastModifiedAt": "2024-01-02T00:00:00.000Z"}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("us-central1.gcp", "proj", "id", "secret", "orders", mock.MagicMock(), manager))

        assert len(batches) == 2
        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert saved.anchor is None
        assert saved.offset == PAGE_SIZE
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(second_url).query)["offset"] == [str(PAGE_SIZE)]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.commercetools.make_tracked_session"
    )
    def test_reanchors_at_offset_cap(self, mock_session):
        pages = []
        for page_index in range(MAX_OFFSET // PAGE_SIZE):
            pages.append(
                _page_response(
                    [
                        {"id": f"{page_index}-{i}", "lastModifiedAt": f"2024-01-01T00:00:{page_index:02d}.000Z"}
                        for i in range(PAGE_SIZE)
                    ]
                )
            )
        # After re-anchoring, one short page ends the scan.
        pages.append(_page_response([{"id": "post-anchor", "lastModifiedAt": "2024-01-02T00:00:00.000Z"}]))
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = pages

        manager = _make_manager()
        batches = list(get_rows("us-central1.gcp", "proj", "id", "secret", "orders", mock.MagicMock(), manager))

        assert len(batches) == MAX_OFFSET // PAGE_SIZE + 1
        post_cap_url = mock_session.return_value.get.call_args_list[-1].args[0]
        query = parse_qs(urlparse(post_cap_url).query)
        # The window re-anchored on the latest lastModifiedAt with offset reset.
        assert query["where"] == ['lastModifiedAt >= "2024-01-01T00:00:19.000Z"']
        assert query["offset"] == ["0"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.commercetools.make_tracked_session"
    )
    def test_non_advancing_anchor_stops_at_cap(self, mock_session):
        same_ts = "2024-01-01T00:00:00.000Z"
        pages = [
            _page_response([{"id": f"{p}-{i}", "lastModifiedAt": same_ts} for i in range(PAGE_SIZE)])
            for p in range(MAX_OFFSET // PAGE_SIZE)
        ]
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [*pages, _page_response([])]

        manager = _make_manager(CommercetoolsResumeConfig(anchor=same_ts, offset=0))
        logger = mock.MagicMock()
        batches = list(get_rows("us-central1.gcp", "proj", "id", "secret", "orders", logger, manager))

        # All cap pages yielded, then the scan stops instead of looping.
        assert len(batches) == MAX_OFFSET // PAGE_SIZE
        logger.error.assert_called_once()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.commercetools.make_tracked_session"
    )
    def test_incremental_starts_from_watermark_anchor(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _page_response([])

        manager = _make_manager()
        list(
            get_rows(
                "us-central1.gcp",
                "proj",
                "id",
                "secret",
                "orders",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["where"] == ['lastModifiedAt >= "2024-01-02T00:00:00.000Z"']

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.commercetools.make_tracked_session"
    )
    def test_remints_token_on_401(self, mock_session):
        expired = mock.MagicMock()
        expired.status_code = 401
        expired.ok = False
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [expired, _page_response([{"id": "1"}])]

        manager = _make_manager()
        batches = list(get_rows("us-central1.gcp", "proj", "id", "secret", "orders", mock.MagicMock(), manager))

        assert batches == [[{"id": "1"}]]
        assert mock_session.return_value.post.call_count == 2

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.commercetools.make_tracked_session"
    )
    def test_resumes_from_saved_state(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _page_response([])

        manager = _make_manager(CommercetoolsResumeConfig(anchor="2024-01-01T00:00:00.000Z", offset=1500))
        list(get_rows("us-central1.gcp", "proj", "id", "secret", "orders", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        query = parse_qs(urlparse(url).query)
        assert query["where"] == ['lastModifiedAt >= "2024-01-01T00:00:00.000Z"']
        assert query["offset"] == ["1500"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.commercetools.make_tracked_session"
    )
    def test_empty_response_stops_without_saving_state(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _page_response([])

        manager = _make_manager()
        batches = list(get_rows("us-central1.gcp", "proj", "id", "secret", "orders", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()


class TestCommercetoolsSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = COMMERCETOOLS_ENDPOINTS[endpoint]
        response = commercetools_source(
            "us-central1.gcp", "proj", "id", "secret", endpoint, mock.MagicMock(), _make_manager()
        )

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]

    @pytest.mark.parametrize("config", list(COMMERCETOOLS_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        assert config.partition_key == "createdAt"
