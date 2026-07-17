import json
from collections.abc import Iterable
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.settings import (
    WEBFLOW_ENDPOINTS,
    collection_items_endpoint_config,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.webflow import (
    WebflowResumeConfig,
    _build_url,
    _extract_items,
    _normalize,
    _resolve_collection_id,
    get_rows,
    validate_credentials,
    webflow_source,
)

TRANSPORT = "products.warehouse_sources.backend.temporal.data_imports.sources.webflow.webflow.make_tracked_session"


def _make_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestExtractItems:
    @parameterized.expand(
        [
            ("configured_key", {"items": [{"id": 1}]}, "items", [{"id": 1}]),
            ("named_envelope", {"sites": [{"id": 1}]}, "sites", [{"id": 1}]),
            ("bare_list", [{"id": 1}], "items", [{"id": 1}]),
            ("missing_key_fallback", {"weird": [{"id": 7}], "pagination": {}}, "items", [{"id": 7}]),
            ("pagination_skipped", {"pagination": [1, 2], "orders": [{"id": 9}]}, "orders", [{"id": 9}]),
            ("nothing", {"pagination": {}}, "items", []),
            ("not_a_dict", 5, "items", []),
        ]
    )
    def test_extract_items(self, _name: str, data: Any, data_key: str, expected: list[dict[str, Any]]) -> None:
        assert _extract_items(data, data_key) == expected


class TestNormalize:
    def test_flattens_nested_product(self) -> None:
        config = WEBFLOW_ENDPOINTS["products"]
        item = {
            "product": {"id": "p1", "createdOn": "2026-01-01", "fieldData": {"name": "Shoe"}},
            "skus": [{"id": "s1"}],
        }
        normalized = _normalize(item, config)
        assert normalized["id"] == "p1"
        assert normalized["createdOn"] == "2026-01-01"
        assert normalized["skus"] == [{"id": "s1"}]

    def test_passthrough_without_flatten_key(self) -> None:
        config = WEBFLOW_ENDPOINTS["pages"]
        item = {"id": "page1", "createdOn": "2026-01-01"}
        assert _normalize(item, config) == item

    def test_passthrough_when_flatten_key_absent(self) -> None:
        config = WEBFLOW_ENDPOINTS["products"]
        item = {"id": "p1"}  # no "product" key
        assert _normalize(item, config) == item


class TestBuildUrl:
    def test_paginated_endpoint(self) -> None:
        url = _build_url(WEBFLOW_ENDPOINTS["pages"], "site-1", 100)
        assert url == "https://api.webflow.com/v2/sites/site-1/pages?limit=100&offset=100"

    def test_non_paginated_endpoint_has_no_query(self) -> None:
        url = _build_url(WEBFLOW_ENDPOINTS["collections"], "site-1", 0)
        assert url == "https://api.webflow.com/v2/sites/site-1/collections"

    def test_sites_endpoint_is_site_scoped(self) -> None:
        url = _build_url(WEBFLOW_ENDPOINTS["sites"], "site-1", 0)
        assert url == "https://api.webflow.com/v2/sites/site-1"

    def test_collection_items_includes_stable_sort(self) -> None:
        url = _build_url(collection_items_endpoint_config("col-99"), "site-1", 0)
        assert url == (
            "https://api.webflow.com/v2/collections/col-99/items?limit=100&offset=0&sortBy=createdOn&sortOrder=asc"
        )

    def test_site_id_with_path_delimiters_is_encoded_into_a_single_segment(self) -> None:
        # A site_id containing path/query delimiters must not redirect the request to
        # an account-level (or otherwise unintended) Webflow endpoint.
        url = _build_url(WEBFLOW_ENDPOINTS["pages"], "../../sites", 0)
        assert url == "https://api.webflow.com/v2/sites/..%2F..%2Fsites/pages?limit=100&offset=0"


def _drive_rows(
    config: Any, manager: Any, responses: list[Response], schema_name: str = "pages"
) -> tuple[list[Any], list[str]]:
    sent_urls: list[str] = []
    response_iter = iter(responses)

    def fake_get(url: str, *_args: Any, **_kwargs: Any) -> Response:
        sent_urls.append(url)
        return next(response_iter)

    with patch(TRANSPORT) as MockSession:
        mock_session = MockSession.return_value
        mock_session.get.side_effect = fake_get
        rows = list(
            get_rows(
                api_token="token",
                site_id="site-1",
                schema_name=schema_name,
                config=config,
                logger=MagicMock(),
                resumable_source_manager=manager,
            )
        )
    return rows, sent_urls


class TestGetRows:
    def test_fresh_run_paginates_until_total_and_saves_after_each_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [
            _make_response({"pages": [{"id": "a"}], "pagination": {"total": 250, "offset": 0}}),
            _make_response({"pages": [{"id": "b"}], "pagination": {"total": 250, "offset": 100}}),
            _make_response({"pages": [{"id": "c"}], "pagination": {"total": 250, "offset": 200}}),
        ]
        rows, sent_urls = _drive_rows(WEBFLOW_ENDPOINTS["pages"], manager, responses)

        assert rows == [[{"id": "a"}], [{"id": "b"}], [{"id": "c"}]]
        assert [u.split("offset=")[1].split("&")[0] for u in sent_urls] == ["0", "100", "200"]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [WebflowResumeConfig(offset=100), WebflowResumeConfig(offset=200)]

    def test_resume_starts_from_saved_offset(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = WebflowResumeConfig(offset=200)
        responses = [_make_response({"pages": [{"id": "c"}], "pagination": {"total": 250, "offset": 200}})]

        rows, sent_urls = _drive_rows(WEBFLOW_ENDPOINTS["pages"], manager, responses)

        assert rows == [[{"id": "c"}]]
        assert "offset=200" in sent_urls[0]
        manager.load_state.assert_called_once()

    def test_terminates_on_short_page_without_pagination_block(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [_make_response({"pages": [{"id": "only"}]})]

        rows, _ = _drive_rows(WEBFLOW_ENDPOINTS["pages"], manager, responses)

        assert rows == [[{"id": "only"}]]
        manager.save_state.assert_not_called()

    def test_single_object_endpoint_wraps_one_row_and_fetches_once(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        # /sites/{site_id} returns a single site object, not a list envelope.
        responses = [_make_response({"id": "s1", "displayName": "My site"})]

        rows, sent_urls = _drive_rows(WEBFLOW_ENDPOINTS["sites"], manager, responses, schema_name="sites")

        assert rows == [[{"id": "s1", "displayName": "My site"}]]
        assert sent_urls == ["https://api.webflow.com/v2/sites/site-1"]
        manager.save_state.assert_not_called()

    def test_paginated_endpoint_with_bare_list_response_does_not_crash(self) -> None:
        # A paginated endpoint that returns a bare list (no pagination block) must
        # fall through to short-page termination instead of crashing on data.get(...).
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [_make_response([{"id": "a"}, {"id": "b"}])]

        rows, sent_urls = _drive_rows(WEBFLOW_ENDPOINTS["pages"], manager, responses)

        assert rows == [[{"id": "a"}, {"id": "b"}]]
        assert len(sent_urls) == 1
        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [_make_response({"pages": [{"id": "a"}]})]

        _drive_rows(WEBFLOW_ENDPOINTS["pages"], manager, responses)

        manager.load_state.assert_not_called()


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("bad_token", 401, None, False),
            ("missing_scope_at_create", 403, None, True),
            ("missing_scope_for_schema", 403, "products", False),
            ("site_not_found", 404, None, False),
            ("server_error", 500, None, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, schema_name: str | None, expected_ok: bool) -> None:
        with patch(TRANSPORT) as MockSession:
            MockSession.return_value.get.return_value = _make_response({"message": "nope"}, status_code=status_code)
            ok, _error = validate_credentials("token", "site-1", schema_name)
        assert ok is expected_ok

    def test_request_exception_returns_error(self) -> None:
        with patch(TRANSPORT) as MockSession:
            MockSession.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
            ok, error = validate_credentials("token", "site-1")
        assert ok is False
        assert error == "boom"


class TestResolveCollectionId:
    def test_resolves_by_slug(self) -> None:
        with patch(TRANSPORT) as MockSession:
            MockSession.return_value.get.return_value = _make_response(
                {"collections": [{"id": "c1", "slug": "blog"}, {"id": "c2", "slug": "authors"}]}
            )
            assert _resolve_collection_id("token", "site-1", "collection_authors") == "c2"

    def test_raises_when_collection_missing(self) -> None:
        with patch(TRANSPORT) as MockSession:
            MockSession.return_value.get.return_value = _make_response({"collections": [{"id": "c1", "slug": "blog"}]})
            with pytest.raises(ValueError):
                _resolve_collection_id("token", "site-1", "collection_missing")


class TestWebflowSource:
    @parameterized.expand(
        [
            ("pages", "pages", ["id"]),
            ("orders", "orders", ["orderId"]),
            ("products", "products", ["id"]),
        ]
    )
    def test_source_response_primary_keys(self, _name: str, schema_name: str, expected_pks: list[str]) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        response = webflow_source("token", "site-1", schema_name, logger=MagicMock(), resumable_source_manager=manager)
        assert response.name == schema_name
        assert response.primary_keys == expected_pks
        assert response.partition_mode == "datetime"

    def test_collection_schema_resolves_collection_id(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.webflow.webflow._resolve_collection_id",
            return_value="c1",
        ) as mock_resolve:
            response = webflow_source(
                "token", "site-1", "collection_blog", logger=MagicMock(), resumable_source_manager=manager
            )
        mock_resolve.assert_called_once_with("token", "site-1", "collection_blog")
        assert response.name == "collection_blog"
        assert response.primary_keys == ["id"]

    def test_items_callable_lazy(self) -> None:
        # Building the SourceResponse must not touch the network; only iterating items() should.
        manager = MagicMock(spec=ResumableSourceManager)
        response = webflow_source("token", "site-1", "pages", logger=MagicMock(), resumable_source_manager=manager)
        assert callable(response.items)
        assert isinstance(response.items(), Iterable)
