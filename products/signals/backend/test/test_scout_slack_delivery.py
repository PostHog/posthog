import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.conf import settings

from celery.exceptions import Retry
from slack_sdk.errors import SlackApiError

from posthog.models import Team
from posthog.models.integration import Integration

from products.signals.backend.models import SignalReport, SignalScoutEmission, SignalScoutRun
from products.signals.backend.scout_harness.slack_delivery import (
    ScoutSlackPermanentDeliveryError,
    post_scout_emission_to_slack,
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

    def test_posts_safe_slack_mrkdwn_through_project_integration_with_stable_delivery_id(self) -> None:
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

        with patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration:
            slack_integration.return_value.client = fake_client
            post_scout_emission_to_slack(
                emission,
                integration_id=integration.id,
                channel="CSCOUTS|#scout-findings",
            )

        call = fake_client.chat_postMessage.call_args.kwargs
        assert call["channel"] == "CSCOUTS"
        assert call["client_msg_id"] == str(emission.id)
        section = call["blocks"][1]["text"]["text"]
        assert "*Checkout*" in section
        assert "<https://example.com/trace|trace>" in section
        assert "<!channel>" not in section
        assert "<!here>" not in section
        assert "&lt;!channel&gt;" in section
        assert call["blocks"][-1]["elements"][0]["url"] == (
            f"{settings.SITE_URL}/project/{self.team.id}/inbox/scouts/signals-scout-error-tracking/checkout%2F500s"
        )

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

        call = fake_client.chat_postMessage.call_args.kwargs
        assert call["channel"] == "CSCOUTS"
        assert call["client_msg_id"] == delivery_id
        section = call["blocks"][2]["text"]["text"]
        assert "*Checkout*" in section
        assert "<!channel>" not in section
        assert "&lt;!channel&gt;" in section
        assert "<https://example.com/trace|trace>" in section
        assert call["blocks"][-1]["elements"][0]["url"] == (
            f"{settings.SITE_URL}/project/{self.team.id}/inbox/reports/{report.id}"
        )

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
