from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized

from products.alerts_platform.backend.facade.contracts import (
    PlatformAlertCheckInput,
    PlatformCheck,
    SourceCoverage,
    SourceVerdict,
    SuppressionReason,
)
from products.alerts_platform.backend.facade.testing import undeclared_policy_divergences
from products.logs.backend.alert_comparison import LOGS_INTENTIONAL_DIVERGENCES, LogsCorrespondence
from products.logs.backend.alert_source_cycle import _evaluation_key, window_end_of
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent

CHECKED_AT = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
WINDOW_END = CHECKED_AT - timedelta(minutes=1)


def _check_input(alert_id, *, next_check_at) -> PlatformAlertCheckInput:
    return PlatformAlertCheckInput(
        id=alert_id,
        team_id=1,
        name="API errors",
        source_config={},
        threshold_count=10,
        threshold_operator="above",
        window_minutes=5,
        check_interval_minutes=5,
        evaluation_periods=1,
        datapoints_to_alarm=1,
        cooldown_minutes=0,
        schedule_restriction=None,
        next_check_at=next_check_at,
        consecutive_failures=0,
        legacy_configuration_id=None,
        state="not_firing",
        last_notified_at=None,
        snooze_until=None,
    )


EVALUATION_KEY = _evaluation_key(_check_input(uuid4(), next_check_at=CHECKED_AT), WINDOW_END)


def _platform_check(
    *,
    team_id: int = 1,
    legacy_configuration_id: UUID | None = None,
    at: datetime = CHECKED_AT,
    muted_notification: str = "none",
) -> PlatformCheck:
    return PlatformCheck(
        team_id=team_id,
        configuration_id=uuid4(),
        legacy_configuration_id=legacy_configuration_id,
        alert_id=uuid4(),
        grouping_key="",
        evaluation_key=EVALUATION_KEY,
        previous_state="not_firing",
        state="firing",
        kind="check",
        muted_notification=muted_notification,
        error_message="",
        occurred_at=at,
    )


class TestLogsDivergenceDeclarations(TestCase):
    def test_every_policy_divergence_is_declared(self) -> None:
        assert undeclared_policy_divergences(LogsCorrespondence()) == frozenset()

    @parameterized.expand(
        [
            (
                "the source made no check because it was muted",
                _platform_check(),
                SourceVerdict(
                    caught_up_at=None,
                    coverage=SourceCoverage.SUPPRESSED,
                    state="snoozed",
                    suppressed_by=SuppressionReason.MUTED,
                ),
                True,
            ),
            (
                "the platform held an announcement while the source fell behind",
                _platform_check(muted_notification="fire"),
                SourceVerdict(caught_up_at=None, coverage=SourceCoverage.BEHIND, state="not_firing"),
                True,
            ),
            (
                "the platform held an announcement the source was not muted for",
                _platform_check(muted_notification="fire"),
                SourceVerdict(caught_up_at=None, coverage=SourceCoverage.EVALUATED, state="not_firing"),
                False,
            ),
        ]
    )
    def test_mute_divergence_recognizes(
        self, _name: str, check: PlatformCheck, verdict: SourceVerdict, recognized: bool
    ) -> None:
        (mute,) = LOGS_INTENTIONAL_DIVERGENCES

        assert mute.recognizes(check, verdict) is recognized


