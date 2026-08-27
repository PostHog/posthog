from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.services.email_sending_tier import (
    TeamSendingHistory,
    decide_tier,
    highest_qualifying_tier,
    recompute_email_sending_tiers,
)
from products.workflows.backend.utils.email_sending_tiers import get_email_sending_tier_limits

TIER_HOURLY_CAPS = [200, 2000, 10000, 50000, 200000]
TIER_DAILY_CAPS = [1000, 10000, 50000, 250000, 1000000]
TIER_BATCH_CAPS = [1000, 10000, 50000, 250000, 1000000]

TIER_SETTINGS = {
    "WORKFLOWS_EMAIL_TIER_HOURLY_CAPS": TIER_HOURLY_CAPS,
    "WORKFLOWS_EMAIL_TIER_DAILY_CAPS": TIER_DAILY_CAPS,
    "WORKFLOWS_EMAIL_TIER_BATCH_AUDIENCE_CAPS": TIER_BATCH_CAPS,
    "WORKFLOWS_EMAIL_TIER_MIN_DAYS_AT_TIER": 3,
    "WORKFLOWS_EMAIL_TIER_MIN_ACTIVE_DAYS": 2,
    "WORKFLOWS_EMAIL_TIER_MIN_DAILY_USE_RATIO": 0.5,
    "WORKFLOWS_EMAIL_TIER_MAX_COMPLAINT_RATE": 0.001,
    "WORKFLOWS_EMAIL_TIER_MAX_BOUNCE_RATE": 0.02,
    "WORKFLOWS_EMAIL_TIER_AUTO_PAUSE_METRIC_NAMES": [],
}


def history(
    *,
    team_id: int = 1,
    sent: int = 0,
    hard_bounced: int = 0,
    complained: int = 0,
    auto_paused: bool = False,
    daily_sends: dict[str, int] | None = None,
) -> TeamSendingHistory:
    return TeamSendingHistory(
        team_id=team_id,
        sent=sent,
        hard_bounced=hard_bounced,
        complained=complained,
        auto_paused=auto_paused,
        daily_sends=daily_sends or {},
    )


def clean_days(count: int, sent_per_day: int) -> dict[str, int]:
    # Relative to today, because only days after the team's tier_updated_at count toward the use
    # bar. Absolute dates would drift out of every window as wall-clock time moves past them.
    today = timezone.now().date()
    return {(today - timedelta(days=offset)).strftime("%Y-%m-%d"): sent_per_day for offset in range(count)}


