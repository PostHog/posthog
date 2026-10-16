from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import Mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.teachable import (
    TeachableSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teachable.source import TeachableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.teachable.teachable import (
    TeachableResumeConfig,
    TeachableUsersPaginator,
    _format_teachable_datetime,
    _rest_api_client_config,
    get_resource,
    validate_credentials,
)


def _driver() -> SourceDriver:
    return SourceDriver(TeachableSource(), TeachableSourceConfig(api_key="key"))


def _users_response(meta: dict[str, Any]) -> Mock:
    response = Mock()
    response.json.return_value = {"users": [], "meta": meta}
    return response


class TestTeachableTransport:
    @parameterized.expand(
        [
            # has_more_results=True from a search_after response — keep paging.
            ("has_more", {"per_page": 2, "has_more_results": True, "search_after": [20]}, 2, True),
            # has_more_results=False — stop even on a full page.
            ("no_more", {"per_page": 2, "has_more_results": False, "search_after": [20]}, 2, False),
            # Page-mode meta (no has_more_results): a page matching the server's per_page keeps going,
            # even when the server clamped our requested `per` below what we asked for.
            ("server_clamped_full_page", {"per_page": 2, "number_of_pages": 5}, 2, True),
            # Page-mode meta: a page shorter than the server's per_page is terminal.
            ("short_page", {"per_page": 2, "number_of_pages": 1}, 1, False),
        ]
    )
    def test_users_paginator_termination(self, _name, meta, row_count, expected_has_next) -> None:
        paginator = TeachableUsersPaginator(per=100)
        data = [{"id": i + 1, "name": "u", "email": "u@example.com"} for i in range(row_count)]
        paginator.update_state(_users_response(meta), data=data)
        assert paginator.has_next_page is expected_has_next

    def test_users_paginator_empty_page_is_terminal(self) -> None:
        paginator = TeachableUsersPaginator(per=100)
        paginator.update_state(_users_response({"per_page": 100}), data=[])
        assert paginator.has_next_page is False

    def test_users_paginator_advances_search_after_cursor(self) -> None:
        paginator = TeachableUsersPaginator(per=100)
        request = Mock()
        request.params = None
        paginator.init_request(request)
        assert request.params == {"per": 100}

        # No meta cursor — fall back to the last row's id.
        data = [{"id": 5}, {"id": 9}]
        paginator.update_state(_users_response({"per_page": 2}), data=data)
        paginator.update_request(request)
        assert request.params["search_after"] == 9

        # A server-provided meta cursor takes precedence over the last row id.
        paginator.update_state(
            _users_response({"per_page": 2, "has_more_results": True, "search_after": [42]}),
            data=[{"id": 30}, {"id": 41}],
        )
        paginator.update_request(request)
        assert request.params["search_after"] == 42

    def test_users_paginator_resume_state_round_trip(self) -> None:
        paginator = TeachableUsersPaginator(per=100)
        paginator.update_state(
            _users_response({"per_page": 1, "has_more_results": True, "search_after": [77]}),
            data=[{"id": 77}],
        )
        state = paginator.get_resume_state()
        assert state == {"search_after": 77}

        resumed = TeachableUsersPaginator(per=100)
        resumed.set_resume_state(cast(dict[str, Any], state))
        request = Mock()
        request.params = None
        resumed.init_request(request)
        assert request.params["search_after"] == 77

    @parameterized.expand(
        [
            ("naive_datetime", datetime(2026, 3, 1, 12, 30, 45, 999999), "2026-03-01T12:30:45Z"),
            ("aware_datetime", datetime(2026, 3, 1, 12, 30, 45, tzinfo=UTC), "2026-03-01T12:30:45Z"),
            ("passthrough_string", "1970-01-01T00:00:00Z", "1970-01-01T00:00:00Z"),
        ]
    )
    def test_format_teachable_datetime(self, _name, value, expected) -> None:
        assert _format_teachable_datetime(value) == expected

    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid Teachable API key"),
            (403, False, "Growth plan"),
            (500, False, "unexpected status code"),
        ]
    )
    def test_validate_credentials_status_mapping(self, status, expected_valid, message_fragment) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            is_valid, message = validate_credentials("teachable-key")

        assert is_valid is expected_valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message

        request = network.requests_log[0]
        assert request.origin + request.path == "https://developers.teachable.com/v1/courses"
        assert request.headers["apikey"] == "teachable-key"
        # The validation session must refuse redirects so a 3xx can't replay the apiKey off-host.
        assert network.session_options[0]["allow_redirects"] is False

    def test_rest_client_config_pins_host_and_blocks_redirects(self) -> None:
        # A redirect off the Teachable host would otherwise replay the apiKey credential header.
        config = _rest_api_client_config("teachable-key")
        assert config["allowed_hosts"] == []
        assert config["allow_redirects"] is False

    def test_get_resource_rejects_fanout_endpoint(self) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource("course_enrollments", should_use_incremental_field=False)

    def test_enrollments_fanout_row_format(self) -> None:
        result = _driver().run(
            "course_enrollments",
            route(
                {
                    "/v1/courses": [ScriptedResponse(json={"courses": [{"id": 11, "name": "Course"}]})],
                    "/v1/courses/11/enrollments": [
                        ScriptedResponse(json={"enrollments": [{"user_id": 7, "enrolled_at": "2026-01-01T00:00:00Z"}]})
                    ],
                }
            ),
        )

        assert result.rows == [{"user_id": 7, "enrolled_at": "2026-01-01T00:00:00Z", "course_id": 11}]
        assert result.response is not None
        # user_id is only unique per course, so the parent course id is part of the key.
        assert result.response.primary_keys == ["course_id", "user_id"]
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == ["enrolled_at"]

    @parameterized.expand(
        [
            ("page_endpoint", "courses", TeachableResumeConfig(page=5), "page", "5"),
            ("users_endpoint", "users", TeachableResumeConfig(search_after=99), "search_after", "99"),
        ]
    )
    def test_resume_state_seeds_paginator(self, _name, endpoint, saved_state, param, expected) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={endpoint: [{"id": 100}], "meta": {"number_of_pages": 5, "per_page": 100}})],
            resume_state=saved_state,
        )

        assert result.requests[0].param(param) == expected

    def test_resume_hook_saves_state_only_when_resumable(self) -> None:
        result = _driver().run(
            "courses",
            [
                ScriptedResponse(json={"courses": [{"id": 1}], "meta": {"number_of_pages": 2}}),
                ScriptedResponse(json={"courses": [{"id": 2}], "meta": {"number_of_pages": 2}}),
            ],
        )

        # The cursor is saved while another page remains, and not after the last page.
        assert result.saved_states == [TeachableResumeConfig(page=2, search_after=None)]

    @parameterized.expand(
        [
            ("incremental_desc", True, "desc"),
            ("full_refresh_asc", False, "asc"),
        ]
    )
    def test_transactions_sort_mode(self, _name, should_use_incremental_field, expected) -> None:
        result = _driver().run(
            "transactions",
            always(ScriptedResponse(json={"transactions": [], "meta": {"number_of_pages": 1}})),
            should_use_incremental_field=should_use_incremental_field,
        )
        response = result.response
        assert response is not None
        assert response.sort_mode == expected
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created_at"]
