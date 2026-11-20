from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from parameterized import parameterized
from redis.exceptions import RedisError

from posthog.models.user import User

from products.actions.backend.facade.testing import create_action
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow, defer_hog_flow_reloads

REPORT_CREATED = "products.workflows.backend.tasks.hog_flows.report_workflow_created.delay"
LOGGER = "products.workflows.backend.models.hog_flow.hog_flow.logger"


class TestHogFlow(TestCase):
    def setUp(self):
        super().setUp()
        org, team, user = User.objects.bootstrap("Test org", "ben@posthog.com", None)
        self.team = team
        self.user = user
        self.org = org

    @patch("posthog.ph_client.get_client")
    @patch(REPORT_CREATED)
    def test_creation_enqueues_one_report_after_commit(self, report_created: MagicMock, get_client: MagicMock) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            flow = HogFlow.objects.create(
                name="Welcome",
                team=self.team,
                created_by=self.user,
                origin_product="broadcasts",
                actions=[{"type": "trigger"}],
            )
            flow.name = "Renamed"
            flow.origin_product = "loops"
            flow.actions = []
            flow.save()
            report_created.assert_not_called()

        report_created.assert_called_once_with(
            team_id=self.team.id,
            hog_flow_id=str(flow.id),
            created_at=flow.created_at.isoformat(),
            origin_product="broadcasts",
            actions_count=1,
        )
        get_client.assert_not_called()

    @patch(REPORT_CREATED, side_effect=RuntimeError("Broker unavailable"))
    def test_failed_enqueue_is_logged_and_does_not_fail_creation(self, report_created: MagicMock) -> None:
        with patch(LOGGER) as logger, self.captureOnCommitCallbacks(execute=True):
            flow = HogFlow.objects.create(name="Welcome", team=self.team)

        report_created.assert_called_once()
        logger.exception.assert_called_once_with(
            "Failed to report workflow creation", team_id=self.team.id, workflow_id=str(flow.id)
        )
        assert HogFlow.objects.filter(id=flow.id, team=self.team).exists()

    @patch(REPORT_CREATED)
    def test_rolled_back_creation_does_not_report(self, report_created: MagicMock) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    HogFlow.objects.create(name="Rolled back", team=self.team)
                    raise ValueError("Abort")
            except ValueError:
                pass
        report_created.assert_not_called()

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_hog_flow_saved_receiver(self, mock_reload):
        with self.captureOnCommitCallbacks(execute=True):
            hog_flow = HogFlow.objects.create(name="Test Flow", team=self.team)
        mock_reload.assert_called_once_with(team_id=self.team.id, hog_flow_ids=[str(hog_flow.id)])

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_deferred_saves_reload_once_after_the_commit(self, mock_reload):
        with self.captureOnCommitCallbacks(execute=True):
            with defer_hog_flow_reloads():
                first = HogFlow.objects.create(name="First", team=self.team)
                second = HogFlow.objects.create(name="Second", team=self.team)
            mock_reload.assert_not_called()

        mock_reload.assert_called_once_with(team_id=self.team.id, hog_flow_ids=sorted([str(first.id), str(second.id)]))

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_draft_only_save_skips_worker_reload(self, mock_reload):
        hog_flow = HogFlow.objects.create(name="Test Flow", team=self.team)
        mock_reload.reset_mock()

        hog_flow.draft = {"name": "Draft name"}
        with self.captureOnCommitCallbacks(execute=True):
            hog_flow.save(update_fields=["draft", "draft_updated_at"])
        mock_reload.assert_not_called()

        with self.captureOnCommitCallbacks(execute=True):
            hog_flow.save(update_fields=["draft", "name"])
        mock_reload.assert_called_once_with(team_id=self.team.id, hog_flow_ids=[str(hog_flow.id)])

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_email_pause_save_reloads_the_workers(self, mock_reload):
        # The worker enforces the pause off its cached config, so a pause that does not publish a
        # reload lets in-flight runs and queued batch sends keep sending for the cache's lifetime.
        hog_flow = HogFlow.objects.create(name="Test Flow", team=self.team)
        mock_reload.reset_mock()

        hog_flow.email_sending_paused_at = timezone.now()
        hog_flow.email_sending_paused_reason = "Spam complaints reached 2%."
        with self.captureOnCommitCallbacks(execute=True):
            hog_flow.save(update_fields=["email_sending_paused_at", "email_sending_paused_reason"])
            mock_reload.assert_not_called()

        mock_reload.assert_called_once_with(team_id=self.team.id, hog_flow_ids=[str(hog_flow.id)])

    @parameterized.expand([("save",), ("delete",)])
    @patch("products.workflows.backend.models.hog_flow.hog_flow.capture_exception")
    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_a_failed_reload_publish_is_retried_reported_and_runs_the_callbacks_after_it(
        self, change, mock_reload, mock_capture_exception
    ):
        hog_flow = HogFlow.objects.create(name="Test Flow", team=self.team)
        hog_flow_id = str(hog_flow.id)
        mock_reload.side_effect = RedisError("Redis is down")
        callback_after_the_reload = MagicMock()

        with self.captureOnCommitCallbacks(execute=True):
            if change == "save":
                hog_flow.name = "Renamed"
                hog_flow.save(update_fields=["name"])
            else:
                hog_flow.delete()
            transaction.on_commit(callback_after_the_reload)

        assert mock_reload.call_count == 2
        mock_reload.assert_called_with(team_id=self.team.id, hog_flow_ids=[hog_flow_id])
        mock_capture_exception.assert_called_once()
        callback_after_the_reload.assert_called_once()

    @patch("products.workflows.backend.tasks.hog_flows.refresh_affected_hog_flows.delay")
    def test_action_saved_receiver(self, mock_refresh):
        action = create_action(team=self.team, name="Test Action")
        mock_refresh.assert_called_once_with(action_id=action.id)

    @patch("products.workflows.backend.tasks.hog_flows.refresh_affected_hog_flows.delay")
    def test_team_saved_receiver(self, mock_refresh):
        with self.captureOnCommitCallbacks(execute=True):
            self.team.save()
            mock_refresh.assert_not_called()
        mock_refresh.assert_called_once_with(team_id=self.team.id)

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_backfill_conversion_filters_to_events_command(self, _mock_reload):
        # Event-based conversion stored in the wrong slot (the legacy shape we're fixing).
        event_obj = {
            "events": [{"id": "purchase", "name": "purchase", "type": "events", "order": 0}],
            "source": "events",
        }
        bad = HogFlow.objects.create(
            name="bad",
            team=self.team,
            conversion={"window_minutes": 60, "filters": event_obj, "bytecode": ["_H", 1, 29]},
        )
        # Correctly-shaped property conversion — must be left untouched.
        good_filters = [{"key": "plan", "type": "person", "value": ["growth"], "operator": "exact"}]
        good = HogFlow.objects.create(
            name="good",
            team=self.team,
            conversion={"window_minutes": 30, "filters": good_filters, "bytecode": ["_H", 1, 1]},
        )

        # Dry-run (the default) must not change anything.
        call_command("backfill_conversion_filters_to_events")
        bad.refresh_from_db()
        assert bad.conversion is not None and isinstance(bad.conversion["filters"], dict)

        # Live-run relocates the bad shape and leaves the good one untouched.
        call_command("backfill_conversion_filters_to_events", "--live-run")

        bad.refresh_from_db()
        bad_conversion = bad.conversion
        assert bad_conversion is not None
        assert bad_conversion["filters"] == []
        assert bad_conversion["bytecode"] == []
        assert bad_conversion["events"] == [{"filters": event_obj}]

        good.refresh_from_db()
        good_conversion = good.conversion
        assert good_conversion is not None
        assert good_conversion["filters"] == good_filters
        assert not good_conversion.get("events")

        # Idempotent: a second live-run must not double-move or change anything.
        call_command("backfill_conversion_filters_to_events", "--live-run")
        bad.refresh_from_db()
        bad_conversion = bad.conversion
        assert bad_conversion is not None
        assert bad_conversion["filters"] == []
        assert bad_conversion["events"] == [{"filters": event_obj}]