@override_settings(**TIER_SETTINGS)
class TestEmailSendingTierDecision(BaseTest):
    @parameterized.expand([(tier, caps) for tier, caps in enumerate(zip(TIER_HOURLY_CAPS, TIER_DAILY_CAPS))])
    def test_tier_maps_to_its_caps(self, tier: int, caps: tuple[int, int]) -> None:
        limits = get_email_sending_tier_limits(tier)
        assert (limits.per_hour, limits.per_day) == caps

    @parameterized.expand([(tier,) for tier in range(len(TIER_DAILY_CAPS) - 1)])
    def test_promotes_one_tier_when_every_criterion_is_met(self, tier: int) -> None:
        used = clean_days(2, TIER_DAILY_CAPS[tier])
        decision = decide_tier(
            history=history(sent=sum(used.values()), daily_sends=used),
            current_tier=tier,
            tier_updated_at=timezone.now() - timedelta(days=30),
            suspended=False,
        )
        assert decision.new_tier == tier + 1
        assert decision.reason == "clean_and_used"

    def test_does_not_promote_before_the_minimum_time_at_tier(self) -> None:
        used = clean_days(2, TIER_DAILY_CAPS[0])
        decision = decide_tier(
            history=history(sent=sum(used.values()), daily_sends=used),
            current_tier=0,
            tier_updated_at=timezone.now() - timedelta(hours=1),
            suspended=False,
        )
        assert decision.new_tier == 0
        assert decision.reason == "too_soon"

    # Tier 0 allows 1,000/day and the bar is half of it, so 900 clears the volume but one day is
    # short of the two-day minimum, and 400 misses the volume however many days it runs for.
    @parameterized.expand(
        [
            ("nothing sent", 0, 0),
            ("only one qualifying day", 1, 900),
            ("volume below half the daily cap on every day", 2, 400),
        ]
    )
    def test_does_not_promote_without_real_use_of_the_tier(self, _name: str, days: int, sent_per_day: int) -> None:
        daily_sends = clean_days(days, sent_per_day)
        decision = decide_tier(
            history=history(sent=sum(daily_sends.values()), daily_sends=daily_sends),
            current_tier=0,
            tier_updated_at=timezone.now() - timedelta(days=30),
            suspended=False,
        )
        assert decision.new_tier == 0
        assert decision.reason == "tier_not_used_enough"

    @parameterized.expand(
        [
            ("complaint rate above the bar", 10_000, 0, 50),
            ("hard bounce rate above the bar", 10_000, 500, 0),
        ]
    )
    def test_demotes_one_tier_on_dirty_rates(self, _name: str, sent: int, bounced: int, complained: int) -> None:
        used = clean_days(5, TIER_DAILY_CAPS[1])
        decision = decide_tier(
            history=history(sent=sent, hard_bounced=bounced, complained=complained, daily_sends=used),
            current_tier=2,
            tier_updated_at=timezone.now() - timedelta(days=30),
            suspended=False,
        )
        assert decision.new_tier == 1
        assert decision.reason == "rates_above_threshold"

    def test_demotion_stops_at_tier_zero(self) -> None:
        decision = decide_tier(
            history=history(sent=1000, complained=500),
            current_tier=0,
            tier_updated_at=timezone.now() - timedelta(days=30),
            suspended=False,
        )
        assert decision.new_tier == 0

    def test_suspension_drops_straight_to_tier_zero(self) -> None:
        decision = decide_tier(
            history=history(sent=100_000, daily_sends=clean_days(10, TIER_DAILY_CAPS[3])),
            current_tier=4,
            tier_updated_at=timezone.now() - timedelta(days=30),
            suspended=True,
        )
        assert decision.new_tier == 0
        assert decision.reason == "staff_suspension"

    @override_settings(WORKFLOWS_EMAIL_TIER_AUTO_PAUSE_METRIC_NAMES=["email_auto_paused"])
    def test_auto_pause_demotes_one_tier(self) -> None:
        decision = decide_tier(
            history=history(sent=10_000, auto_paused=True, daily_sends=clean_days(5, TIER_DAILY_CAPS[2])),
            current_tier=3,
            tier_updated_at=timezone.now() - timedelta(days=30),
            suspended=False,
        )
        assert decision.new_tier == 2
        assert decision.reason == "workflow_auto_paused"

    def test_backfill_mode_jumps_straight_to_the_earned_tier(self) -> None:
        # An established sender must land on its real tier at once. Walking it up one step per
        # daily run would throttle a healthy customer for weeks.
        used = clean_days(5, TIER_DAILY_CAPS[3])
        decision = decide_tier(
            history=history(sent=sum(used.values()), daily_sends=used),
            current_tier=0,
            tier_updated_at=None,
            suspended=False,
            require_time_at_tier=False,
            single_step=False,
        )
        assert decision.new_tier == 4

    def test_qualifying_tier_never_exceeds_the_table(self) -> None:
        used = clean_days(5, TIER_DAILY_CAPS[-1] * 100)
        assert highest_qualifying_tier(used) == len(TIER_DAILY_CAPS) - 1


@override_settings(**TIER_SETTINGS)
class TestRecomputeEmailSendingTiers(BaseTest):
    def _config(self, **fields) -> TeamWorkflowsConfig:
        config, _ = TeamWorkflowsConfig.objects.update_or_create(team=self.team, defaults=fields)
        return config

    def _run(self, histories: dict[int, TeamSendingHistory]) -> None:
        with patch(
            "products.workflows.backend.services.email_sending_tier.build_sending_histories",
            return_value=histories,
        ):
            recompute_email_sending_tiers()

    def test_promotion_is_persisted_with_a_fresh_timestamp(self) -> None:
        self._config(email_sending_tier=0, email_sending_tier_updated_at=timezone.now() - timedelta(days=30))
        used = clean_days(2, TIER_DAILY_CAPS[0])
        self._run({self.team.id: history(team_id=self.team.id, sent=sum(used.values()), daily_sends=used)})

        config = TeamWorkflowsConfig.objects.get(team=self.team)
        assert config.email_sending_tier == 1
        assert config.email_sending_tier_updated_at > timezone.now() - timedelta(minutes=1)

    def test_suspended_team_is_demoted_even_with_no_recent_sending(self) -> None:
        self._config(
            email_sending_tier=3,
            email_sending_tier_updated_at=timezone.now() - timedelta(days=30),
            email_sending_suspended_at=timezone.now(),
        )
        self._run({})

        assert TeamWorkflowsConfig.objects.get(team=self.team).email_sending_tier == 0

    @parameterized.expand([("promotion", 0), ("demotion", 3)])
    def test_pinned_team_never_moves(self, _name: str, tier: int) -> None:
        self._config(
            email_sending_tier=tier,
            email_sending_tier_pinned=True,
            email_sending_tier_updated_at=timezone.now() - timedelta(days=30),
            email_sending_suspended_at=timezone.now() if tier else None,
        )
        used = clean_days(5, TIER_DAILY_CAPS[3])
        self._run({self.team.id: history(team_id=self.team.id, sent=sum(used.values()), daily_sends=used)})

        assert TeamWorkflowsConfig.objects.get(team=self.team).email_sending_tier == tier
