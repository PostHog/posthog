from datetime import timedelta

import pytest

from django.test import override_settings

from products.tasks.backend.temporal.constants import (
    INACTIVITY_TIMEOUT,
    INTERACTIVE_INACTIVITY_TIMEOUT,
    resolve_inactivity_timeout,
)


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("interactive", INTERACTIVE_INACTIVITY_TIMEOUT),
        ("background", INACTIVITY_TIMEOUT),
        ("", INACTIVITY_TIMEOUT),
        ("unknown", INACTIVITY_TIMEOUT),
    ],
)
def test_resolve_inactivity_timeout_by_mode(mode: str, expected: timedelta):
    assert resolve_inactivity_timeout(mode) == expected


def test_interactive_window_is_shorter_than_background():
    assert INTERACTIVE_INACTIVITY_TIMEOUT < INACTIVITY_TIMEOUT


def test_interactive_default_is_ten_minutes():
    assert INTERACTIVE_INACTIVITY_TIMEOUT == timedelta(minutes=10)


@override_settings(TASKS_INACTIVITY_TIMEOUT_SECONDS=30)
def test_background_override_does_not_affect_interactive():
    # TASKS_INACTIVITY_TIMEOUT_SECONDS governs background runs only — interactive keeps
    # its own window even when the background override is set.
    assert resolve_inactivity_timeout("interactive") == INTERACTIVE_INACTIVITY_TIMEOUT
    assert resolve_inactivity_timeout("interactive") != resolve_inactivity_timeout("background")
