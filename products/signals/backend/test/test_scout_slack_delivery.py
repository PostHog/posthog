import json

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.conf import settings

from celery.exceptions import Retry
from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.models import Team
from posthog.models.integration import Integration

from products.signals.backend.facade.slack_actions import SLACK_CREATE_PR_ACTION_ID
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalScoutEmission, SignalScoutRun
from products.signals.backend.scout_harness.slack_delivery import (
    ScoutSlackPermanentDeliveryError,
    post_scout_emission_to_slack,
    post_scout_report_to_slack,
)
from products.signals.backend.scout_harness.slack_delivery_queue import queue_configured_scout_slack_delivery
from products.signals.backend.tasks import deliver_scout_slack_output, enqueue_scout_slack_delivery


class FakeSlackResponse(dict):
    def __init__(self, data: dict, headers: dict | None = None) -> None:
        super().__init__(data)
        self.headers = headers or {}


class TestScoutSlackDelivery(BaseTest):
    def _make_emission(self, description: str = "**Checkout** failures") -> SignalScoutEmission:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(
            team=self.team,
            title="scout run",
            description="scout run",
            origin_product=Task.OriginProduct.SIGNALS_SCOUT,
        )
        task_run = TaskRun.objects.create(task=task, team=self.team)
        run = SignalScoutRun.all_teams.create(
            task_run=task_run,
            team=self.team,
            skill_name="signals-scout-error-tracking",
            skill_version=1,
        )
        return SignalScoutEmission.all_teams.create(
            team=self.team,
            scout_run=run,
            finding_id="checkout/500s",
            description=description,
            weight=1.0,
            confidence=0.84,
            severity="P1",
            tags=["checkout", "regression"],
            source_id=f"run:{run.id}:finding:checkout-500s",
        )

    def test_posts_safe_mrkdwn_but_does_not_invite_followup_for_child_environment(self) -> None:
        emission = self._make_emission(
            "**Checkout** failures [trace](https://example.com/trace) <!channel> [ping](!here)"
        )
        child_team = Team.objects.create(
            organization=self.organization,
            project=self.team.project,
            parent_team=self.team,
            name="Child environment",
        )
        integration = Integration.objects.create(team=child_team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()
        fake_client.chat_postMessage.return_value = {"ts": "1785418710.000100"}

        with patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration:
            slack_integration.return_value.client = fake_client
            post_scout_emission_to_slack(
                emission,
                integration_id=integration.id,
                channel="CSCOUTS|#scout-findings",
            )

        call = fake_client.chat_postMessage.call_args_list[0].kwargs
        assert call["channel"] == "CSCOUTS"
        assert call["client_msg_id"] == str(emission.id)
        assert "thread_ts" not in call
        section = call["blocks"][1]["text"]["text"]
        assert "*Checkout*" in section
        assert "<https://example.com/trace|trace>" in section
        assert "<!channel>" not in section
        assert "<!here>" not in section
        assert "&lt;!channel&gt;" in section
        assert call["blocks"][-1]["elements"][0]["url"] == (
            f"{settings.SITE_URL}/project/{self.team.id}/inbox/scouts/signals-scout-error-tracking/checkout%2F500s"
        )
        assert fake_client.chat_postMessage.call_count == 1

    def test_posts_report_with_safe_markdown_and_delivery_id(self) -> None:
        emission = self._make_emission()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout failures",
            summary="**Checkout** failed for <!channel> [trace](https://example.com/trace)",
        )
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()
        fake_client.chat_postMessage.return_value = {"ts": "1785418710.000200"}
        delivery_id = "01864f4c-6957-7d3f-8d85-1d775e527265"

        with patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration:
            slack_integration.return_value.client = fake_client
            deliver_scout_slack_output.run(
                self.team.id,
                "report",
                str(report.id),
                str(emission.scout_run_id),
                delivery_id,
                integration.id,
                "CSCOUTS|#scout-findings",
            )

        call = fake_client.chat_postMessage.call_args_list[0].kwargs
        assert call["channel"] == "CSCOUTS"
        assert call["client_msg_id"] == delivery_id
        assert "thread_ts" not in call
        section = call["blocks"][2]["text"]["text"]
        assert "*Checkout*" in section
        assert "<!channel>" not in section
        assert "&lt;!channel&gt;" in section
        assert "<https://example.com/trace|trace>" in section
        assert call["blocks"][-1]["elements"][0]["url"] == (
            f"{settings.SITE_URL}/project/{self.team.id}/inbox/reports/{report.id}"
        )
        reply = fake_client.chat_postMessage.call_args_list[1].kwargs
        assert reply["thread_ts"] == "1785418710.000200"
        assert reply["blocks"][0]["type"] == "context"

    @parameterized.expand(
        [
            # A report the pipeline resolved a repo for is the case the button exists for.
            ("repo_selected", {"repository": "PostHog/posthog", "reason": "owns the code"}, False, True),
            # A scout that filed a no-code report passes NO_REPO, which persists as a null repository.
            ("no_repo_sentinel", {"repository": None, "reason": "nothing to fix in code"}, False, False),
            ("no_repo_selection", None, False, False),
            # Delivery accepts any connection in the project, but the webhook authorizes a report
            # action against the connection's own team — so a button here would be dropped on click.
            ("cross_environment_connection", {"repository": "PostHog/posthog", "reason": "owns it"}, True, False),
        ]
    )
    def test_report_offers_create_pr_only_when_a_pr_can_be_opened(
        self, _name: str, repo_selection: dict | None, connect_from_child_environment: bool, expect_button: bool
    ) -> None:
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Stale pricing",
            summary="Pricing page is out of date",
        )
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            content=json.dumps(
                {
                    "actionability": "immediately_actionable",
                    "explanation": "The pricing table is hardcoded.",
                    "already_addressed": False,
                }
            ),
        )
        if repo_selection is not None:
            SignalReportArtefact.objects.create(
                team=self.team,
                report=report,
                type=SignalReportArtefact.ArtefactType.REPO_SELECTION,
                content=json.dumps(repo_selection),
            )
        run = self._make_emission().scout_run
        integration_team = self.team
        if connect_from_child_environment:
            integration_team = Team.objects.create(
                organization=self.organization,
                project=self.team.project,
                parent_team=self.team,
                name="Child environment",
            )
        integration = Integration.objects.create(team=integration_team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()
        fake_client.chat_postMessage.return_value = {"ts": "1785418710.000300"}

        with patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration:
            slack_integration.return_value.client = fake_client
            post_scout_report_to_slack(
                report,
                run,
                delivery_id=str(report.id),
                integration_id=integration.id,
                channel="CSCOUTS|#scout-findings",
            )

        elements = fake_client.chat_postMessage.call_args_list[0].kwargs["blocks"][-1]["elements"]
        create_pr = [el for el in elements if el.get("action_id") == SLACK_CREATE_PR_ACTION_ID]
        assert bool(create_pr) is expect_button
        # The link out to the report is never displaced by the new button.
        assert elements[0]["text"]["text"] == "View report in PostHog"
        if not expect_button:
            return
        # The webhook re-resolves everything from these three values, so they have to be complete.
        assert json.loads(create_pr[0]["value"]) == {
            "integration_id": integration.id,
            "report_id": str(report.id),
            "team_id": self.team.id,
        }

    def test_reply_posted_regardless_of_ai_approval(self) -> None:
        # The Slack follow-up invite is unconditional — no AI-approval gate on scout output.
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        emission = self._make_emission()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout failures",
            summary="Checkout failed",
        )
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()
        fake_client.chat_postMessage.return_value = {"ts": "1785418710.000400"}

        with patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration:
            slack_integration.return_value.client = fake_client
            deliver_scout_slack_output.run(
                self.team.id,
                "report",
                str(report.id),
                str(emission.scout_run_id),
                "01864f4c-6957-7d3f-8d85-1d775e527265",
                integration.id,
                "CSCOUTS|#scout-findings",
            )

        assert fake_client.chat_postMessage.call_count == 2
        reply = fake_client.chat_postMessage.call_args_list[1].kwargs
        assert reply["thread_ts"] == "1785418710.000400"

    def test_reply_transport_failure_does_not_fail_delivery(self) -> None:
        # The parent message already landed, so a failing follow-up reply — even a non-SlackApiError
        # transport error — must be swallowed rather than fail the task and retry the whole delivery.
        emission = self._make_emission()
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()
        fake_client.chat_postMessage.side_effect = [{"ts": "1785418710.000500"}, ConnectionError("boom")]

        with patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration:
            slack_integration.return_value.client = fake_client
            post_scout_emission_to_slack(
                emission,
                integration_id=integration.id,
                channel="CSCOUTS|#scout-findings",
            )

        assert fake_client.chat_postMessage.call_count == 2

    def test_task_skips_report_suppressed_before_delivery(self) -> None:
        emission = self._make_emission()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.SUPPRESSED,
            title="Unsafe report",
            summary="This report must not leave PostHog.",
        )
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()

        with patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration:
            slack_integration.return_value.client = fake_client
            deliver_scout_slack_output.run(
                self.team.id,
                "report",
                str(report.id),
                str(emission.scout_run_id),
                "01864f4c-6957-7d3f-8d85-1d775e527265",
                integration.id,
                "CSCOUTS|#scout-findings",
            )

        fake_client.chat_postMessage.assert_not_called()

    def test_task_retries_transient_delivery_failure(self) -> None:
        emission = self._make_emission()
        error = SlackApiError(
            message="rate limited",
            response=FakeSlackResponse({"error": "ratelimited"}, headers={"retry-after": "120"}),
        )

        with patch(
            "products.signals.backend.tasks.post_scout_emission_to_slack",
            side_effect=error,
        ):
            with pytest.raises(Retry) as retry:
                deliver_scout_slack_output.apply(
                    args=(
                        self.team.id,
                        "finding",
                        str(emission.id),
                        str(emission.scout_run_id),
                        str(emission.id),
                        1,
                        "CSCOUTS|#scout-findings",
                    ),
                    throw=True,
                )

        assert retry.value.when == 120

    def test_task_captures_known_permanent_failure_without_retry(self) -> None:
        emission = self._make_emission()
        error = ScoutSlackPermanentDeliveryError("channel unavailable", error_code="channel_not_found")

        with (
            patch("products.signals.backend.tasks.post_scout_emission_to_slack", side_effect=error),
            patch("products.signals.backend.tasks.capture_exception") as capture,
        ):
            deliver_scout_slack_output.run(
                self.team.id,
                "finding",
                str(emission.id),
                str(emission.scout_run_id),
                str(emission.id),
                9,
                "CMISSING|#missing",
            )

        capture.assert_called_once_with(
            error,
            {
                "team_id": self.team.id,
                "output_type": "finding",
                "output_id": str(emission.id),
                "run_id": str(emission.scout_run_id),
                "integration_id": 9,
                "error_code": "channel_not_found",
            },
        )

    def test_task_captures_transient_failure_after_retries_are_exhausted(self) -> None:
        emission = self._make_emission()
        error = ConnectionError("Slack unavailable")

        with (
            patch("products.signals.backend.tasks.post_scout_emission_to_slack", side_effect=error),
            patch("products.signals.backend.tasks.capture_exception") as capture,
        ):
            result = deliver_scout_slack_output.apply(
                args=(
                    self.team.id,
                    "finding",
                    str(emission.id),
                    str(emission.scout_run_id),
                    str(emission.id),
                    9,
                    "CSCOUTS|#scout-findings",
                ),
                retries=5,
                throw=True,
            )

        assert result.successful()
        capture.assert_called_once_with(
            error,
            {
                "team_id": self.team.id,
                "output_type": "finding",
                "output_id": str(emission.id),
                "run_id": str(emission.scout_run_id),
                "integration_id": 9,
                "error_code": None,
                "attempts": 6,
            },
        )

    def test_enqueue_captures_broker_failure(self) -> None:
        error = ConnectionError("broker unavailable")

        with (
            patch.object(deliver_scout_slack_output, "delay", side_effect=error),
            patch("products.signals.backend.tasks.capture_exception") as capture,
        ):
            enqueue_scout_slack_delivery(
                team_id=self.team.id,
                output_type="report",
                output_id="ddab8ee5-2bb8-4226-b145-6732d31dc344",
                run_id="e3865391-bc89-44e6-86f7-2d4405627daf",
                delivery_id="b316c1d1-6901-49eb-8223-96d4df69f67f",
                integration_id=9,
                channel="CSCOUTS|#scout-findings",
            )

        capture.assert_called_once_with(
            error,
            {
                "team_id": self.team.id,
                "output_type": "report",
                "output_id": "ddab8ee5-2bb8-4226-b145-6732d31dc344",
                "run_id": "e3865391-bc89-44e6-86f7-2d4405627daf",
                "integration_id": 9,
            },
        )

    def test_queue_captures_failure_before_enqueue(self) -> None:
        error = ConnectionError("database unavailable")
        run_id = "e3865391-bc89-44e6-86f7-2d4405627daf"

        with (
            patch.object(SignalScoutRun.all_teams, "select_related", side_effect=error),
            patch("products.signals.backend.scout_harness.slack_delivery_queue.capture_exception") as capture,
        ):
            queue_configured_scout_slack_delivery(
                run_id=run_id,
                output_type="report",
                output_id="ddab8ee5-2bb8-4226-b145-6732d31dc344",
            )

        capture.assert_called_once_with(
            error,
            {
                "run_id": run_id,
                "output_type": "report",
                "output_id": "ddab8ee5-2bb8-4226-b145-6732d31dc344",
            },
        )
