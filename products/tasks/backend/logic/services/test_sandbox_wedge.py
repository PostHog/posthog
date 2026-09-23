import pytest

from products.tasks.backend.logic.services.sandbox_wedge import killing_signal_name, sandbox_wedge_verdict


@pytest.mark.parametrize(
    "exit_code,expected_signal",
    [
        (1, None),
        (128, None),
        (137, "SIGKILL"),
        (143, "SIGTERM"),
        (300, None),
    ],
)
def test_signal_classification(exit_code, expected_signal):
    assert killing_signal_name(exit_code) == expected_signal


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
