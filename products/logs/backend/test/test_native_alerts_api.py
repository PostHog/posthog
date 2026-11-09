from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.scoping import team_scope
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import create_configuration
from products.alerts_platform.backend.facade.contracts import Grouping, PlatformAlertConfigurationEdit, SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_cutover import NATIVE_CREATE_FLAG
from products.logs.backend.platform_source_config import logs_source_config

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
# The fields the Terraform provider's `posthog_logs_alert` resource reads back after each call.
_TERRAFORM_FIELDS = (
    "name",
    "enabled",
    "filters",
    "threshold_count",
    "threshold_operator",
    "window_minutes",
    "evaluation_periods",
    "datapoints_to_alarm",
    "cooldown_minutes",
    "schedule_restriction",
    "snooze_until",
    "state",
)
_FILTERS = {"severityLevels": ["error"]}
# The body the provider sends on update: every field, with a nil filter group as null.
_TERRAFORM_UPDATE = {
    "name": "Renamed",
    "enabled": True,
    "filters": {"severityLevels": ["error", "warn"], "serviceNames": ["api"], "filterGroup": None},
    "threshold_count": 20,
    "threshold_operator": "above",
    "window_minutes": 10,
    "evaluation_periods": 3,
    "datapoints_to_alarm": 2,
    "cooldown_minutes": 15,
    "schedule_restriction": None,
    "snooze_until": (_NOW + timedelta(hours=2)).isoformat(),
}


