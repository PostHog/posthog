import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.conf import settings

from celery.exceptions import Retry
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration

from products.signals.backend.models import SignalScoutEmission, SignalScoutRun
from products.signals.backend.scout_harness.slack_delivery import (
    ScoutSlackPermanentDeliveryError,
    post_scout_emission_to_slack,
)
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

    def test_posts_safe_slack_mrkdwn_with_stable_delivery_id(self) -> None:
        emission = self._make_emission(
            "**Checkout** failures [trace](https://example.com/trace) <!channel> [ping](!here)"
        )
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
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
                    args=(self.team.id, str(emission.id), 1, "CSCOUTS|#scout-findings"),
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
            deliver_scout_slack_output.run(self.team.id, str(emission.id), 9, "CMISSING|#missing")

        capture.assert_called_once_with(
            error,
            {
                "team_id": self.team.id,
                "emission_id": str(emission.id),
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
                args=(self.team.id, str(emission.id), 9, "CSCOUTS|#scout-findings"),
                retries=5,
                throw=True,
            )

        assert result.successful()
        capture.assert_called_once_with(
            error,
            {
                "team_id": self.team.id,
                "emission_id": str(emission.id),
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
                emission_id="ddab8ee5-2bb8-4226-b145-6732d31dc344",
                integration_id=9,
                channel="CSCOUTS|#scout-findings",
            )

        capture.assert_called_once_with(
            error,
            {
                "team_id": self.team.id,
                "emission_id": "ddab8ee5-2bb8-4226-b145-6732d31dc344",
                "integration_id": 9,
            },
        )
