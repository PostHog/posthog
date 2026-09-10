from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teachable.teachable import (
    TeachableResumeConfig,
    TeachableUsersPaginator,
    _format_teachable_datetime,
    _rest_api_client_config,
    get_resource,
    teachable_source,
    validate_credentials,
)


class _FakeDltResource:
    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


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
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.teachable.teachable.make_tracked_session")
    def test_validate_credentials_status_mapping(self, status, expected_valid, message_fragment, mock_session) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=status)

        is_valid, message = validate_credentials("teachable-key")

        assert is_valid is expected_valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://developers.teachable.com/v1/courses"
        assert call.kwargs["headers"]["apiKey"] == "teachable-key"
        # The validation session must refuse redirects so a 3xx can't replay the apiKey off-host.
        assert mock_session.call_args.kwargs["allow_redirects"] is False

    def test_rest_client_config_pins_host_and_blocks_redirects(self) -> None:
        # A redirect off the Teachable host would otherwise replay the apiKey credential header.
        config = _rest_api_client_config("teachable-key")
        assert config["allowed_hosts"] == []
        assert config["allow_redirects"] is False

    def test_get_resource_transactions_incremental(self) -> None:
        resource = cast(dict[str, Any], get_resource("transactions", should_use_incremental_field=True))
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        incremental = resource["endpoint"]["incremental"]
        assert incremental["start_param"] == "start"
        assert incremental["cursor_path"] == "created_at"
        assert resource["endpoint"]["data_selector"] == "transactions"

    def test_get_resource_transactions_full_refresh(self) -> None:
        resource = cast(dict[str, Any], get_resource("transactions", should_use_incremental_field=False))
        assert resource["write_disposition"] == "replace"
        assert "incremental" not in resource["endpoint"]

    def test_get_resource_users_uses_search_after_paginator(self) -> None:
        resource = cast(dict[str, Any], get_resource("users", should_use_incremental_field=False))
        assert isinstance(resource["endpoint"]["paginator"], TeachableUsersPaginator)

    def test_get_resource_page_paginator_stops_on_number_of_pages(self) -> None:
        resource = cast(dict[str, Any], get_resource("courses", should_use_incremental_field=False))
        paginator = resource["endpoint"]["paginator"]
        assert isinstance(paginator, PageNumberPaginator)

        response = Mock()
        response.json.return_value = {"courses": [], "meta": {"number_of_pages": 1}}
        paginator.update_state(response, data=[{"id": 1}])
        assert paginator.has_next_page is False

    def test_get_resource_rejects_fanout_endpoint(self) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource("course_enrollments", should_use_incremental_field=False)

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_enrollments_fanout_row_format(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("courses", [{"id": 11, "name": "Course"}]),
            _FakeDltResource(
                "course_enrollments",
                [{"user_id": 7, "enrolled_at": "2026-01-01T00:00:00Z", "_courses_id": 11}],
            ),
        ]

        response = teachable_source(
            api_key="key",
            endpoint="course_enrollments",
            team_id=1,
            job_id="job-1",
        )

        rows = list(cast(Any, response.items()))
        assert rows == [{"user_id": 7, "enrolled_at": "2026-01-01T00:00:00Z", "course_id": 11}]
        # user_id is only unique per course, so the parent course id is part of the key.
        assert response.primary_keys == ["course_id", "user_id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["enrolled_at"]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.teachable.teachable.build_dependent_resource"
    )
    def test_enrollments_fanout_wiring(self, mock_build_dependent_resource) -> None:
        mock_build_dependent_resource.return_value = iter([])

        teachable_source(api_key="key", endpoint="course_enrollments", team_id=1, job_id="job-1")

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["page_size_param"] == "per"
        assert kwargs["parent_endpoint_extra"]["data_selector"] == "courses"
        assert kwargs["child_endpoint_extra"]["data_selector"] == "enrollments"
        assert kwargs["child_params_extra"] == {"sort_direction": "asc"}

    @parameterized.expand(
        [
            ("page_endpoint", TeachableResumeConfig(page=5), {"page": 5}),
            ("users_endpoint", TeachableResumeConfig(search_after=99), {"search_after": 99}),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.teachable.teachable.rest_api_resource")
    def test_resume_state_seeds_paginator(self, _name, saved_state, expected_initial, mock_rest_api_resource) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = saved_state

        teachable_source(
            api_key="key",
            endpoint="users" if saved_state.search_after else "courses",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        assert mock_rest_api_resource.call_args.kwargs["initial_paginator_state"] == expected_initial

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.teachable.teachable.rest_api_resource")
    def test_resume_hook_saves_state_only_when_resumable(self, mock_rest_api_resource) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = False

        teachable_source(
            api_key="key",
            endpoint="courses",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        resume_hook = mock_rest_api_resource.call_args.kwargs["resume_hook"]

        resume_hook({"page": 3})
        assert manager.save_state.call_args.args[0] == TeachableResumeConfig(page=3, search_after=None)

        manager.save_state.reset_mock()
        resume_hook(None)
        resume_hook({})
        manager.save_state.assert_not_called()

    @parameterized.expand(
        [
            ("incremental_desc", True, "desc"),
            ("full_refresh_asc", False, "asc"),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.teachable.teachable.rest_api_resource")
    def test_transactions_sort_mode(
        self, _name, should_use_incremental_field, expected, mock_rest_api_resource
    ) -> None:
        response = teachable_source(
            api_key="key",
            endpoint="transactions",
            team_id=1,
            job_id="job-1",
            should_use_incremental_field=should_use_incremental_field,
        )
        assert response.sort_mode == expected
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created_at"]
