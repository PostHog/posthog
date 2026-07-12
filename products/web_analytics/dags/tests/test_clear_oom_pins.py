import dagster

from posthog import redis

from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import (
    _oom_pin_key,
    is_team_oom_pinned,
    pin_team_oom,
)
from products.web_analytics.dags.clear_oom_pins import web_analytics_clear_precompute_oom_pins_job

TEAMS = (901901, 901902)


def _run(config: dict) -> dagster.ExecuteInProcessResult:
    return web_analytics_clear_precompute_oom_pins_job.execute_in_process(
        run_config={"ops": {"clear_precompute_oom_pins_op": {"config": config}}},
        raise_on_error=False,
    )


class TestClearOomPinsJob:
    def setup_method(self):
        for team_id in TEAMS:
            pin_team_oom(team_id)

    def teardown_method(self):
        for team_id in TEAMS:
            redis.get_client().delete(_oom_pin_key(team_id))

    def test_dry_run_clears_nothing(self):
        result = _run({})
        assert result.success
        assert all(is_team_oom_pinned(t) for t in TEAMS)

    def test_clears_single_team(self):
        result = _run({"team_id": TEAMS[0]})
        assert result.success
        assert is_team_oom_pinned(TEAMS[0]) is False
        assert is_team_oom_pinned(TEAMS[1]) is True

    def test_clear_all(self):
        result = _run({"clear_all": True})
        assert result.success
        assert not any(is_team_oom_pinned(t) for t in TEAMS)

    def test_conflicting_config_fails_and_clears_nothing(self):
        result = _run({"team_id": TEAMS[0], "clear_all": True})
        assert not result.success
        assert all(is_team_oom_pinned(t) for t in TEAMS)
