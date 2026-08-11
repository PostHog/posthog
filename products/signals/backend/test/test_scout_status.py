from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.serializers import SignalScoutConfigUpdateSerializer

Status = SignalScoutConfig.Status
Reason = SignalScoutConfig.PauseReason


class TestScoutStatusTransitions(BaseTest):
    def _config(
        self,
        status: SignalScoutConfig.Status = Status.ACTIVE,
        pause_reason: SignalScoutConfig.PauseReason | None = None,
    ) -> SignalScoutConfig:
        return SignalScoutConfig.objects.create(
            team=self.team,
            skill_name="signals-scout-foo",
            enabled=status in SignalScoutConfig.RUNNABLE_STATUSES,
            status=status,
            pause_reason=pause_reason,
        )

    @parameterized.expand(
        [
            ("warn_active_scout", Status.ACTIVE, None, Status.PENDING_PAUSE, Reason.NO_OUTPUT, True),
            ("pause_active_scout", Status.ACTIVE, None, Status.PAUSED_BY_SYSTEM, Reason.NO_OUTPUT, True),
            (
                "owner_escalates_warning",
                Status.PENDING_PAUSE,
                Reason.NO_OUTPUT,
                Status.PAUSED_BY_SYSTEM,
                Reason.NO_OUTPUT,
                True,
            ),
            (
                "owner_resumes_own_pause",
                Status.PAUSED_BY_SYSTEM,
                Reason.REPEATED_FAILURES,
                Status.ACTIVE,
                Reason.REPEATED_FAILURES,
                True,
            ),
            (
                "other_writer_cannot_escalate",
                Status.PENDING_PAUSE,
                Reason.NO_OUTPUT,
                Status.PAUSED_BY_SYSTEM,
                Reason.REPEATED_FAILURES,
                False,
            ),
            (
                "other_writer_cannot_overwrite_pause",
                Status.PAUSED_BY_SYSTEM,
                Reason.REPEATED_FAILURES,
                Status.PAUSED_BY_SYSTEM,
                Reason.IGNORED,
                False,
            ),
            # The sweep owns both inactivity reasons, so reclassifying its own warning is not a
            # foreign write. Reclassification restarts the grace clock via `status_changed_at`.
            (
                "sweep_reclassifies_its_own_warning",
                Status.PENDING_PAUSE,
                Reason.NO_OUTPUT,
                Status.PENDING_PAUSE,
                Reason.IGNORED,
                True,
            ),
            (
                "sweep_resumes_either_of_its_own_reasons",
                Status.PENDING_PAUSE,
                Reason.IGNORED,
                Status.ACTIVE,
                Reason.NO_OUTPUT,
                True,
            ),
            (
                "other_writer_cannot_resume",
                Status.PAUSED_BY_SYSTEM,
                Reason.NO_OUTPUT,
                Status.ACTIVE,
                Reason.REPEATED_FAILURES,
                False,
            ),
            (
                "user_pause_blocks_system_pause",
                Status.PAUSED_BY_USER,
                None,
                Status.PAUSED_BY_SYSTEM,
                Reason.NO_OUTPUT,
                False,
            ),
            ("user_pause_blocks_system_resume", Status.PAUSED_BY_USER, None, Status.ACTIVE, Reason.NO_OUTPUT, False),
            (
                "pause_not_downgraded_to_warning",
                Status.PAUSED_BY_SYSTEM,
                Reason.NO_OUTPUT,
                Status.PENDING_PAUSE,
                Reason.NO_OUTPUT,
                False,
            ),
            (
                "same_state_is_a_noop",
                Status.PENDING_PAUSE,
                Reason.NO_OUTPUT,
                Status.PENDING_PAUSE,
                Reason.NO_OUTPUT,
                False,
            ),
        ]
    )
    def test_system_transition_ownership_rule(
        self,
        _name: str,
        start_status: SignalScoutConfig.Status,
        start_reason: SignalScoutConfig.PauseReason | None,
        new_status: SignalScoutConfig.Status,
        writer_reason: SignalScoutConfig.PauseReason,
        expect_applied: bool,
    ) -> None:
        config = self._config(status=start_status, pause_reason=start_reason)

        applied = config.transition_status_by_system(new_status, pause_reason=writer_reason)

        assert applied is expect_applied
        config.refresh_from_db()
        if expect_applied:
            assert config.status == new_status
            assert config.pause_reason == (None if new_status == Status.ACTIVE else writer_reason)
            assert config.enabled is (new_status in SignalScoutConfig.RUNNABLE_STATUSES)
            assert config.status_changed_at is not None
        else:
            assert config.status == start_status
            assert config.pause_reason == start_reason
            assert config.status_changed_at is None

    def test_system_writer_may_never_set_paused_by_user(self) -> None:
        config = self._config()
        with self.assertRaises(ValueError):
            config.transition_status_by_system(Status.PAUSED_BY_USER, pause_reason=Reason.NO_OUTPUT)

    def test_stale_system_decision_refused_after_a_newer_status_change(self) -> None:
        # A sweep evaluates, then a human moves the status before the sweep's write lands:
        # the write carries the evaluation time and must lose to the newer human change.
        config = self._config(status=Status.PENDING_PAUSE, pause_reason=Reason.NO_OUTPUT)
        evaluation_time = timezone.now()
        config.status = Status.ACTIVE
        config.pause_reason = None
        config.status_changed_at = timezone.now()
        config.status_changed_by = self.user
        config.save()

        applied = config.transition_status_by_system(
            Status.PAUSED_BY_SYSTEM, pause_reason=Reason.NO_OUTPUT, evaluated_at=evaluation_time
        )

        assert applied is False
        config.refresh_from_db()
        assert config.status == Status.ACTIVE

    def test_system_resume_refused_when_team_is_at_the_enabled_cap(self) -> None:
        paused = self._config(status=Status.PAUSED_BY_SYSTEM, pause_reason=Reason.REPEATED_FAILURES)
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-other")

        with patch("products.signals.backend.scout_harness.limits.MAX_ENABLED_SCOUTS_PER_TEAM", 1):
            applied = paused.transition_status_by_system(Status.ACTIVE, pause_reason=Reason.REPEATED_FAILURES)

        assert applied is False
        paused.refresh_from_db()
        assert paused.enabled is False

    def test_system_resume_starts_with_a_clean_failure_streak(self) -> None:
        # Without the reset, the first failed run after a resume would re-trip the breaker
        # off the stale pre-pause streak instead of five fresh failures.
        config = self._config(status=Status.PAUSED_BY_SYSTEM, pause_reason=Reason.REPEATED_FAILURES)
        SignalScoutConfig.objects.filter(pk=config.pk).update(consecutive_failure_count=5)

        applied = config.transition_status_by_system(Status.ACTIVE, pause_reason=Reason.REPEATED_FAILURES)

        assert applied is True
        config.refresh_from_db()
        assert config.consecutive_failure_count == 0

    def test_human_re_enable_starts_with_a_clean_failure_streak(self) -> None:
        config = self._config(status=Status.PAUSED_BY_SYSTEM, pause_reason=Reason.REPEATED_FAILURES)
        SignalScoutConfig.objects.filter(pk=config.pk).update(consecutive_failure_count=5)
        config.refresh_from_db()

        serializer = SignalScoutConfigUpdateSerializer(config, data={"enabled": True}, partial=True, context={})
        assert serializer.is_valid()
        config = serializer.save()

        config.refresh_from_db()
        assert config.status == Status.ACTIVE
        assert config.consecutive_failure_count == 0

    def test_system_transition_clears_the_human_attribution_stamp(self) -> None:
        # Without the clear, a system pause would keep pointing at whichever human made the
        # previous transition and read as their action.
        config = self._config()
        config.status_changed_by = self.user
        config.save(update_fields=["status_changed_by"])

        config.transition_status_by_system(Status.PAUSED_BY_SYSTEM, pause_reason=Reason.NO_OUTPUT)

        config.refresh_from_db()
        assert config.status_changed_by is None


