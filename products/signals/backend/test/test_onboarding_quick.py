from contextlib import ExitStack, contextmanager
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership
from posthog.models.integration import Integration
from posthog.models.team.team import Team

from products.event_definitions.backend.models import EventDefinition
from products.signals.backend.models import SignalScoutConfig, SignalSourceConfig, SignalTeamConfig
from products.signals.backend.presentation.onboarding import InboxOnboardingDraftSerializer
from products.signals.backend.trial.billing import TrialBillingStatus, TrialContinuation

COMPLETED_EVENT = "self-driving onboarding completed"


class TestQuickActivation(APIBaseTest):
    def _project(self, organization: Organization) -> Team:
        team = Team.objects.create(organization=organization, name="Quick setup project", ingested_event=True)
        for name in ("$exception", "$pageview"):
            EventDefinition.objects.create(
                team=team, project_id=team.project_id, name=name, last_seen_at=timezone.now()
            )
        Integration.objects.create(team=team, kind="github")
        SignalSourceConfig.objects.create(
            team=team, source_product="error_tracking", source_type="issue_reopened", enabled=False
        )
        return team

    def _second_organization(self) -> Organization:
        organization = Organization.objects.create(name="Second organization")
        OrganizationMembership.objects.create(
            user=self.user, organization=organization, level=OrganizationMembership.Level.ADMIN
        )
        return organization

    @contextmanager
    def _environment(self, *, usage_based_pricing: bool):
        github = MagicMock()
        github.return_value.list_repositories.return_value = ([{"full_name": "example-org/web-app"}], False)
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "products.signals.backend.onboarding_completion.InboxOnboardingReconciler.has_repository",
                    return_value=True,
                )
            )
            stack.enter_context(patch("products.signals.backend.onboarding_quick.GitHubIntegration", github))
            stack.enter_context(
                patch(
                    "posthoganalytics.feature_enabled",
                    side_effect=lambda key, *args, **kwargs: (
                        usage_based_pricing if key == "self-driving-ubp" else False
                    ),
                )
            )
            stack.enter_context(
                patch(
                    "products.signals.backend.first_report_experiment.posthoganalytics.get_feature_flag",
                    return_value=False,
                )
            )
            stack.enter_context(
                patch(
                    "products.signals.backend.trial.billing.TrialBilling.status",
                    return_value=TrialBillingStatus(ready=True, continuation=TrialContinuation.PAYMENT),
                )
            )
            stack.enter_context(patch("products.signals.backend.trial.service.report_signals_trial_grant"))
            stack.enter_context(
                patch("products.signals.backend.views.SignalSourceConfigViewSet._trigger_error_tracking_backfill")
            )
            launch = stack.enter_context(patch("products.signals.backend.tasks.launch_inbox_onboarding_job.delay"))
            capture = stack.enter_context(patch("posthog.event_usage.posthoganalytics.capture"))
            stack.enter_context(self.captureOnCommitCallbacks(execute=True))
            yield launch, capture

    def _browser_quick_setup(self, team: Team, *, usage_based_pricing: bool) -> None:
        # The request sequence of `activate` in inboxSetupLogic.ts for quick setup, with the draft
        # that `quickInboxSetupDraft` builds from this fixture's data.
        base = f"/api/projects/{team.id}/signals"
        assert self.client.post(f"{base}/scout/configs/sync/?surface=onboarding").status_code == 200
        general = next(
            config
            for config in self.client.get(f"{base}/scout/configs/").json()
            if config["skill_name"] == "signals-scout-general"
        )
        draft: dict[str, Any] = {
            "onboarding_origin": "agent",
            "step": "github",
            "setup_mode": "quick",
            "sources": [
                {"source_product": "error_tracking", "source_type": source_type, "enabled": True}
                for source_type in ("issue_created", "issue_reopened", "issue_spiking")
            ]
            + [
                {"source_product": "analytics", "source_type": "anomaly_investigation", "enabled": True},
                {"source_product": "health_checks", "source_type": "health_issue", "enabled": True},
            ],
            "scanner_ids": [],
            "suggestions": [
                {
                    "id": f"builtin:{general['id']}",
                    "kind": "canonical",
                    "skill_name": "signals-scout-general",
                    "title": "General scout",
                    "why_here": "Explore available project data.",
                    "description": "",
                    "draft_body": "",
                    "proposed_config": {
                        "run_interval_minutes": general["run_interval_minutes"],
                        "run_cron_schedule": general["run_cron_schedule"],
                        "emit": True,
                    },
                    "gap": True,
                    "confidence": "medium",
                }
            ],
            "automatic_implementation": not usage_based_pricing,
            "implementation_priority": "P1",
        }
        assert self.client.post(f"{base}/onboarding/", draft, format="json").status_code == 200
        draft["activation_scouts"] = ["signals-scout-general"]
        assert self.client.post(f"{base}/onboarding/", draft, format="json").status_code == 200
        assert self.client.post(f"{base}/config/", {"autostart_enabled": False}, format="json").status_code == 200
        existing = {
            (row["source_product"], row["source_type"]): row["id"]
            for row in self.client.get(f"{base}/source_configs/?limit=1000").json()["results"]
        }
        for source in [
            *draft["sources"],
            {"source_product": "signals_scout", "source_type": "cross_source_issue", "enabled": True},
        ]:
            key = (source["source_product"], source["source_type"])
            if key in existing:
                response = self.client.patch(f"{base}/source_configs/{existing[key]}/", {"enabled": True})
            else:
                response = self.client.post(f"{base}/source_configs/", source, format="json")
            assert response.status_code in (200, 201), response.json()
        response = self.client.post(
            f"{base}/scout/configs/",
            {
                "skill_name": "signals-scout-general",
                "enabled": True,
                "emit": True,
                "run_cron_schedule": general["run_cron_schedule"],
                "run_interval_minutes": general["run_interval_minutes"],
            },
            format="json",
        )
        assert response.status_code in (200, 201), response.json()
        response = self.client.post(f"{base}/onboarding/complete/", draft, format="json")
        assert response.status_code == 200, response.json()

    def _server_quick_setup(self, team: Team) -> dict[str, Any]:
        url = f"/api/projects/{team.id}/signals/onboarding/quick_activation/"
        plan = self.client.get(url).json()
        assert plan["can_activate"] is True, plan["blockers"]
        assert plan["github"]["repositories"] == ["example-org/web-app"]
        response = self.client.post(url, {"plan_fingerprint": plan["fingerprint"]}, format="json")
        assert response.status_code == 200, response.json()
        return response.json()

    def _saved_setup(self, team: Team) -> dict[str, Any]:
        config = SignalTeamConfig.objects.get(team=team)
        onboarding = config.onboarding or {}
        draft = dict(onboarding["draft"])
        cosmetic = ("id", "title", "why_here")
        draft["suggestions"] = [
            {key: value for key, value in item.items() if key not in cosmetic} for item in draft["suggestions"]
        ]
        return {
            "autostart_enabled": config.autostart_enabled,
            "default_autostart_priority": config.default_autostart_priority,
            "draft": draft,
            "first_report_variant": onboarding.get("first_report_variant"),
            "jobs": {job: status for job, status in onboarding["jobs"].items() if job != "error_tracking_backfill"},
            "sources": sorted(
                SignalSourceConfig.objects.filter(team=team).values_list("source_product", "source_type", "enabled")
            ),
            "scouts": sorted(
                SignalScoutConfig.objects.for_team(team.id)
                .filter(enabled=True)
                .values_list("skill_name", "emit", "run_interval_minutes", "run_cron_schedule", "status")
            ),
        }

    @parameterized.expand([("legacy_pricing", False), ("usage_based_pricing", True)])
    def test_server_activation_matches_browser_quick_setup(self, _name: str, usage_based_pricing: bool) -> None:
        browser_team = self._project(self.organization)
        server_team = self._project(self._second_organization())
        with self._environment(usage_based_pricing=usage_based_pricing) as (launch, capture):
            self._browser_quick_setup(browser_team, usage_based_pricing=usage_based_pricing)
            state = self._server_quick_setup(server_team)

        assert state["completed_at"] is not None
        assert self._saved_setup(server_team) == self._saved_setup(browser_team)
        server_onboarding = SignalTeamConfig.objects.get(team=server_team).onboarding or {}
        assert server_onboarding["draft"]["onboarding_origin"] == "agent"
        assert InboxOnboardingDraftSerializer(data=server_onboarding["draft"]).is_valid()
        assert server_onboarding["jobs"]["error_tracking_backfill"] == "pending"
        assert (server_team.id, "error_tracking_backfill") in {call.args for call in launch.call_args_list}
        methods = {
            call.kwargs["properties"]["project_id"]: call.kwargs["properties"]["activation_method"]
            for call in capture.call_args_list
            if call.kwargs.get("event") == COMPLETED_EVENT
        }
        assert methods == {browser_team.id: "page", server_team.id: "mcp_tool"}

    @parameterized.expand(
        [
            ("plan_changed", "plan_changed"),
            ("github_not_connected", "github_not_connected"),
            ("setup_started", "setup_started"),
        ]
    )
    def test_activation_refuses_without_changing_settings(self, change: str, code: str) -> None:
        team = self._project(self.organization)
        url = f"/api/projects/{team.id}/signals/onboarding/quick_activation/"
        with self._environment(usage_based_pricing=False):
            fingerprint = self.client.get(url).json()["fingerprint"]
            if change == "plan_changed":
                SignalSourceConfig.objects.create(
                    team=team, source_product="health_checks", source_type="health_issue", enabled=False
                )
            elif change == "github_not_connected":
                Integration.objects.filter(team=team, kind="github").delete()
            else:
                self.client.post(
                    f"/api/projects/{team.id}/signals/onboarding/",
                    {
                        "step": "signals",
                        "sources": [],
                        "scanner_ids": [],
                        "suggestions": [],
                        "automatic_implementation": False,
                        "implementation_priority": "P1",
                    },
                    format="json",
                )
            response = self.client.post(url, {"plan_fingerprint": fingerprint}, format="json")

        assert response.status_code == 409, response.json()
        assert response.json()["code"] == code
        assert not (SignalTeamConfig.objects.get(team=team).onboarding or {}).get("completed_at")
        assert not SignalSourceConfig.objects.filter(team=team, enabled=True).exists()
        assert not SignalScoutConfig.objects.for_team(team.id).filter(enabled=True).exists()
