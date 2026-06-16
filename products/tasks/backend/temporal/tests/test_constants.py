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
def test_generic_override_collapses_all_modes():
    # The testing-only override forces a fast shutdown for every mode, so interactive
    # no longer gets its own (shorter) window — both resolve to INACTIVITY_TIMEOUT.
    assert resolve_inactivity_timeout("interactive") == INACTIVITY_TIMEOUT
    assert resolve_inactivity_timeout("interactive") == resolve_inactivity_timeout("background")
