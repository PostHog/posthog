from datetime import timedelta
from io import StringIO
from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import delete_source_destination_rows, list_alert_destinations
from products.alerts_platform.backend.facade.contracts import AlertEventKind
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.templates.fixtures import template_slack
from products.cdp.backend.templates.hog_function_template import sync_template_to_db
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_cutover import NATIVE_CREATE_FLAG

SLACK = {"type": "slack", "slack_workspace_id": 42, "slack_channel_id": "C123", "slack_channel_name": "alerts"}
WEBHOOK = {"type": "webhook", "webhook_url": "https://example.com/hook"}


class TestConvertLogsAlertDestinations(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/logs/alerts/"
        # Native creates off, so a new alert gets a logs row and HogFunction destinations to convert.
        patcher = patch(
            "posthoganalytics.feature_enabled", side_effect=lambda flag, *_, **__: flag != NATIVE_CREATE_FLAG
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        for reload in (
            "products.alerts.backend.logic.destinations.reload_hog_functions_on_workers",
            "products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers",
        ):
            reload_patcher = patch(reload)
            reload_patcher.start()
            self.addCleanup(reload_patcher.stop)
        sync_template_to_db(template_slack)

    def _alert_with_slack(self, *, platform_owned: bool = True, name: str = "Errors") -> tuple[str, list[str]]:
        alert = self.client.post(
            self.base_url,
            {"name": name, "threshold_count": 10, "filters": {"severityLevels": ["error"]}},
            format="json",
        ).json()
        created = self.client.post(f"{self.base_url}{alert['id']}/destinations/", SLACK, format="json")
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        owner = PlatformAlertOwner.PLATFORM if platform_owned else PlatformAlertOwner.SOURCE
        LogsAlertConfiguration.objects.filter(id=alert["id"]).update(owner=owner)
        return alert["id"], created.json()["hog_function_ids"]

    def _rows(self, alert_id: str) -> list[Any]:
        with team_scope(self.team.id):
            configuration_id = platform_testing.copy_of(UUID(alert_id)).id
        return list(list_alert_destinations(team_id=self.team.id, configuration_id=configuration_id))

    def _run(self, *args: str) -> str:
        out = StringIO()
        call_command("convert_logs_alert_destinations", "--team-id", str(self.team.id), *args, stdout=out)
        return out.getvalue()

    def _live(self, hog_function_ids: list[str]) -> int:
        return HogFunction.objects.filter(id__in=hog_function_ids, deleted=False).count()

    @parameterized.expand(
        [
            ("added_before_rows", False, True),
            ("already_copied_by_a_row", True, True),
            ("switched_off_after_the_row_copied_it", True, False),
        ]
    )
    def test_a_stock_slack_group_becomes_one_row_and_its_hog_functions_retire(
        self, _name: str, has_row: bool, enabled: bool
    ) -> None:
        alert_id, hog_function_ids = self._alert_with_slack()
        for hog_function_id in [] if enabled else hog_function_ids:
            switched_off = self.client.patch(
                f"/api/projects/{self.team.pk}/hog_functions/{hog_function_id}/", {"enabled": False}, format="json"
            )
            assert switched_off.status_code == status.HTTP_200_OK, switched_off.json()
        if not has_row:
            (row,) = self._rows(alert_id)
            delete_source_destination_rows(
                team_id=self.team.id, public_id=UUID(alert_id), destination_ids=[row.id], hog_function_ids=()
            )

        rows_before = [r.id for r in self._rows(alert_id)]

        dry_run = self._run()

        assert f"{{'{'kept_row' if has_row else 'converted'}': 1}}" in dry_run
        assert self._live(hog_function_ids) == 4
        assert len(rows_before) == (1 if has_row else 0)

        self._run("--apply")

        (row,) = self._rows(alert_id)
        if has_row:
            assert [row.id] == rows_before
        assert sorted(map(str, row.legacy_hog_function_ids)) == sorted(hog_function_ids)
        assert set(row.event_kinds) == {
            AlertEventKind.FIRING,
            AlertEventKind.RESOLVED,
            AlertEventKind.BROKEN,
            AlertEventKind.ERRORED,
        }
        assert (row.enabled, row.data["slack_channel_id"], row.data.get("slack_channel_name")) == (
            enabled,
            "C123",
            "alerts" if has_row else None,
        )
        assert self._live(hog_function_ids) == 0
        assert not HogFunction.objects.filter(id__in=hog_function_ids, enabled=True).exists()

        again = self._run("--apply")

        assert "no HogFunction destinations" in again
        assert [r.id for r in self._rows(alert_id)] == [row.id]

    def test_a_webhook_on_an_alert_held_on_hog_functions_keeps_the_legacy_body_it_was_sent(self) -> None:
        HogFunctionTemplate.objects.get_or_create(
            template_id="template-webhook",
            defaults={
                "sha": "1.0.0",
                "name": "Webhook",
                "code": "return event",
                "code_language": "hog",
                "inputs_schema": [{"key": "url", "type": "string"}, {"key": "body", "type": "json"}],
                "type": "destination",
                "status": "stable",
            },
        )
        held_alert, slack_ids = self._alert_with_slack(name="Held by its Slack")
        native_alert, _ = self._alert_with_slack(name="Native")
        for alert_id in (held_alert, native_alert):
            created = self.client.post(f"{self.base_url}{alert_id}/destinations/", WEBHOOK, format="json")
            assert created.status_code == status.HTTP_201_CREATED, created.json()
        edited = self.client.patch(
            f"/api/projects/{self.team.pk}/hog_functions/{slack_ids[0]}/",
            {"hog": "fetch('https://relay.example.com')"},
            format="json",
        )
        assert edited.status_code == status.HTTP_200_OK, edited.json()

        self._run("--apply")

        assert {row.data["type"]: row.keeps_legacy_webhook_body for row in self._rows(held_alert)} == {
            "slack": False,
            "webhook": True,
        }
        assert {row.data["type"]: row.keeps_legacy_webhook_body for row in self._rows(native_alert)} == {
            "slack": False,
            "webhook": False,
        }

    def test_customized_groups_firing_or_recently_emitting_alerts_and_logs_owned_alerts_keep_their_hog_functions(
        self,
    ) -> None:
        customized_alert, customized_ids = self._alert_with_slack()
        edited = self.client.patch(
            f"/api/projects/{self.team.pk}/hog_functions/{customized_ids[0]}/",
            {"hog": "fetch('https://relay.example.com')"},
            format="json",
        )
        assert edited.status_code == status.HTTP_200_OK, edited.json()
        logs_owned_alert, logs_owned_ids = self._alert_with_slack(platform_owned=False, name="Kept on logs")
        firing_alert, firing_ids = self._alert_with_slack(name="Firing")
        emitting_alert, emitting_ids = self._alert_with_slack(name="Emitted lately")
        quiet_alert, quiet_ids = self._alert_with_slack(name="Emitted long ago")
        with team_scope(self.team.id):
            platform_testing.start_firing(
                platform_testing.copy_of(UUID(firing_alert)).id, team_id=self.team.id, at=timezone.now()
            )
            for alert_id, emitted_at in (
                (emitting_alert, timezone.now() - timedelta(minutes=1)),
                (quiet_alert, timezone.now() - timedelta(hours=1)),
            ):
                platform_testing.record_legacy_emission(
                    platform_testing.copy_of(UUID(alert_id)).id, team_id=self.team.id, at=emitted_at
                )

        out = self._run("--apply")

        assert "outcome=customized" in out
        assert f"alert={firing_alert}" in out and "outcome=firing" in out
        assert self._live(firing_ids) == 4
        assert f"alert={emitting_alert}" in out and "outcome=recently_emitted" in out
        assert self._live(emitting_ids) == 4
        assert self._live(quiet_ids) == 0
        assert self._live(customized_ids) == 4
        assert self._live(logs_owned_ids) == 4
        assert len(self._rows(customized_alert)) == 1
        assert len(self._rows(logs_owned_alert)) == 1