@time_machine.travel(_NOW, tick=False)
@patch("products.alerts.backend.logic.destinations.reload_hog_functions_on_workers")
@patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers")
class TestLogsAlertWithNoLogsRow(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/logs/alerts/"
        self.native_create = False
        patcher = patch(
            "posthoganalytics.feature_enabled",
            side_effect=lambda flag, *_, **__: flag != NATIVE_CREATE_FLAG or self.native_create,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
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

    def _create_with_logs_row(self) -> str:
        response = self.client.post(
            self.base_url, {"name": "High error rate", "threshold_count": 10, "filters": _FILTERS}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()["id"]

    def _create_without_logs_row(self) -> str:
        with team_scope(self.team.id):
            created = platform_testing.create_configuration(
                team_id=self.team.id,
                name="High error rate",
                enabled=True,
                source_kind=SourceKind.LOGS.value,
                source_config=logs_source_config(
                    _FILTERS, {"threshold_count": 10, "threshold_operator": "above", "window_minutes": 5}
                ),
                check_interval_minutes=5,
                next_check_at=_NOW,
                owner=PlatformAlertOwner.PLATFORM,
                created_by=self.user,
                first_enabled_at=_NOW,
            )
        return str(created.id)

    def _read(self, alert_id: str) -> dict[str, Any]:
        response = self.client.get(f"{self.base_url}{alert_id}/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        return {
            **{field: body[field] for field in _TERRAFORM_FIELDS},
            "destinations": [destination["type"] for destination in body["destinations"]],
        }

    def _terraform_lifecycle(self, alert_id: str) -> list[Any]:
        """Runs the provider's calls on one alert and returns what each read gave back."""
        seen: list[Any] = [self._read(alert_id)]

        updated = self.client.patch(f"{self.base_url}{alert_id}/", _TERRAFORM_UPDATE, format="json")
        assert updated.status_code == status.HTTP_200_OK, updated.json()
        seen.append({field: updated.json()[field] for field in _TERRAFORM_FIELDS})
        seen.append(self._read(alert_id))

        destination = self.client.post(
            f"{self.base_url}{alert_id}/destinations/",
            {"type": "webhook", "webhook_url": "https://example.com/hook"},
            format="json",
        )
        assert destination.status_code == status.HTTP_201_CREATED, destination.json()
        hog_function_ids = destination.json()["hog_function_ids"]
        seen.append(self._read(alert_id))
        seen.append(
            sorted(
                {
                    (f.filters or {})["properties"][0]["value"] == alert_id
                    for f in HogFunction.objects.filter(id__in=hog_function_ids)
                }
            )
        )

        listed = self.client.get(self.base_url)
        assert listed.status_code == status.HTTP_200_OK, listed.json()
        seen.append([alert["id"] for alert in listed.json()["results"]].count(alert_id))

        removed = self.client.post(
            f"{self.base_url}{alert_id}/destinations/delete/", {"hog_function_ids": hog_function_ids}, format="json"
        )
        assert removed.status_code == status.HTTP_204_NO_CONTENT
        seen.append(self._read(alert_id)["destinations"])

        # Only the status: a logs row also records its own edits as events, which the platform does not.
        seen.append((self.client.get(f"{self.base_url}{alert_id}/events/").status_code,))
        reset = self.client.post(f"{self.base_url}{alert_id}/reset/")
        seen.append((reset.status_code, reset.json()))

        assert self.client.delete(f"{self.base_url}{alert_id}/").status_code == status.HTTP_204_NO_CONTENT
        seen.append(self.client.get(f"{self.base_url}{alert_id}/").status_code)
        seen.append(HogFunction.objects.filter(id__in=hog_function_ids, deleted=False).count())
        return seen

    def test_an_object_level_deny_treats_both_kinds_of_alert_alike(self, *_: object) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        with_row = self._create_with_logs_row()
        without_row = self._create_without_logs_row()
        member = self._create_user("member@example.com", level=OrganizationMembership.Level.MEMBER)
        membership = member.organization_memberships.get(organization=self.organization)
        for alert_id in (with_row, without_row):
            AccessControl.objects.create(
                team=self.team,
                resource="logs",
                resource_id=alert_id,
                access_level="none",
                organization_member=membership,
            )
        self.client.force_login(member)

        listed = {alert["id"] for alert in self.client.get(self.base_url).json()["results"]}
        seen = {
            alert_id: (alert_id in listed, self.client.get(f"{self.base_url}{alert_id}/").status_code)
            for alert_id in (with_row, without_row)
        }

        assert seen[without_row] == seen[with_row]

    def test_a_list_page_interleaves_both_kinds_of_alert_newest_first(self, *_: object) -> None:
        created = []
        for minute, kind in enumerate(["row", "native", "row", "native"]):
            with time_machine.travel(_NOW + timedelta(minutes=minute), tick=False):
                alert_id = self._create_with_logs_row() if kind == "row" else self._create_without_logs_row()
            created.append(alert_id)

        pages = [
            [alert["id"] for alert in self.client.get(self.base_url, {"limit": 2, "offset": offset}).json()["results"]]
            for offset in (0, 2)
        ]

        assert pages == [created[3:1:-1], created[1::-1]]

    def test_the_creator_filter_matches_both_kinds_of_alert_by_their_creator(self, *_: object) -> None:
        other = User.objects.create_and_join(self.organization, "other@example.com", None)
        with_row, without_row = self._create_with_logs_row(), self._create_without_logs_row()

        def listed(created_by: User) -> list[tuple[str, int]]:
            response = self.client.get(self.base_url, {"created_by": str(created_by.uuid)})
            return sorted((alert["id"], alert["created_by"]["id"]) for alert in response.json()["results"])

        assert (listed(self.user), listed(other)) == (
            sorted([(with_row, self.user.id), (without_row, self.user.id)]),
            [],
        )

    def test_terraform_sees_no_difference_between_an_alert_with_a_logs_row_and_one_without(self, *_: object) -> None:
        with_row = self._terraform_lifecycle(self._create_with_logs_row())
        without_row = self._terraform_lifecycle(self._create_without_logs_row())

        assert without_row == with_row
        assert without_row[2] == {
            **{field: value for field, value in _TERRAFORM_UPDATE.items() if field != "snooze_until"},
            "filters": _TERRAFORM_UPDATE["filters"],
            "snooze_until": "2026-11-06T14:00:00Z",
            "state": "snoozed",
            "destinations": [],
        }
        assert without_row[3:7] == [{**without_row[2], "destinations": ["webhook"]}, [True], 1, []]
        assert without_row[7][0] == status.HTTP_200_OK
        assert without_row[8][0] == status.HTTP_400_BAD_REQUEST
        assert without_row[9:] == [status.HTTP_404_NOT_FOUND, 0]
        assert not LogsAlertConfiguration.objects.filter(team=self.team).exists()

    def _create(self, route: str) -> str:
        if route == "logs_api":
            response = self.client.post(
                self.base_url, {"name": "High error rate", "threshold_count": 10, "filters": _FILTERS}, format="json"
            )
            assert response.status_code == status.HTTP_201_CREATED, response.json()
            return response.json()["id"]
        with team_scope(self.team.id):
            view = create_configuration(
                team_id=self.team.id,
                source_kind=SourceKind.LOGS,
                edit=PlatformAlertConfigurationEdit(
                    name="High error rate",
                    enabled=True,
                    source_config=logs_source_config(
                        _FILTERS, {"threshold_count": 10, "threshold_operator": "above", "window_minutes": 5}
                    ),
                    grouping=Grouping(),
                    schedule_restriction=None,
                    evaluation_periods=1,
                    datapoints_to_alarm=1,
                    cooldown_minutes=0,
                ),
                created_by_id=self.user.id,
            )
        return str(view.destination_alert_id)

    @parameterized.expand(
        [
            ("logs_api_flag_off", "logs_api", False),
            ("logs_api_flag_on", "logs_api", True),
            ("platform_api_flag_off", "platform_api", False),
            ("platform_api_flag_on", "platform_api", True),
        ]
    )
    def test_a_create_writes_a_logs_row_only_while_the_native_create_flag_is_off(
        self, _name: str, route: str, native_create: bool, *_: object
    ) -> None:
        self.native_create = native_create

        alert_id = self._create(route)

        read = self.client.get(f"{self.base_url}{alert_id}/")
        assert read.status_code == status.HTTP_200_OK, read.json()
        assert (
            LogsAlertConfiguration.objects.filter(team=self.team).count(),
            read.json()["name"],
            read.json()["threshold_count"],
            read.json()["created_by"]["id"],
            read.json()["first_enabled_at"] is not None,
        ) == (0 if native_create else 1, "High error rate", 10, self.user.id, True)

    def test_a_native_create_keeps_the_snooze_terraform_sent(self, *_: object) -> None:
        self.native_create = True
        until = (_NOW + timedelta(hours=1)).isoformat()

        created = self.client.post(
            self.base_url,
            {"name": "High error rate", "threshold_count": 10, "filters": _FILTERS, "snooze_until": until},
            format="json",
        )

        assert created.status_code == status.HTTP_201_CREATED, created.json()
        read = self._read(created.json()["id"])
        assert (read["snooze_until"], read["state"]) == ("2026-11-06T13:00:00Z", "snoozed")

    def test_a_team_whose_alerts_stay_with_logs_keeps_the_logs_row_with_the_flag_on(self, *_: object) -> None:
        LogsAlertConfiguration.objects.create(team=self.team, name="Kept on logs", enabled=False)
        self.native_create = True

        self._create("logs_api")

        assert LogsAlertConfiguration.objects.filter(team=self.team).count() == 2

    def test_an_alert_with_no_logs_row_takes_a_slot_under_the_cap(self, *_: object) -> None:
        self.native_create = True

        with patch("products.logs.backend.alert_creation.MAX_ALERTS_PER_TEAM", 1):
            self._create("logs_api")
            refused = self.client.post(
                self.base_url, {"name": "Second", "threshold_count": 10, "filters": _FILTERS}, format="json"
            )

        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.json()
        assert [alert["name"] for alert in self.client.get(self.base_url).json()["results"]] == ["High error rate"]
