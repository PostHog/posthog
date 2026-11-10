from collections.abc import Iterator
from contextlib import contextmanager
from io import StringIO

from posthog.test.base import APIBaseTest

from django.core.management import call_command

from parameterized import parameterized

from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.activity_logging.utils import activity_storage

from products.signals.backend.models import SignalScoutConfig, SignalTeamConfig
from products.signals.backend.scout_harness.config_registry import (
    unchosen_general_scout_configs,
    unenroll_unchosen_general_scout,
)
from products.signals.backend.scout_harness.lazy_seed import HARNESS_SEEDED_BY, _compute_row_hash
from products.skills.backend.models.skills import LLMSkill

_GENERAL = "signals-scout-general"
_COMPLETED = {"completed_at": "2026-11-01T00:00:00Z"}


class TestUnenrollUnchosenGeneralScouts(APIBaseTest):
    def _seed_general_skill(self, *, edited: bool = False) -> None:
        skill = LLMSkill.objects.create(
            team=self.team,
            name=_GENERAL,
            description="d",
            body="canonical body",
            allowed_tools=[],
            metadata={"seeded_by": HARNESS_SEEDED_BY},
            version=1,
            is_latest=True,
        )
        skill.metadata["canonical_hash"] = _compute_row_hash(skill, [])
        if edited:
            skill.body = "the team's own body"
        skill.save()

    @contextmanager
    def _in_request_of(self, user: User) -> Iterator[None]:
        activity_storage.set_user(user)
        try:
            yield
        finally:
            activity_storage.clear_user()

    def _run(self, *args: str) -> str:
        out = StringIO()
        call_command("unenroll_unchosen_general_scouts", *args, stdout=out)
        return out.getvalue()

    def _log_count(self, config: SignalScoutConfig) -> int:
        return ActivityLog.objects.filter(scope="SignalScoutConfig", item_id=str(config.id)).count()

    @parameterized.expand(
        [
            ("unchosen", {}, True),
            (
                "pending_pause",
                {
                    "config": {
                        "status": SignalScoutConfig.Status.PENDING_PAUSE,
                        "pause_reason": SignalScoutConfig.PauseReason.NO_OUTPUT,
                    }
                },
                True,
            ),
            ("person_enabled", {"config": {"enabled_by": "user"}}, False),
            ("person_created", {"config": {"created_by": "user"}}, False),
            ("setup_completed", {"setup": "team"}, False),
            ("child_setup_completed", {"setup": "child"}, False),
            ("paused", {"config": {"enabled": False}}, False),
            ("edited_skill", {"edited": True}, False),
            ("renamed_duplicate", {"config": {"skill_name": "signals-scout-general-copy"}}, False),
            ("team_chose_other_scout", {"other_scout": True}, False),
            ("person_set_interval_then_deleted", {"person_edit": {"run_interval_minutes": 60}}, False),
            ("person_set_emit_then_deleted", {"person_edit": {"emit": False}}, False),
            ("seeded_in_a_request", {"seed_in_request": True}, True),
            ("label_backfilled_in_a_request", {"person_edit": {"display_name": "General"}}, True),
        ]
    )
    def test_apply_switches_off_only_unchosen_general_scouts(
        self, _name: str, case: dict, expect_changed: bool
    ) -> None:
        self._seed_general_skill(edited=case.get("edited", False))
        fields = {"skill_name": _GENERAL, **case.get("config", {})}
        for user_field in ("enabled_by", "created_by"):
            if fields.get(user_field) == "user":
                fields[user_field] = self.user
        if case.get("seed_in_request"):
            with self._in_request_of(self.user):
                config = SignalScoutConfig.objects.create(team=self.team, **fields)
        else:
            config = SignalScoutConfig.objects.create(team=self.team, **fields)
        if case.get("setup") == "team":
            SignalTeamConfig.objects.create(team=self.team, onboarding=_COMPLETED)
        elif case.get("setup") == "child":
            child = Team.objects.create(organization=self.organization, parent_team=self.team)
            SignalTeamConfig.objects.create(team=child, onboarding=_COMPLETED)
        if case.get("other_scout"):
            SignalScoutConfig.objects.create(
                team=self.team, skill_name="signals-scout-product-analytics", enabled_by=self.user
            )
        if edit := case.get("person_edit"):
            editor = User.objects.create_and_join(self.organization, "editor@example.com", None)
            with self._in_request_of(editor):
                for name, value in edit.items():
                    setattr(config, name, value)
                config.save()
            editor.delete()
        config.refresh_from_db()
        enabled_before, status_before, logs_before = config.enabled, config.status, self._log_count(config)

        output = self._run("--team-ids", str(self.team.id))

        config.refresh_from_db()
        assert (config.enabled, config.status) == (enabled_before, status_before)
        assert f"Matched: {int(expect_changed)}" in output

        output = self._run("--apply")

        config.refresh_from_db()
        assert f"Changed: {int(expect_changed)}" in output
        if expect_changed:
            assert config.enabled is False
            assert config.status == SignalScoutConfig.Status.PAUSED_BY_USER
            assert config.status_changed_by_id is None
            assert self._log_count(config) == logs_before + 1
        else:
            assert (config.enabled, config.status) == (enabled_before, status_before)
            assert self._log_count(config) == logs_before

        assert "Changed: 0" in self._run("--apply")
        assert self._log_count(config) == logs_before + int(expect_changed)

    def test_unenroll_rechecks_setup_completed_after_the_batch_read(self) -> None:
        self._seed_general_skill()
        SignalScoutConfig.objects.create(team=self.team, skill_name=_GENERAL)
        stale = unchosen_general_scout_configs().get(team_id=self.team.id)
        SignalTeamConfig.objects.create(team=self.team, onboarding=_COMPLETED)

        assert unenroll_unchosen_general_scout(stale) is False

        stale.refresh_from_db()
        assert stale.enabled is True

    def test_team_ids_limits_the_run(self) -> None:
        self._seed_general_skill()
        config = SignalScoutConfig.objects.create(team=self.team, skill_name=_GENERAL)

        output = self._run("--apply", "--team-ids", str(self.team.id + 1))

        config.refresh_from_db()
        assert config.enabled is True
        assert "Matched: 0" in output