class TestScoutStatusEnabledReconciliation(BaseTest):
    def test_create_with_enabled_false_records_a_user_pause(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo", enabled=False)

        assert config.status == Status.PAUSED_BY_USER
        assert config.status_changed_at is None

    def test_enabled_only_save_derives_status(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")

        config.enabled = False
        config.save(update_fields=["enabled"])

        config.refresh_from_db()
        assert config.status == Status.PAUSED_BY_USER
        assert config.status_changed_at is not None

    def test_enabled_only_save_resumes_a_system_pause(self) -> None:
        config = SignalScoutConfig.objects.create(
            team=self.team,
            skill_name="signals-scout-foo",
            enabled=False,
            status=Status.PAUSED_BY_SYSTEM,
            pause_reason=Reason.NO_OUTPUT,
        )

        config.enabled = True
        config.save(update_fields=["enabled"])

        config.refresh_from_db()
        assert config.status == Status.ACTIVE
        assert config.pause_reason is None

    def test_create_with_explicit_status_derives_enabled(self) -> None:
        config = SignalScoutConfig.objects.create(
            team=self.team,
            skill_name="signals-scout-foo",
            status=Status.PAUSED_BY_SYSTEM,
            pause_reason=Reason.NO_OUTPUT,
        )

        assert config.enabled is False
        assert config.status == Status.PAUSED_BY_SYSTEM

    def test_status_named_alone_in_update_fields_derives_enabled(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")

        config.status = Status.PAUSED_BY_SYSTEM
        config.pause_reason = Reason.NO_OUTPUT
        config.save(update_fields=["status", "pause_reason"])

        config.refresh_from_db()
        assert config.enabled is False


class TestScoutColdStartGrace(BaseTest):
    def test_grace_follows_creation_then_expires(self) -> None:
        with freeze_time("2026-07-01T00:00:00Z"):
            config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        with freeze_time("2026-07-10T00:00:00Z"):
            assert config.in_cold_start_grace() is True
        with freeze_time("2026-07-16T00:00:00Z"):
            assert config.in_cold_start_grace() is False

    def test_human_reactivation_grants_a_fresh_window(self) -> None:
        with freeze_time("2026-06-01T00:00:00Z"):
            config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo", enabled=False)
        with freeze_time("2026-07-15T00:00:00Z"):
            serializer = SignalScoutConfigUpdateSerializer(
                config, data={"enabled": True}, partial=True, context={"request": self._request_stub()}
            )
            assert serializer.is_valid()
            config = serializer.save()
        with freeze_time("2026-07-20T00:00:00Z"):
            assert config.in_cold_start_grace() is True

    def test_any_reactivation_grants_a_fresh_window(self) -> None:
        # Deliberately independent of attribution, so the window survives the re-enabling
        # user's account being deleted (the FK is SET_NULL).
        with freeze_time("2026-06-01T00:00:00Z"):
            config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo", enabled=False)
        with freeze_time("2026-07-15T00:00:00Z"):
            config.enabled = True
            config.save(update_fields=["enabled"])
        with freeze_time("2026-07-20T00:00:00Z"):
            assert config.in_cold_start_grace() is True

    def test_a_system_transition_does_not_re_anchor(self) -> None:
        # A sweep's own pending_pause warning re-anchoring grace would put the scout back
        # under protection and the sweep could never pause anything.
        with freeze_time("2026-06-01T00:00:00Z"):
            config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        with freeze_time("2026-07-15T00:00:00Z"):
            config.transition_status_by_system(Status.PENDING_PAUSE, pause_reason=Reason.NO_OUTPUT)
        with freeze_time("2026-07-20T00:00:00Z"):
            assert config.in_cold_start_grace() is False

    def _request_stub(self):
        class _Request:
            def __init__(self, user):
                self.user = user

        return _Request(self.user)
