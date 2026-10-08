from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.motion.motion import (
    MotionResumeConfig,
    motion_source,
    validate_credentials,
)

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


class TestMotionSource:
    def test_a_saved_cursor_seeds_the_paginator(self) -> None:
        with mock.patch(f"{_MODULE}.rest_api_resource") as rest_api_resource:
            motion_source("key", "tasks", 1, "job", _manager(MotionResumeConfig(cursor="page-2")))

        assert rest_api_resource.call_args.kwargs["initial_paginator_state"] == {"cursor": "page-2"}

    @pytest.mark.parametrize(
        "state,expected_saves,expected_clears",
        [
            ({"cursor": "next-page"}, [mock.call(MotionResumeConfig(cursor="next-page"))], 0),
            ({}, [], 0),
            (None, [], 1),
        ],
    )
    def test_checkpoint_lifecycle(
        self,
        state: Optional[dict[str, Any]],
        expected_saves: list,
        expected_clears: int,
    ) -> None:
        manager = _manager()
        with mock.patch(f"{_MODULE}.rest_api_resource") as rest_api_resource:
            motion_source("key", "tasks", 1, "job", manager)

        rest_api_resource.call_args.kwargs["resume_hook"](state)
        assert manager.save_state.call_args_list == expected_saves
        assert manager.clear_state.call_count == expected_clears


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

    def test_an_unreachable_api_is_reported_rather_than_raised(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = ConnectionError("no route")

        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            valid, message = validate_credentials("key")

        assert valid is False
        assert message is not None
