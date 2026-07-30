from freezegun import freeze_time
from posthog.test.base import BaseTest

from parameterized import parameterized

from products.signals.backend.models import SignalScoutConfig

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
                Reason.NO_OUTPUT,
                Status.PAUSED_BY_SYSTEM,
                Reason.IGNORED,
                False,
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
            config.enabled = True
            config.save(update_fields=["enabled"])
        with freeze_time("2026-07-20T00:00:00Z"):
            assert config.in_cold_start_grace() is True

    def test_a_paused_scout_does_not_re_anchor_on_status_change(self) -> None:
        with freeze_time("2026-06-01T00:00:00Z"):
            config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        with freeze_time("2026-07-15T00:00:00Z"):
            config.transition_status_by_system(Status.PAUSED_BY_SYSTEM, pause_reason=Reason.NO_OUTPUT)
        with freeze_time("2026-07-20T00:00:00Z"):
            assert config.in_cold_start_grace() is False
