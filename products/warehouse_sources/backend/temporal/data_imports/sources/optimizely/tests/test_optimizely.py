from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.optimizely import (
    PAGE_SIZE,
    get_rows,
    optimizely_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.settings import (
    ENDPOINTS,
    OPTIMIZELY_ENDPOINTS,
)


def _response(items: list[dict[str, Any]], next_url: str | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = items
    resp.status_code = 200
    resp.ok = True
    resp.links = {"next": {"url": next_url}} if next_url else {}
    return resp


def _http_error(status: int) -> requests.HTTPError:
    response = mock.MagicMock()
    response.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=response)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (403, True),
            (401, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.optimizely.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("token") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.optimizely.make_tracked_session"
    )
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.optimizely.make_tracked_session"
    )
    def test_projects_paginates_via_link_header(self, mock_session):
        next_url = "https://api.optimizely.com/v2/projects?page=2&per_page=100"
        mock_session.return_value.get.side_effect = [
            _response([{"id": 1}], next_url=next_url),
            _response([{"id": 2}]),
        ]

        batches = list(get_rows("token", "projects", mock.MagicMock()))

        assert [item["id"] for batch in batches for item in batch] == [1, 2]
        assert mock_session.return_value.get.call_args_list[1].args[0] == next_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.optimizely.make_tracked_session"
    )
    def test_project_scoped_endpoint_fans_out_over_projects(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": 11}, {"id": 22}]),  # projects list
            _response([{"id": "exp-1", "project_id": 11}]),
            _response([{"id": "exp-2", "project_id": 22}]),
        ]

        batches = list(get_rows("token", "experiments", mock.MagicMock()))

        assert [item["id"] for batch in batches for item in batch] == ["exp-1", "exp-2"]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urlparse(urls[0]).path == "/v2/projects"
        assert parse_qs(urlparse(urls[1]).query)["project_id"] == ["11"]
        assert parse_qs(urlparse(urls[2]).query)["project_id"] == ["22"]
        assert all(parse_qs(urlparse(u).query)["per_page"] == [str(PAGE_SIZE)] for u in urls)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.optimizely._iterate_pages")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.optimizely.make_tracked_session"
    )
    def test_fan_out_skips_projects_without_feature_access(self, mock_session, mock_iterate):
        def iterate(session, path, params, logger):
            if path == "/projects":
                yield [{"id": 11}, {"id": 22}]
                return
            if params.get("project_id") == 11:
                raise _http_error(403)
            yield [{"id": "camp-1"}]

        mock_iterate.side_effect = iterate

        logger = mock.MagicMock()
        batches = list(get_rows("token", "campaigns", logger))

        assert batches == [[{"id": "camp-1"}]]
        logger.warning.assert_called_once()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.optimizely._iterate_pages")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.optimizely.make_tracked_session"
    )
    def test_fan_out_raises_on_unexpected_errors(self, mock_session, mock_iterate):
        # 401 and other non-retried 4xx (not in the skip set 400/403/404) are the
        # cases that actually reach the `raise` branch via requests.HTTPError.
        # 5xx would arrive as OptimizelyRetryableError (after retries), bypassing
        # the HTTPError handler entirely.
        def iterate(session, path, params, logger):
            if path == "/projects":
                yield [{"id": 11}]
                return
            raise _http_error(401)

        mock_iterate.side_effect = iterate

        with pytest.raises(requests.HTTPError):
            list(get_rows("token", "experiments", mock.MagicMock()))

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.optimizely.make_tracked_session"
    )
    def test_pagination_stops_on_foreign_next_url(self, mock_session):
        # A next_url on an unexpected host must not be followed — it could
        # redirect our authenticated Bearer request and leak the token.
        evil_url = "https://evil.example.com/v2/projects?page=2&per_page=100"
        mock_session.return_value.get.side_effect = [
            _response([{"id": 1}], next_url=evil_url),
            _response([{"id": 2}]),
        ]

        batches = list(get_rows("token", "projects", mock.MagicMock()))

        assert [item["id"] for batch in batches for item in batch] == [1]
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.optimizely.make_tracked_session"
    )
    def test_empty_response_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        assert list(get_rows("token", "projects", mock.MagicMock())) == []


class TestOptimizelySourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = OPTIMIZELY_ENDPOINTS[endpoint]
        response = optimizely_source("token", endpoint, mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
