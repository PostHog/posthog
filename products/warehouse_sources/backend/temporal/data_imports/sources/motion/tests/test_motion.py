from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.motion.motion import (
    MotionResumeConfig,
    get_resource,
    motion_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.motion.settings import MOTION_ENDPOINTS

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.motion.motion"


def _manager(resume_state: MotionResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(status_code: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    return response


class TestMotionResources:
    @pytest.mark.parametrize("endpoint", sorted(MOTION_ENDPOINTS))
    def test_rows_are_selected_from_the_endpoints_own_envelope(self, endpoint: str) -> None:
        # Motion wraps rows in a per-resource key next to `meta`, so a wrong selector yields nothing.
        resource_endpoint = get_resource(endpoint)["endpoint"]
        assert resource_endpoint is not None and not isinstance(resource_endpoint, str)
        assert resource_endpoint["data_selector"] == f"{MOTION_ENDPOINTS[endpoint].data_key}[*]"

    def test_tasks_ask_for_every_status(self) -> None:
        # Without this param Motion omits completed work, which would silently truncate the table.
        resource_endpoint = get_resource("tasks")["endpoint"]
        assert resource_endpoint is not None and not isinstance(resource_endpoint, str)
        assert resource_endpoint["params"] == {"includeAllStatuses": "true"}


class TestMotionSource:
    def test_pages_are_walked_with_motions_cursor_field(self) -> None:
        with mock.patch(f"{_MODULE}.rest_api_resource") as rest_api_resource:
            motion_source("key", "tasks", 1, "job", _manager())

        paginator = rest_api_resource.call_args.args[0]["client"]["paginator"]
        assert isinstance(paginator, JSONResponseCursorPaginator)
        assert paginator.cursor_path == "meta.nextCursor"
        assert paginator.cursor_param == "cursor"

    def test_requests_have_a_timeout(self) -> None:
        with mock.patch(f"{_MODULE}.rest_api_resource") as rest_api_resource:
            motion_source("key", "tasks", 1, "job", _manager())

        assert rest_api_resource.call_args.args[0]["client"]["request_timeout"] == 30

    def test_the_key_rides_the_header_motion_expects(self) -> None:
        with mock.patch(f"{_MODULE}.rest_api_resource") as rest_api_resource:
            motion_source("key", "tasks", 1, "job", _manager())

        assert rest_api_resource.call_args.args[0]["client"]["auth"] == {
            "type": "api_key",
            "api_key": "key",
            "name": "X-API-Key",
            "location": "header",
        }

    def test_a_saved_cursor_seeds_the_paginator(self) -> None:
        with mock.patch(f"{_MODULE}.rest_api_resource") as rest_api_resource:
            motion_source("key", "tasks", 1, "job", _manager(MotionResumeConfig(cursor="page-2")))

        assert rest_api_resource.call_args.kwargs["initial_paginator_state"] == {"cursor": "page-2"}

    def test_a_fresh_run_seeds_no_paginator_state(self) -> None:
        with mock.patch(f"{_MODULE}.rest_api_resource") as rest_api_resource:
            motion_source("key", "tasks", 1, "job", _manager())

        assert rest_api_resource.call_args.kwargs["initial_paginator_state"] is None

    @pytest.mark.parametrize(
        "state,expected_saves",
        [({"cursor": "next-page"}, [mock.call(MotionResumeConfig(cursor="next-page"))]), ({}, []), (None, [])],
    )
    def test_only_a_real_cursor_is_checkpointed(self, state: Optional[dict[str, Any]], expected_saves: list) -> None:
        manager = _manager()
        with mock.patch(f"{_MODULE}.rest_api_resource") as rest_api_resource:
            motion_source("key", "tasks", 1, "job", manager)

        rest_api_resource.call_args.kwargs["resume_hook"](state)
        assert manager.save_state.call_args_list == expected_saves


class TestMotionCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_valid",
        [(200, True), (401, False), (403, False), (429, False), (500, False)],
    )
    def test_status_maps_to_a_verdict(self, status_code: int, expected_valid: bool) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(status_code)

        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            valid, message = validate_credentials("key")

        assert valid is expected_valid
        assert (message is None) is expected_valid

    def test_a_rate_limited_key_says_to_wait(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(429)

        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            _, message = validate_credentials("key")

        assert message is not None and "rate limiting" in message

    def test_an_unreachable_api_is_reported_rather_than_raised(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = ConnectionError("no route")

        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            valid, message = validate_credentials("key")

        assert valid is False
        assert message is not None
