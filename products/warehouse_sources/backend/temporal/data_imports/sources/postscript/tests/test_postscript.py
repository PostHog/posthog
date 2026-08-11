from datetime import UTC, datetime
from typing import Any, cast

from unittest.mock import MagicMock, Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postscript.postscript import (
    PostscriptResumeConfig,
    _format_postscript_datetime,
    _rest_api_client_config,
    get_resource,
    postscript_source,
    validate_credentials,
)


def _subscribers_response(total_pages: int) -> Mock:
    response = Mock()
    response.json.return_value = {"page_info": {"page": 1, "total_pages": total_pages}, "subscribers": []}
    return response


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

    def test_subscribers_full_refresh_pins_stable_sort(self) -> None:
        resource = cast(Any, get_resource("subscribers", "v2", should_use_incremental_field=False))
        endpoint = resource["endpoint"]
        assert resource["write_disposition"] == "replace"
        assert "incremental" not in endpoint
        # created_at is immutable, so page boundaries stay stable while rows are written
        # during the sync.
        assert endpoint["params"]["sort"] == "created_at__asc"

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
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postscript.postscript.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(self, status, expected_valid, message_fragment, mock_session) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=status)

        is_valid, message = validate_credentials("sk_postscript", "v2")

        assert is_valid is expected_valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.postscript.io/api/v2/subscribers"
        assert call.kwargs["headers"]["Authorization"] == "Bearer sk_postscript"
        # The validation session must refuse redirects so a 3xx can't replay the token off-host.
        assert mock_session.call_args.kwargs["allow_redirects"] is False
        assert mock_session.call_args.kwargs["redact_values"] == ("sk_postscript",)

    def test_rest_client_config_pins_host_and_blocks_redirects(self) -> None:
        # A redirect off the Postscript host would otherwise replay the bearer token.
        config = _rest_api_client_config("sk_postscript")
        assert config["allowed_hosts"] == []
        assert config["allow_redirects"] is False
        assert config["auth"] == {"type": "bearer", "token": "sk_postscript"}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postscript.postscript.rest_api_resource")
    def test_resume_state_seeds_paginator(self, mock_rest_api_resource) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = PostscriptResumeConfig(page=7)

        postscript_source(
            api_key="sk_postscript",
            endpoint="subscribers",
            api_version="v2",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        assert mock_rest_api_resource.call_args.kwargs["initial_paginator_state"] == {"page": 7}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postscript.postscript.rest_api_resource")
    def test_resume_hook_saves_only_a_real_next_page(self, mock_rest_api_resource) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = False

        postscript_source(
            api_key="sk_postscript",
            endpoint="subscribers",
            api_version="v2",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        resume_hook = mock_rest_api_resource.call_args.kwargs["resume_hook"]

        resume_hook({"page": 3})
        assert manager.save_state.call_args.args[0] == PostscriptResumeConfig(page=3)

        manager.save_state.reset_mock()
        # The paginator returns None once it is on the last page — persisting then would
        # resume a finished sync onto a page that no longer exists.
        resume_hook(None)
        resume_hook({})
        manager.save_state.assert_not_called()

    @parameterized.expand(
        [
            ("subscribers", "subscribers", ["id"], ["created_at"]),
            ("keywords", "keywords", ["id"], ["created_at"]),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postscript.postscript.rest_api_resource")
    def test_source_response_shape(
        self, _name, endpoint, expected_keys, expected_partition_keys, mock_rest_api_resource
    ) -> None:
        response = postscript_source(
            api_key="sk_postscript",
            endpoint=endpoint,
            api_version="v2",
            team_id=1,
            job_id="job-1",
            should_use_incremental_field=True,
        )

        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        # Every paginated request pins `<field>__asc`, so rows really do arrive oldest-first.
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == expected_partition_keys
