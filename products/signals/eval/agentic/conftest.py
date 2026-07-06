"""pytest options/fixtures for the agentic evals.

These extend the parent eval conftest. Defaults keep the pytest entrypoints deterministic
(replay, no judge, no capture) so they run anywhere; flags opt into the heavier paths.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser) -> None:
    group = parser.getgroup("signals-agentic-eval")
    group.addoption("--eval-mode", default="replay", choices=["replay", "record", "live"])
    group.addoption("--judge", action="store_true", default=False, help="Enable LLM-judge scorers.")
    group.addoption("--capture-results", action="store_true", default=False, help="Emit $ai_evaluation events.")
    group.addoption("--eval-team-id", type=int, default=1)
    group.addoption("--eval-user-id", type=int, default=1)
    group.addoption("--case-filter", default=None)
    group.addoption("--min-pass-rate", type=float, default=None)


@pytest.fixture
def eval_opts(request) -> dict:
    opt = request.config.getoption
    return {
        "mode": opt("--eval-mode"),
        "judge_enabled": opt("--judge"),
        "capture": opt("--capture-results"),
        "team_id": opt("--eval-team-id"),
        "user_id": opt("--eval-user-id"),
        "case_filter": opt("--case-filter"),
        "min_pass_rate": opt("--min-pass-rate"),
    }
