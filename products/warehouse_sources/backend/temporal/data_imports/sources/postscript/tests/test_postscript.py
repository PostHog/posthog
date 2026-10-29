from datetime import UTC, datetime
from typing import Any, cast

from unittest.mock import Mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.postscript import (
    PostscriptSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postscript.postscript import (
    PostscriptResumeConfig,
    _format_postscript_datetime,
    _rest_api_client_config,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postscript.source import PostscriptSource


def _subscribers_response(total_pages: int) -> Mock:
    response = Mock()
    response.json.return_value = {"page_info": {"page": 1, "total_pages": total_pages}, "subscribers": []}
    return response


def _subscribers_page(total_pages: int, page: int = 1) -> ScriptedResponse:
    return ScriptedResponse(
        json={"page_info": {"page": page, "total_pages": total_pages}, "subscribers": [{"id": f"s_{page}"}]}
    )


def _driver() -> SourceDriver:
    return SourceDriver(PostscriptSource(), PostscriptSourceConfig(api_key="sk_postscript"))


class TestPostscriptTransport:
    @parameterized.expand(
        [
            ("naive_datetime", datetime(2026, 3, 1, 12, 30, 45, 999999), "2026-03-01T12:30:45Z"),
            ("aware_datetime", datetime(2026, 3, 1, 12, 30, 45, tzinfo=UTC), "2026-03-01T12:30:45Z"),
            ("passthrough_string", "1970-01-01T00:00:00Z", "1970-01-01T00:00:00Z"),
        ]
    )
    def test_format_postscript_datetime(self, _name, value, expected) -> None:
        assert _format_postscript_datetime(value) == expected

    @parameterized.expand(
        [
            ("updated_at", "updated_at"),
            ("created_at", "created_at"),
            # An unadvertised field has no matching `__gte` filter or `sort` value, so it would
            # 400 the API — fall back to the endpoint default instead.
            ("unknown_field_falls_back", "last_seen_at"),
            ("none_falls_back", None),
        ]
    )
    def test_subscribers_incremental_filter_and_sort_agree(self, _name, requested) -> None:
        resource = cast(
            Any,
            get_resource("subscribers", "v2", should_use_incremental_field=True, incremental_field_name=requested),
        )
        expected = requested if requested in ("updated_at", "created_at") else "updated_at"

        endpoint = resource["endpoint"]
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        assert endpoint["incremental"]["start_param"] == f"{expected}__gte"
        assert endpoint["incremental"]["cursor_path"] == expected
        # The sort column has to match the filtered column, or rows stop arriving in
        # watermark order and the asc checkpoint corrupts.
        assert endpoint["params"]["sort"] == f"{expected}__asc"

    @parameterized.expand([("incremental", True), ("full_refresh", False)])
    def test_keywords_never_paginates_or_filters(self, _name, should_use_incremental_field) -> None:
        resource = cast(Any, get_resource("keywords", "v2", should_use_incremental_field=should_use_incremental_field))
        endpoint = resource["endpoint"]
        # /keywords documents no query params: no page, no sort, no time filter.
        assert isinstance(endpoint["paginator"], SinglePagePaginator)
        assert endpoint["params"] == {}
        assert "incremental" not in endpoint
        assert resource["write_disposition"] == "replace"

    @parameterized.expand(
        [
            ("subscribers", "subscribers", "/api/v2/subscribers"),
            ("keywords", "keywords", "/api/v2/keywords"),
        ]
    )
    def test_resource_path_uses_resolved_api_version(self, _name, endpoint, expected_path) -> None:
        resource = cast(Any, get_resource(endpoint, "v2", should_use_incremental_field=False))
        assert resource["endpoint"]["path"] == expected_path
        assert resource["endpoint"]["data_selector"] == endpoint
        assert resource["endpoint"]["data_selector_required"] is True

    @parameterized.expand(
        [
            # page_info.total_pages is the authoritative stop signal, so a full last page
            # doesn't trigger one more (empty) request.
            ("last_page", 1, False),
            ("more_pages", 3, True),
        ]
    )
    def test_subscribers_paginator_stops_on_total_pages(self, _name, total_pages, expected_has_next) -> None:
        resource = cast(Any, get_resource("subscribers", "v2", should_use_incremental_field=False))
        paginator = resource["endpoint"]["paginator"]
        assert isinstance(paginator, PageNumberPaginator)

        request = Mock()
        request.params = None
        paginator.init_request(request)
        # Postscript pages are 1-based; starting at 0 would silently drop the first page.
        assert request.params == {"page": 1}

        paginator.update_state(_subscribers_response(total_pages), data=[{"id": "s_1"}])
        assert paginator.has_next_page is expected_has_next

    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid Postscript API key"),
            (403, False, "shop Private API Key"),
            (500, False, "unexpected status code"),
        ]
    )
    def test_validate_credentials_status_mapping(self, status, expected_valid, message_fragment) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            is_valid, message = validate_credentials("sk_postscript", "v2")

        assert is_valid is expected_valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message

        request = network.requests_log[0]
        assert request.url.startswith("https://api.postscript.io/api/v2/subscribers")
        assert request.headers["authorization"] == "Bearer sk_postscript"
        # The validation session must refuse redirects so a 3xx can't replay the token off-host.
        assert network.session_options[0]["allow_redirects"] is False
        assert network.session_options[0]["redact_values"] == ("sk_postscript",)

    def test_rest_client_config_pins_host_and_blocks_redirects(self) -> None:
        # A redirect off the Postscript host would otherwise replay the bearer token.
        config = _rest_api_client_config("sk_postscript")
        assert config["allowed_hosts"] == []
        assert config["allow_redirects"] is False
        assert config["auth"] == {"type": "bearer", "token": "sk_postscript"}

    def test_resume_state_seeds_paginator(self) -> None:
        result = _driver().run(
            "subscribers", [_subscribers_page(total_pages=7, page=7)], resume_state=PostscriptResumeConfig(page=7)
        )

        assert result.params("page")[0] == "7"

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _driver().run("subscribers", [_subscribers_page(total_pages=1)])

        assert result.params("page")[0] == "1"

    def test_resume_hook_saves_only_a_real_next_page(self) -> None:
        result = _driver().run(
            "subscribers",
            [
                _subscribers_page(total_pages=3, page=1),
                _subscribers_page(total_pages=3, page=2),
                _subscribers_page(total_pages=3, page=3),
            ],
        )

        assert result.params("page") == ["1", "2", "3"]
        # The paginator has no next page once it is on the last page — persisting then would
        # resume a finished sync onto a page that no longer exists.
        assert result.saved_states == [PostscriptResumeConfig(page=2), PostscriptResumeConfig(page=3)]

    @parameterized.expand(
        [
            ("subscribers", "subscribers", ["id"], ["created_at"]),
            ("keywords", "keywords", ["id"], ["created_at"]),
        ]
    )
    def test_source_response_shape(self, _name, endpoint, expected_keys, expected_partition_keys) -> None:
        page = (
            _subscribers_page(total_pages=1) if endpoint == "subscribers" else ScriptedResponse(json={"keywords": []})
        )

        response = _driver().run(endpoint, [page], should_use_incremental_field=True).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        # Every paginated request pins `<field>__asc`, so rows really do arrive oldest-first.
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == expected_partition_keys
