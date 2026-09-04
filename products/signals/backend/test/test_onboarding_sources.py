from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from products.signals.backend.facade.api import enable_onboarding_signal_sources
from products.signals.backend.models import SignalSourceConfig


def _enabled_pairs(team_id: int) -> set[tuple[str, str]]:
    return set(
        SignalSourceConfig.objects.filter(team_id=team_id, enabled=True).values_list("source_product", "source_type")
    )


class TestOnboardingSignalSources(BaseTest):
    def test_a_new_workspace_ends_up_watched_without_anyone_touching_a_toggle(self) -> None:
        sources = enable_onboarding_signal_sources(self.team.id, self.user.id)

        assert _enabled_pairs(self.team.id) == {
            ("error_tracking", "issue_created"),
            ("error_tracking", "issue_reopened"),
            ("error_tracking", "issue_spiking"),
            ("health_checks", "health_issue"),
            ("conversations", "ticket"),
            ("llm_analytics", "evaluation_report"),
            ("analytics", "anomaly_investigation"),
        }
        assert sources.newly_enabled
        assert sources.labels[:2] == ("error tracking", "health checks")
        # Onboarding copy names these to a first-time reader, so they have to describe the problem
        # caught rather than the product it came from.
        assert sources.watches == (
            "errors",
            "failing health checks",
            "support tickets",
            "AI evals",
            "metric swings",
        )

    def test_a_source_the_team_switched_off_is_never_switched_back_on(self) -> None:
        SignalSourceConfig.objects.create(
            team_id=self.team.id, source_product="health_checks", source_type="health_issue", enabled=False
        )

        enable_onboarding_signal_sources(self.team.id, self.user.id)

        assert ("health_checks", "health_issue") not in _enabled_pairs(self.team.id)
        assert ("error_tracking", "issue_created") in _enabled_pairs(self.team.id)

    def test_a_source_whose_write_failed_is_retried_next_time(self) -> None:
        real = SignalSourceConfig.objects.update_or_create

        def explode_on_health_checks(**kwargs: Any) -> Any:
            if kwargs.get("source_product") == "health_checks":
                raise RuntimeError("boom")
            return real(**kwargs)

        with patch.object(SignalSourceConfig.objects, "update_or_create", side_effect=explode_on_health_checks):
            enable_onboarding_signal_sources(self.team.id, self.user.id)
        assert ("health_checks", "health_issue") not in _enabled_pairs(self.team.id)

        sources = enable_onboarding_signal_sources(self.team.id, self.user.id)

        assert ("health_checks", "health_issue") in _enabled_pairs(self.team.id)
        assert sources.newly_enabled

    def test_a_team_that_already_runs_everything_is_left_alone(self) -> None:
        enable_onboarding_signal_sources(self.team.id, self.user.id)
        before = _enabled_pairs(self.team.id)

        sources = enable_onboarding_signal_sources(self.team.id, self.user.id)

        assert not sources.newly_enabled
        assert "error tracking" in sources.labels
        assert _enabled_pairs(self.team.id) == before

    def test_one_source_failing_does_not_take_the_rest_down(self) -> None:
        real = SignalSourceConfig.objects.update_or_create

        def explode_on_health_checks(**kwargs: Any) -> Any:
            if kwargs.get("source_product") == "health_checks":
                raise RuntimeError("boom")
            return real(**kwargs)

        with patch.object(SignalSourceConfig.objects, "update_or_create", side_effect=explode_on_health_checks):
            sources = enable_onboarding_signal_sources(self.team.id, self.user.id)

        assert "health checks" not in sources.labels
        assert "failing health checks" not in sources.watches
        assert "error tracking" in sources.labels
        assert ("error_tracking", "issue_created") in _enabled_pairs(self.team.id)
