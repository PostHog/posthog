from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from parameterized import parameterized

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.lazy_seed import HARNESS_SEEDED_BY
from products.skills.backend.models.skills import LLMSkill

_OPERATIONAL_SCOUT = "signals-scout-inbox-validation"
_READ_PAYLOAD = "products.signals.backend.scout_harness.config_registry._read_flag_payload"


class TestResumeSetupPausedOperationalScouts(BaseTest):
    def _paused_config(
        self, skill_name: str = _OPERATIONAL_SCOUT, *, gap: timedelta = timedelta(seconds=10), by_user: bool = False
    ) -> SignalScoutConfig:
        LLMSkill.objects.create(
            team=self.team, name=skill_name, description="d", body="b", metadata={"seeded_by": HARNESS_SEEDED_BY}
        )
        config = SignalScoutConfig.objects.create(team=self.team, skill_name=skill_name, enabled=True)
        SignalScoutConfig.all_teams.filter(pk=config.pk).update(
            enabled=False,
            status=SignalScoutConfig.Status.PAUSED_BY_USER,
            status_changed_at=config.created_at + gap,
            status_changed_by=self.user if by_user else None,
        )
        config.refresh_from_db()
        return config

    def _run(self, *args: str, payload: dict[str, Any] | None = None) -> None:
        with patch(_READ_PAYLOAD, return_value=payload):
            call_command("resume_setup_paused_operational_scouts", *args)

    def test_dry_run_changes_nothing_and_apply_resumes_the_setup_pause(self) -> None:
        config = self._paused_config()

        self._run()
        config.refresh_from_db()
        assert config.status == SignalScoutConfig.Status.PAUSED_BY_USER

        self._run("--apply", "--team-id", str(self.team.id))
        config.refresh_from_db()
        assert config.status == SignalScoutConfig.Status.ACTIVE
        assert config.enabled is True
        assert config.auto_pause_exempt is True

    @parameterized.expand(
        [
            ("attributed_pause", {"by_user": True}),
            ("late_pause", {"gap": timedelta(hours=1)}),
            ("specialist", {"skill_name": "signals-scout-general"}),
        ]
    )
    def test_apply_leaves_pauses_the_setup_flow_did_not_make(self, _name: str, kwargs: dict[str, Any]) -> None:
        config = self._paused_config(**kwargs)

        self._run("--apply")

        config.refresh_from_db()
        assert config.status == SignalScoutConfig.Status.PAUSED_BY_USER
        assert config.enabled is False

    def test_apply_leaves_a_withheld_scout_paused(self) -> None:
        config = self._paused_config()

        self._run("--apply", payload={"default_team_config": {"withheld_skills": [_OPERATIONAL_SCOUT]}})

        config.refresh_from_db()
        assert config.status == SignalScoutConfig.Status.PAUSED_BY_USER
