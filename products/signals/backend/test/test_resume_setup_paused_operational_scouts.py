from datetime import timedelta
from io import StringIO
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.management import call_command

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.lazy_seed import HARNESS_SEEDED_BY
from products.skills.backend.models.skills import LLMSkill

_OPERATIONAL_SCOUT = "signals-scout-inbox-validation"
_READ_PAYLOAD = "products.signals.backend.scout_harness.config_registry._read_flag_payload"


class TestResumeSetupPausedOperationalScouts(APIBaseTest):
    def _paused_config(
        self, skill_name: str = _OPERATIONAL_SCOUT, *, client: str | None = "mcp", log: bool = True
    ) -> SignalScoutConfig:
        LLMSkill.objects.create(
            team=self.team, name=skill_name, description="d", body="b", metadata={"seeded_by": HARNESS_SEEDED_BY}
        )
        config = SignalScoutConfig.objects.create(team=self.team, skill_name=skill_name, enabled=True)
        headers = {"X-PostHog-Client": client} if client else {}
        response = self.client.patch(
            f"/api/projects/{self.team.id}/signals/scout/configs/{config.id}/",
            data={"enabled": False},
            format="json",
            headers=headers,
        )
        assert response.status_code == 200, response.json()
        if not log:
            ActivityLog.objects.filter(scope="SignalScoutConfig", item_id=str(config.id)).delete()
        config.refresh_from_db()
        assert config.status == SignalScoutConfig.Status.PAUSED_BY_USER
        assert config.status_changed_by_id == self.user.id
        return config

    def _run(self, *args: str, payload: dict[str, Any] | None = None) -> str:
        out = StringIO()
        with patch(_READ_PAYLOAD, return_value=payload):
            call_command("resume_setup_paused_operational_scouts", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_changes_nothing_and_apply_resumes_the_mcp_pause(self) -> None:
        config = self._paused_config()

        output = self._run()
        config.refresh_from_db()
        assert config.status == SignalScoutConfig.Status.PAUSED_BY_USER
        assert "Pause sources: mcp 1" in output

        self._run("--apply", "--team-id", str(self.team.id))
        config.refresh_from_db()
        assert config.status == SignalScoutConfig.Status.ACTIVE
        assert config.enabled is True
        assert config.auto_pause_exempt is True

    @parameterized.expand(
        [
            ("ui_pause", {"client": None}, "ui 1"),
            ("no_log_entry", {"log": False}, "no_log 1"),
            ("specialist", {"skill_name": "signals-scout-general"}, "none"),
        ]
    )
    def test_apply_leaves_pauses_the_setup_flow_did_not_make(
        self, _name: str, kwargs: dict[str, Any], sources: str
    ) -> None:
        config = self._paused_config(**kwargs)

        output = self._run("--apply")

        config.refresh_from_db()
        assert config.status == SignalScoutConfig.Status.PAUSED_BY_USER
        assert config.enabled is False
        assert f"Pause sources: {sources}" in output

    def test_max_gap_leaves_a_late_mcp_pause(self) -> None:
        config = self._paused_config()
        assert config.status_changed_at is not None
        SignalScoutConfig.all_teams.filter(pk=config.pk).update(
            created_at=config.status_changed_at - timedelta(hours=1)
        )

        self._run("--apply", "--max-gap-seconds", "300")

        config.refresh_from_db()
        assert config.status == SignalScoutConfig.Status.PAUSED_BY_USER

    def test_apply_leaves_a_withheld_scout_paused(self) -> None:
        config = self._paused_config()

        self._run("--apply", payload={"default_team_config": {"withheld_skills": [_OPERATIONAL_SCOUT]}})

        config.refresh_from_db()
        assert config.status == SignalScoutConfig.Status.PAUSED_BY_USER