class TestLogsCorrespondence(BaseTest):
    def _alert(self, **overrides) -> LogsAlertConfiguration:
        return LogsAlertConfiguration.objects.create(
            team=self.team,
            name="API errors",
            created_by=self.user,
            threshold_count=10,
            **{"last_checked_at": CHECKED_AT, **overrides},
        )

    def _event(self, alert: LogsAlertConfiguration, *, at: datetime, **overrides) -> LogsAlertEvent:
        event = LogsAlertEvent.objects.create(
            alert=alert,
            threshold_breached=False,
            state_before=overrides.pop("state_before", LogsAlertConfiguration.State.NOT_FIRING),
            state_after=overrides.pop("state_after", LogsAlertConfiguration.State.FIRING),
            **overrides,
        )
        LogsAlertEvent.objects.filter(pk=event.pk).update(created_at=at)
        event.refresh_from_db()
        return event

    def _check(self, alert: LogsAlertConfiguration, *, at: datetime = CHECKED_AT) -> PlatformCheck:
        return _platform_check(team_id=self.team.id, legacy_configuration_id=alert.id, at=at)

    def _verdict(self, alert: LogsAlertConfiguration):
        check = self._check(alert)
        return LogsCorrespondence().verdicts_for([check])[check.ref]

    def test_an_alert_that_never_transitioned_reports_its_current_state(self) -> None:
        alert = self._alert(state=LogsAlertConfiguration.State.FIRING)

        verdict = self._verdict(alert)

        assert verdict.state == LogsAlertConfiguration.State.FIRING
        assert verdict.coverage is SourceCoverage.EVALUATED

    def test_the_state_comes_from_the_transition_after_the_check(self) -> None:
        alert = self._alert(state=LogsAlertConfiguration.State.FIRING)
        self._event(
            alert,
            at=CHECKED_AT + timedelta(minutes=5),
            state_before=LogsAlertConfiguration.State.NOT_FIRING,
            state_after=LogsAlertConfiguration.State.FIRING,
        )

        verdict = self._verdict(alert)

        assert verdict.state == LogsAlertConfiguration.State.NOT_FIRING
        assert verdict.observed_at == CHECKED_AT + timedelta(minutes=5)

    @parameterized.expand(
        [
            (
                "snoozed",
                {"state": LogsAlertConfiguration.State.SNOOZED},
                SourceCoverage.SUPPRESSED,
                SuppressionReason.MUTED,
            ),
            (
                "broken",
                {"state": LogsAlertConfiguration.State.BROKEN},
                SourceCoverage.SUPPRESSED,
                SuppressionReason.BROKEN,
            ),
            (
                "inside a schedule restriction",
                {"schedule_restriction": {"blocked_windows": [{"start": "11:00", "end": "13:00"}]}},
                SourceCoverage.SUPPRESSED,
                SuppressionReason.MUTED,
            ),
            (
                "disabled",
                {"enabled": False},
                SourceCoverage.SUPPRESSED,
                SuppressionReason.DISABLED,
            ),
            (
                "never checked",
                {"last_checked_at": None},
                SourceCoverage.BEHIND,
                None,
            ),
            (
                "stalled before the window the platform answered for",
                {"last_checked_at": WINDOW_END - timedelta(minutes=1)},
                SourceCoverage.BEHIND,
                None,
            ),
        ]
    )
    def test_coverage(
        self,
        _name: str,
        overrides: dict,
        coverage: SourceCoverage,
        suppressed_by: SuppressionReason | None,
    ) -> None:
        alert = self._alert(**overrides)

        verdict = self._verdict(alert)

        assert verdict.coverage is coverage
        assert verdict.suppressed_by is suppressed_by

    def test_a_disable_after_the_check_means_the_alert_was_enabled_at_it(self) -> None:
        alert = self._alert(enabled=False)
        self._event(
            alert,
            at=CHECKED_AT + timedelta(minutes=5),
            kind=LogsAlertEvent.Kind.DISABLE,
            state_before=LogsAlertConfiguration.State.NOT_FIRING,
            state_after=LogsAlertConfiguration.State.NOT_FIRING,
        )

        verdict = self._verdict(alert)

        assert verdict.coverage is SourceCoverage.EVALUATED

    def test_one_flapping_alert_does_not_cost_the_batch_its_answers(self) -> None:
        flapping = self._alert()
        quiet = self._alert()
        window_start = CHECKED_AT - timedelta(hours=1)
        for minute in range(3):
            self._event(flapping, at=window_start + timedelta(minutes=minute + 1))
        # Two instants, so the compared window has room to hold the transitions between them.
        checks = [self._check(flapping, at=window_start), self._check(flapping)]
        checks += [self._check(quiet, at=window_start), self._check(quiet)]

        with patch("products.logs.backend.alert_comparison.MAX_EVENTS_PER_WINDOW", 2):
            verdicts = LogsCorrespondence().verdicts_for(checks)

        assert verdicts[checks[0].ref].coverage is SourceCoverage.UNKNOWN
        assert verdicts[checks[2].ref].coverage is SourceCoverage.EVALUATED

    def test_a_transition_after_the_window_still_dates_the_last_check(self) -> None:
        # The read is bounded by the window, so this row sits outside it and is fetched on purpose.
        alert = self._alert(state=LogsAlertConfiguration.State.FIRING)
        self._event(
            alert,
            at=CHECKED_AT + timedelta(hours=2),
            state_before=LogsAlertConfiguration.State.NOT_FIRING,
            state_after=LogsAlertConfiguration.State.FIRING,
        )

        assert self._verdict(alert).state == LogsAlertConfiguration.State.NOT_FIRING

    def test_the_window_bound_round_trips_through_the_key_the_source_mints(self) -> None:
        # A key the minter no longer produces would silently cost every check its window bound.
        check = _check_input(uuid4(), next_check_at=CHECKED_AT)

        assert window_end_of(_evaluation_key(check, WINDOW_END)) == WINDOW_END

    def test_an_alert_disabled_after_the_window_was_still_enabled_during_it(self) -> None:
        # The read is bounded by the window, so a toggle can sit past the first transition after
        # it. Missing it reads the whole window as disabled, and every check as a disagreement.
        alert = self._alert(enabled=False)
        self._event(
            alert,
            at=CHECKED_AT + timedelta(hours=2),
            state_before=LogsAlertConfiguration.State.NOT_FIRING,
            state_after=LogsAlertConfiguration.State.FIRING,
        )
        self._event(
            alert,
            at=CHECKED_AT + timedelta(hours=3),
            kind=LogsAlertEvent.Kind.DISABLE,
            state_before=LogsAlertConfiguration.State.FIRING,
            state_after=LogsAlertConfiguration.State.NOT_FIRING,
        )

        verdict = self._verdict(alert)

        assert verdict.coverage is SourceCoverage.EVALUATED
        assert verdict.suppressed_by is None

    @parameterized.expand(
        [
            # A later check bounds the read past both transitions.
            ("both transitions inside the window", True),
            # The read reaches past the window only for the rows it asks for by name.
            ("both transitions after the last check", False),
        ]
    )
    def test_catching_up_is_the_first_move_into_the_state_not_merely_the_next_move(
        self, _name: str, later_check: bool
    ) -> None:
        # Reading only the next transition would book this lag as a genuine disagreement.
        alert = self._alert(state=LogsAlertConfiguration.State.FIRING)
        early = CHECKED_AT - timedelta(minutes=10)
        self._event(
            alert,
            at=early + timedelta(minutes=2),
            state_before=LogsAlertConfiguration.State.NOT_FIRING,
            state_after=LogsAlertConfiguration.State.ERRORED,
        )
        self._event(
            alert,
            at=early + timedelta(minutes=6),
            state_before=LogsAlertConfiguration.State.ERRORED,
            state_after=LogsAlertConfiguration.State.FIRING,
        )
        checks = [self._check(alert, at=early), *([self._check(alert)] if later_check else [])]

        verdicts = LogsCorrespondence().verdicts_for(checks)

        assert verdicts[checks[0].ref].state == LogsAlertConfiguration.State.NOT_FIRING
        assert verdicts[checks[0].ref].caught_up_at == early + timedelta(minutes=6)

    def test_a_check_whose_configuration_names_no_logs_alert_cannot_be_answered(self) -> None:
        orphan = replace(self._check(self._alert()), legacy_configuration_id=None)

        verdicts = LogsCorrespondence().verdicts_for([orphan])

        assert verdicts[orphan.ref].coverage is SourceCoverage.UNKNOWN
