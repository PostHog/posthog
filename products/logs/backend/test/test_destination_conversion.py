from io import StringIO
from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.management import call_command

from parameterized import parameterized
from rest_framework import status

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import delete_source_destination_rows, list_alert_destinations
from products.alerts_platform.backend.facade.contracts import AlertEventKind
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.templates.fixtures import template_slack
from products.cdp.backend.templates.hog_function_template import sync_template_to_db
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_cutover import NATIVE_CREATE_FLAG

SLACK = {"type": "slack", "slack_workspace_id": 42, "slack_channel_id": "C123", "slack_channel_name": "alerts"}


@patch("products.alerts.backend.logic.destinations.reload_hog_functions_on_workers")
@patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers")
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

    @parameterized.expand([("added_before_rows", False), ("already_copied_by_a_row", True)])
    def test_a_stock_slack_group_becomes_one_row_and_its_hog_functions_retire(
        self, _name: str, has_row: bool, *_mocks: Any
    ) -> None:
        alert_id, hog_function_ids = self._alert_with_slack()
        if not has_row:
            (row,) = self._rows(alert_id)
            delete_source_destination_rows(
                team_id=self.team.id, public_id=UUID(alert_id), destination_ids=[row.id], hog_function_ids=()
            )

        dry_run = self._run()

        assert "dry_run" in dry_run
        assert self._live(hog_function_ids) == 4
        assert len(self._rows(alert_id)) == (1 if has_row else 0)

        self._run("--apply")

        (row,) = self._rows(alert_id)
        assert sorted(map(str, row.legacy_hog_function_ids)) == sorted(hog_function_ids)
        assert set(row.event_kinds) == {
            AlertEventKind.FIRING,
            AlertEventKind.RESOLVED,
            AlertEventKind.BROKEN,
            AlertEventKind.ERRORED,
        }
        assert (row.enabled, row.data["slack_channel_id"]) == (True, "C123")
        assert self._live(hog_function_ids) == 0
        assert not HogFunction.objects.filter(id__in=hog_function_ids, enabled=True).exists()

        again = self._run("--apply")

        assert "no HogFunction destinations" in again
        assert [r.id for r in self._rows(alert_id)] == [row.id]

    def test_customized_groups_and_alerts_the_logs_stack_owns_keep_their_hog_functions(self, *_mocks: Any) -> None:
        customized_alert, customized_ids = self._alert_with_slack()
        edited = self.client.patch(
            f"/api/projects/{self.team.pk}/hog_functions/{customized_ids[0]}/",
            {"hog": "fetch('https://relay.example.com')"},
            format="json",
        )
        assert edited.status_code == status.HTTP_200_OK, edited.json()
        logs_owned_alert, logs_owned_ids = self._alert_with_slack(platform_owned=False, name="Kept on logs")

        out = self._run("--apply")

        assert "outcome=customized" in out
        assert self._live(customized_ids) == 4
        assert self._live(logs_owned_ids) == 4
        assert len(self._rows(customized_alert)) == 1
        assert len(self._rows(logs_owned_alert)) == 1
