from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from products.workflows.backend.management.commands.backfill_workflows_email_sending_tiers import (
    Command as BackfillCommand,
)
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.services.email_sending_tier import (
    SendingHistoryWindows,
    SesTenantState,
    TeamSendingHistory,
    TierDecision,
    apply_tier_decision,
    decide_tier,
    highest_qualifying_tier,
    recompute_email_sending_tiers,
)
from products.workflows.backend.utils.email_sending_tiers import get_email_sending_tier_limits

TIER_HOURLY_CAPS = [200, 600, 2000, 6000, 20000, 60000, 200000]
TIER_DAILY_CAPS = [1000, 3000, 10000, 30000, 100000, 300000, 1000000]
TIER_BATCH_CAPS = [1000, 3000, 10000, 30000, 100000, 300000, 1000000]

TIER_SETTINGS = {
    "WORKFLOWS_EMAIL_TIER_HOURLY_CAPS": TIER_HOURLY_CAPS,
    "WORKFLOWS_EMAIL_TIER_DAILY_CAPS": TIER_DAILY_CAPS,
    "WORKFLOWS_EMAIL_TIER_BATCH_AUDIENCE_CAPS": TIER_BATCH_CAPS,
    "WORKFLOWS_EMAIL_TIER_MIN_DAYS_AT_TIER": [3],
    "WORKFLOWS_EMAIL_TIER_MIN_ACTIVE_DAYS": 2,
    "WORKFLOWS_EMAIL_TIER_MIN_DAILY_USE_RATIO": 0.5,
    "WORKFLOWS_EMAIL_TIER_MAX_COMPLAINT_RATE": 0.001,
    "WORKFLOWS_EMAIL_TIER_MAX_BOUNCE_RATE": 0.02,
    "WORKFLOWS_EMAIL_TIER_COMPLAINT_RATE_MIN_SENDS": 1000,
    "WORKFLOWS_EMAIL_TIER_COMPLAINT_COUNT_BACKSTOP": 3,
    "WORKFLOWS_EMAIL_TIER_BOUNCE_RATE_MIN_SENDS": 200,
    "WORKFLOWS_EMAIL_TIER_DEMOTION_WINDOW_DAYS": 7,
    "WORKFLOWS_EMAIL_TIER_DEMOTION_COOLDOWN_DAYS": 7,
    "WORKFLOWS_EMAIL_TIER_INACTIVITY_DECAY_DAYS": 30,
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


def clean_days(count: int, sent_per_day: int, *, days_ago: int = 0) -> dict[str, int]:
    # Relative to today, because only days after the team's tier_updated_at count toward the use
    # bar. Absolute dates would drift out of every window as wall-clock time moves past them.
    today = timezone.now().date()
    return {(today - timedelta(days=offset + days_ago)).strftime("%Y-%m-%d"): sent_per_day for offset in range(count)}


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

    # The cooldown must be armed only by a prior rate demotion: with the cooldown at the window
    # length, one incident demotes exactly once, and a fresh promotion must not shield a team from
    # its first real demotion.
    @parameterized.expand(
        [
            ("a recent rate demotion holds further demotion", 1, 2, "demotion_cooldown"),
            ("an expired cooldown lets new evidence demote", 8, 1, "rates_above_threshold"),
            ("no prior rate demotion demotes immediately", None, 1, "rates_above_threshold"),
        ]
    )
    def test_the_demotion_cooldown_is_armed_by_rate_demotions_only(
        self, _name: str, demoted_days_ago: int | None, expected_tier: int, expected_reason: str
    ) -> None:
        decision = decide_tier(
            history=history(sent=10_000, complained=50),
            current_tier=2,
            # A fresh tier write (a promotion or a staff change) must not block the demotion.
            tier_updated_at=timezone.now() - timedelta(days=1),
            last_rate_demotion_at=(
                timezone.now() - timedelta(days=demoted_days_ago) if demoted_days_ago is not None else None
            ),
            suspended=False,
        )
        assert decision.new_tier == expected_tier
        assert decision.reason == expected_reason

    @parameterized.expand(
        [
            ("complaints at the backstop demote a silent window", 3, 1, "rates_above_threshold"),
            ("fewer complaints than the backstop stay clean", 2, 2, "tier_not_used_enough"),
        ]
    )
    def test_delayed_complaints_count_even_when_the_window_has_no_sends(
        self, _name: str, complained: int, expected_tier: int, expected_reason: str
    ) -> None:
        # Feedback lags sends, so a window can hold the complaints from sends made just before it
        # opened. Zero sends must not make those complaints invisible. The anchor stays inside the
        # inactivity decay period so the clean case is not demoted for dormancy instead.
        decision = decide_tier(
            history=history(sent=0, complained=complained),
            current_tier=2,
            tier_updated_at=timezone.now() - timedelta(days=10),
            suspended=False,
        )
        assert decision.new_tier == expected_tier
        assert decision.reason == expected_reason

    # Demotion reads the short recent window and promotion the full window, so an aged-out
    # incident stops demoting but still blocks the climb until the full window is clean.
    @parameterized.expand(
        [
            ("recent incident demotes despite a clean full window", 50, 0, 1, "rates_above_threshold"),
            ("aged-out incident blocks promotion but stops demoting", 0, 200, 2, "rates_recovering"),
        ]
    )
    def test_demotion_and_promotion_read_different_windows(
        self, _name: str, recent_complaints: int, older_complaints: int, expected_tier: int, expected_reason: str
    ) -> None:
        used = clean_days(5, TIER_DAILY_CAPS[2])
        decision = decide_tier(
            history=history(sent=100_000, complained=recent_complaints + older_complaints, daily_sends=used),
            recent_history=history(sent=10_000, complained=recent_complaints),
            current_tier=2,
            tier_updated_at=timezone.now() - timedelta(days=30),
            suspended=False,
        )
        assert decision.new_tier == expected_tier
        assert decision.reason == expected_reason

    # AWS measures the complaint rate against FBL-domain sends only, while our rate divides by all
    # sends and reads lower. The tenant verdict must therefore override a clean internal history:
    # a paused tenant restarts at the bottom, HIGH impact demotes, LOW blocks the climb.
    @parameterized.expand(
        [
            ("aws paused tenant drops to the bottom", "DISABLED", "", 0, "ses_tenant_paused"),
            ("high impact demotes despite clean internal rates", "ENABLED", "HIGH", 1, "ses_reputation_high"),
            ("low impact blocks promotion but does not demote", "ENABLED", "LOW", 2, "ses_reputation_not_clean"),
            ("reinstated tenant with no impact still promotes", "REINSTATED", "NONE", 3, "clean_and_used"),
        ]
    )
    def test_the_ses_tenant_verdict_overrides_clean_internal_rates(
        self, _name: str, sending_status: str, impact: str, expected_tier: int, expected_reason: str
    ) -> None:
        used = clean_days(5, TIER_DAILY_CAPS[2])
        decision = decide_tier(
            history=history(sent=sum(used.values()), daily_sends=used),
            current_tier=2,
            tier_updated_at=timezone.now() - timedelta(days=30),
            suspended=False,
            tenant_state=SesTenantState(sending_status=sending_status, reputation_impact=impact),
        )
        assert decision.new_tier == expected_tier
        assert decision.reason == expected_reason

    # At the 0.1% threshold one complaint per 1,000 sends is exactly the line, so a small window
    # must not turn a single complaint into a demotion, while the absolute backstop still catches
    # an egregious small sender.
    @parameterized.expand(
        [
            ("one complaint under the denominator floor stays clean", 900, 0, 1, 2),
            ("complaints at the backstop demote despite the floor", 900, 0, 3, 1),
            ("high bounce rate under the denominator floor stays clean", 150, 20, 0, 2),
        ]
    )
    def test_rates_only_count_on_a_meaningful_denominator(
        self, _name: str, sent: int, bounced: int, complained: int, expected_tier: int
    ) -> None:
        decision = decide_tier(
            history=history(sent=sent, hard_bounced=bounced, complained=complained),
            current_tier=2,
            tier_updated_at=timezone.now() - timedelta(days=30),
            suspended=False,
        )
        assert decision.new_tier == expected_tier

    # A dormant allowance is no longer earned: mailbox providers keep about 30 days of reputation
    # history, and a comeback blast from a stale list is what the caps exist to prevent.
    @parameterized.expand(
        [
            ("dormant past the decay period drops one tier", 3, 40, 2, "inactive"),
            ("dormant but inside the decay period holds", 3, 10, 3, "tier_not_used_enough"),
            ("the lowest tier never decays", 0, 40, 0, "tier_not_used_enough"),
        ]
    )
    def test_inactivity_decays_one_tier_per_period(
        self, _name: str, current_tier: int, days_since_update: int, expected_tier: int, expected_reason: str
    ) -> None:
        decision = decide_tier(
            history=history(sent=0),
            current_tier=current_tier,
            tier_updated_at=timezone.now() - timedelta(days=days_since_update),
            suspended=False,
        )
        assert decision.new_tier == expected_tier
        assert decision.reason == expected_reason

    @parameterized.expand([("dwell met at the low tier", 0, 1), ("dwell not met at the high tier", 2, 2)])
    @override_settings(WORKFLOWS_EMAIL_TIER_MIN_DAYS_AT_TIER=[3, 3, 5])
    def test_the_promotion_dwell_is_indexed_by_tier(self, _name: str, current_tier: int, expected_tier: int) -> None:
        used = clean_days(4, TIER_DAILY_CAPS[current_tier])
        decision = decide_tier(
            history=history(sent=sum(used.values()), daily_sends=used),
            current_tier=current_tier,
            tier_updated_at=timezone.now() - timedelta(days=4),
            suspended=False,
        )
        assert decision.new_tier == expected_tier

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

    # An established sender must land on its real tier at once, but only recent volume counts:
    # two high-volume days months ago must not grant a dormant team an allowance the inactivity
    # decay exists to remove, with a freshly stamped decay clock on top.
    @parameterized.expand(
        [
            ("recent volume earns the real tier", 0, 4),
            ("volume older than the decay period earns nothing", 60, 0),
        ]
    )
    def test_backfill_mode_jumps_straight_to_the_recently_earned_tier(
        self, _name: str, days_ago: int, expected_tier: int
    ) -> None:
        used = clean_days(5, TIER_DAILY_CAPS[3], days_ago=days_ago)
        decision = decide_tier(
            history=history(sent=sum(used.values()), daily_sends=used),
            current_tier=0,
            tier_updated_at=None,
            suspended=False,
            require_time_at_tier=False,
            single_step=False,
        )
        assert decision.new_tier == expected_tier

    def test_sends_before_a_midday_tier_change_do_not_count(self) -> None:
        # The tier change stamps a mid-day anchor, but metrics are day-grained. The anchor day's
        # pre-change volume must not count toward the new tier, so a team demoted mid-day cannot
        # re-promote on one real day at the new tier plus the anchor day it was demoted on.
        now = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        anchor = now - timedelta(days=4)  # past the 3-day dwell, so promotion is considered
        # Tier 0 allows 1,000/day and the bar is half of it, so 900 qualifies. Only the anchor day
        # and one later day clear the bar, so counting the anchor day would reach the two-day minimum.
        daily_sends = {anchor.strftime("%Y-%m-%d"): 900, now.strftime("%Y-%m-%d"): 900}
        decision = decide_tier(
            history=history(sent=sum(daily_sends.values()), daily_sends=daily_sends),
            current_tier=0,
            tier_updated_at=anchor,
            suspended=False,
            now=now,
        )
        assert decision.new_tier == 0
        assert decision.reason == "tier_not_used_enough"

    def test_qualifying_tier_never_exceeds_the_table(self) -> None:
        used = clean_days(5, TIER_DAILY_CAPS[-1] * 100)
        assert highest_qualifying_tier(used) == len(TIER_DAILY_CAPS) - 1


@override_settings(**TIER_SETTINGS)
class TestRecomputeEmailSendingTiers(BaseTest):
    def _config(self, **fields) -> TeamWorkflowsConfig:
        config, _ = TeamWorkflowsConfig.objects.update_or_create(team=self.team, defaults=fields)
        return config

    def _run(
        self,
        histories: dict[int, TeamSendingHistory],
        recent: dict[int, TeamSendingHistory] | None = None,
    ) -> None:
        with patch(
            "products.workflows.backend.services.email_sending_tier.build_sending_history_windows",
            return_value=SendingHistoryWindows(window=histories, recent=recent if recent is not None else histories),
        ):
            recompute_email_sending_tiers()

    def test_returns_a_held_decision_with_its_reason(self) -> None:
        # The admin recompute action reports why a team did not move, so the sweep must return
        # holds with their reason rather than only the applied changes.
        self._config(email_sending_tier=2, email_sending_tier_updated_at=timezone.now() - timedelta(days=10))
        with patch(
            "products.workflows.backend.services.email_sending_tier.build_sending_history_windows",
            return_value=SendingHistoryWindows(window={}, recent={}),
        ):
            decisions = recompute_email_sending_tiers()
        held = next(decision for decision in decisions if decision.team_id == self.team.id)
        assert not held.changed
        assert held.reason == "tier_not_used_enough"
        assert TeamWorkflowsConfig.objects.get(team=self.team).email_sending_tier == 2

    def test_promotion_is_persisted_with_a_fresh_timestamp(self) -> None:
        self._config(email_sending_tier=0, email_sending_tier_updated_at=timezone.now() - timedelta(days=30))
        used = clean_days(2, TIER_DAILY_CAPS[0])
        self._run({self.team.id: history(team_id=self.team.id, sent=sum(used.values()), daily_sends=used)})

        config = TeamWorkflowsConfig.objects.get(team=self.team)
        assert config.email_sending_tier == 1
        assert config.email_sending_tier_updated_at is not None
        assert config.email_sending_tier_updated_at > timezone.now() - timedelta(minutes=1)

    def test_suspended_team_is_demoted_even_with_no_recent_sending(self) -> None:
        self._config(
            email_sending_tier=3,
            email_sending_tier_updated_at=timezone.now() - timedelta(days=30),
            email_sending_suspended_at=timezone.now(),
        )
        self._run({})

        assert TeamWorkflowsConfig.objects.get(team=self.team).email_sending_tier == 0

    @parameterized.expand([("pinned_after_snapshot", "pin"), ("tier_set_after_snapshot", "retier")])
    def test_stale_decision_does_not_overwrite_a_concurrent_staff_change(self, _name: str, change: str) -> None:
        # The sweep read the row at tier 1 and decided to promote to 2. Staff then pinned or re-set
        # the tier before the write. The stale decision must not clobber the staff change.
        config = self._config(email_sending_tier=1, email_sending_tier_pinned=False)
        if change == "pin":
            TeamWorkflowsConfig.objects.filter(team=self.team).update(email_sending_tier_pinned=True)
            expected_tier = 1
        else:
            TeamWorkflowsConfig.objects.filter(team=self.team).update(email_sending_tier=5)
            expected_tier = 5

        decision = TierDecision(team_id=self.team.id, previous_tier=1, new_tier=2, reason="clean_and_used")
        assert apply_tier_decision(config, decision) is False
        assert TeamWorkflowsConfig.objects.get(team=self.team).email_sending_tier == expected_tier

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


@override_settings(**TIER_SETTINGS)
class TestBackfillEmailSendingTiers(BaseTest):
    def test_suspended_team_is_not_promoted_despite_qualifying_history(self) -> None:
        used = clean_days(5, TIER_DAILY_CAPS[3])
        histories = {self.team.id: history(team_id=self.team.id, sent=sum(used.values()), daily_sends=used)}

        # Control: the same history promotes when the team is not suspended.
        TeamWorkflowsConfig.objects.update_or_create(team=self.team, defaults={"email_sending_tier": 0})
        assert BackfillCommand()._decide(histories=histories, team_ids=[self.team.id]) != []

        # A staff suspension keeps the backfill at tier 0, so reinstatement does not restore a high tier.
        TeamWorkflowsConfig.objects.filter(team=self.team).update(email_sending_suspended_at=timezone.now())
        assert BackfillCommand()._decide(histories=histories, team_ids=[self.team.id]) == []

    def test_suspended_team_with_no_window_history_is_reset_to_tier_zero(self) -> None:
        # A suspended team that sent nothing in the window must still be evaluated, or the backfill
        # would leave its stored elevated tier in place for reinstatement.
        TeamWorkflowsConfig.objects.update_or_create(
            team=self.team,
            defaults={"email_sending_tier": 4, "email_sending_suspended_at": timezone.now()},
        )
        decisions = BackfillCommand()._decide(histories={}, team_ids=[self.team.id])
        assert [(d.new_tier, d.reason) for d in decisions] == [(0, "staff_suspension")]

    def test_apply_does_not_overwrite_a_concurrent_staff_change(self) -> None:
        # The fleet scan computes decisions before it writes. A staff pin landing in that gap must
        # win over the stale decision, matching the daily sweep's compare-and-set.
        TeamWorkflowsConfig.objects.update_or_create(
            team=self.team, defaults={"email_sending_tier": 1, "email_sending_tier_pinned": True}
        )
        stale = TierDecision(team_id=self.team.id, previous_tier=1, new_tier=4, reason="clean_and_used")
        assert BackfillCommand()._apply([stale]) == 0
        assert TeamWorkflowsConfig.objects.get(team=self.team).email_sending_tier == 1

    def test_history_for_a_deleted_team_is_dropped(self) -> None:
        # app_metrics2 in ClickHouse outlives a team deleted from Postgres, so its history can name a
        # team that no longer exists. It must not reach the distribution or the write count.
        ghost_id = self.team.id + 10_000
        histories = {
            self.team.id: history(team_id=self.team.id),
            ghost_id: history(team_id=ghost_id),
        }
        assert set(BackfillCommand()._without_deleted_teams(histories)) == {self.team.id}
