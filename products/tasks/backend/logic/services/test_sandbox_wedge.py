import pytest

from products.tasks.backend.logic.services.sandbox_wedge import (
    describe_exit_code,
    killing_signal_name,
    sandbox_wedge_verdict,
)


@pytest.mark.parametrize(
    "exit_code,expected_signal,expected_description",
    [
        (1, None, "1"),
        (128, None, "128"),
        (137, "SIGKILL", "137 (SIGKILL)"),
        (143, "SIGTERM", "143 (SIGTERM)"),
        (300, None, "300"),
    ],
)
def test_signal_classification(exit_code, expected_signal, expected_description):
    assert killing_signal_name(exit_code) == expected_signal
    assert describe_exit_code(exit_code) == expected_description


@pytest.mark.parametrize(
    "probe,expected",
    [
        ({"oom_kill": "2"}, "oom_seen"),
        (
            {"oom_kill": "2", "pids_current": "50", "pids_max": "50"},
            "pids_exhausted",
        ),
        ({"oom_kill": "0", "tmp_available_kb": "0"}, "disk_full"),
        ({"oom_kill": "0", "tmp_available_kb": "10"}, "unknown"),
    ],
)
def test_sandbox_wedge_verdict(probe, expected):
    assert sandbox_wedge_verdict(probe) == expected
