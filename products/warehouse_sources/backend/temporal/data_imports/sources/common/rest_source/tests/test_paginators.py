import json
from typing import Any

import pytest

from requests import PreparedRequest, Request, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    HeaderLinkPaginator,
    JSONLinkPaginator,
    JSONResponseCursorPaginator,
    JSONResponsePaginator,
    OffsetPaginator,
    PageNumberPaginator,
    SinglePagePaginator,
    single_entity_path,
)


def _make_response(json_body: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(json_body or {}).encode()
    resp.headers.update(headers or {})
    return resp


class TestSinglePagePaginator:
    def test_has_no_next_page_after_update(self) -> None:
        p = SinglePagePaginator()
        assert p.has_next_page is True
        p.update_state(_make_response(), [])
        assert p.has_next_page is False


class TestHeaderLinkPaginator:
    def test_follows_next_link(self) -> None:
        p = HeaderLinkPaginator()
        resp = _make_response()
        resp.headers["Link"] = '<https://api.example.com/page2>; rel="next"'
        p.update_state(resp)
        assert p.has_next_page is True
        req = Request(method="GET", url="https://api.example.com/page1")
        p.update_request(req)
        assert req.url == "https://api.example.com/page2"

    def test_stops_when_no_next(self) -> None:
        p = HeaderLinkPaginator()
        resp = _make_response()
        resp.headers["Link"] = '<https://api.example.com/page1>; rel="prev"'
        p.update_state(resp)
        assert p.has_next_page is False


class TestJSONResponsePaginator:
    def test_follows_next_url(self) -> None:
        p = JSONResponsePaginator(next_url_path="next")
        resp = _make_response({"next": "https://api.example.com/page2", "data": []})
        p.update_state(resp)
        assert p.has_next_page is True
        req = Request(method="GET", url="https://api.example.com/page1")
        p.update_request(req)
        assert req.url == "https://api.example.com/page2"

    def test_stops_when_next_is_null(self) -> None:
        p = JSONResponsePaginator(next_url_path="next")
        resp = _make_response({"next": None, "data": []})
        p.update_state(resp)
        assert p.has_next_page is False

    def test_json_link_paginator_is_alias(self) -> None:
        assert JSONLinkPaginator is JSONResponsePaginator

    def test_clears_original_params_when_following_next_url(self) -> None:
        # The initial request carries query params (e.g. per_page + an incremental
        # filter). Once the paginator switches to the server's self-contained next
        # URL, those params must be dropped — otherwise prepare_request re-appends
        # them to the already-complete URL, and an API that echoes the query back
        # into its next link compounds a duplicate every page (observed: an Intercom
        # activity_logs URL grew hundreds of `created_at_after=0` copies until 500).
        p = JSONResponsePaginator(next_url_path="pages.next")
        next_url = "https://api.example.com/logs?per_page=150&created_at_after=0&page=2"
        p.update_state(_make_response({"pages": {"next": next_url}, "activity_logs": []}))
        req = Request(
            method="GET",
            url="https://api.example.com/logs",
            params={"per_page": 150, "created_at_after": 0},
        )
        p.update_request(req)

        prepared: PreparedRequest = Session().prepare_request(req)
        assert prepared.url is not None
        assert prepared.url.count("created_at_after") == 1
        assert prepared.url.count("per_page") == 1

    def test_header_link_paginator_clears_original_params(self) -> None:
        p = HeaderLinkPaginator()
        resp = _make_response()
        resp.headers["Link"] = '<https://api.example.com/page2?per_page=150>; rel="next"'
        p.update_state(resp)
        req = Request(method="GET", url="https://api.example.com/page1", params={"per_page": 150})
        p.update_request(req)

        prepared: PreparedRequest = Session().prepare_request(req)
        assert prepared.url is not None
        assert prepared.url.count("per_page") == 1


class TestJSONResponseCursorPaginator:
    def test_follows_cursor(self) -> None:
        p = JSONResponseCursorPaginator(cursor_path="meta.next_cursor", cursor_param="cursor")
        resp = _make_response({"meta": {"next_cursor": "abc123"}, "data": []})
        p.update_state(resp)
        assert p.has_next_page is True
        req = Request(method="GET", url="https://api.example.com/items", params={})
        p.update_request(req)
        assert req.params["cursor"] == "abc123"

    def test_stops_when_cursor_is_none(self) -> None:
        p = JSONResponseCursorPaginator(cursor_path="meta.next_cursor")
        resp = _make_response({"meta": {"next_cursor": None}})
        p.update_state(resp)
        assert p.has_next_page is False


class TestOffsetPaginator:
    def test_increments_offset(self) -> None:
        p = OffsetPaginator(limit=10, offset=0)
        resp = _make_response({"total": 25})
        p.update_state(resp, data=[{"id": i} for i in range(10)])
        assert p.has_next_page is True
        assert p.offset == 10

        req = Request(method="GET", url="https://api.example.com/items", params={})
        p.update_request(req)
        assert req.params["offset"] == 10

    def test_stops_when_offset_exceeds_total(self) -> None:
        p = OffsetPaginator(limit=10, offset=0)
        resp = _make_response({"total": 5})
        p.update_state(resp, data=[{"id": i} for i in range(5)])
        assert p.has_next_page is False

    def test_stops_on_empty_page(self) -> None:
        p = OffsetPaginator(limit=10, offset=0)
        resp = _make_response({"total": 100})
        p.update_state(resp, data=[])
        assert p.has_next_page is False

    def test_init_request_sets_params(self) -> None:
        p = OffsetPaginator(limit=20, offset=5, offset_param="skip", limit_param="take")
        req = Request(method="GET", url="https://api.example.com/items", params={})
        p.init_request(req)
        assert req.params["skip"] == 5
        assert req.params["take"] == 20


class TestPageNumberPaginator:
    def test_increments_page(self) -> None:
        p = PageNumberPaginator(base_page=1, page=1, page_param="page")
        resp = _make_response({})
        p.update_state(resp, data=[{"id": 1}])
        assert p.has_next_page is True
        assert p.page == 2

    def test_stops_at_maximum_page(self) -> None:
        p = PageNumberPaginator(base_page=1, page=1, maximum_page=2)
        resp = _make_response({})
        p.update_state(resp, data=[{"id": 1}])
        p.update_state(resp, data=[{"id": 2}])
        assert p.page == 3
        assert p.has_next_page is False

    def test_stops_on_empty_page(self) -> None:
        p = PageNumberPaginator(base_page=1, page=1)
        resp = _make_response({})
        p.update_state(resp, data=[])
        assert p.has_next_page is False


class TestSingleEntityPath:
    @pytest.mark.parametrize(
        "path,expected",
        [
            ("users/{user_id}", True),
            ("users/{id}/profile", False),
            ("users", False),
            ("repos/{owner}/{repo}", True),
        ],
    )
    def test_detection(self, path: str, expected: bool) -> None:
        assert single_entity_path(path) == expected
