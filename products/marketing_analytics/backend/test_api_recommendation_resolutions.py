import json
from datetime import UTC, datetime

import pytest
from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.marketing_analytics.backend.models.recommendation_resolution import RecommendationResolution
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.testing import WarehouseAccessControlTestMixin

IDENTITY = {
    "rule": "spend_without_conversions",
    "source_type": "google_ads",
    "customer_id": "1234567890",
    "campaign_id": "",
    "subject": "example shoes",
}


class TestRecommendationResolutions(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base = f"/api/projects/{self.team.pk}/marketing_analytics_recommendation_resolutions/"

    def _resolve(self, identity: dict[str, str], resolution: str = "dismissed"):
        return self.client.post(self.base, {"identity": identity, "resolution": resolution}, format="json")

    def test_resolving_again_replaces_the_resolution(self) -> None:
        first = self._resolve(IDENTITY)
        second = self._resolve(IDENTITY, "applied")

        assert first.status_code == 201, first.json()
        assert second.status_code == 200, second.json()
        assert second.json()["id"] == first.json()["id"]
        assert second.json()["created_at"] == first.json()["created_at"]
        assert second.json()["resolved_at"] > first.json()["resolved_at"]
        assert (second.json()["resolution"], second.json()["resolved_by"]["id"]) == ("applied", self.user.id)
        logs = list(ActivityLog.objects.filter(scope="RecommendationResolution").order_by("created_at"))
        assert [
            (
                log.activity,
                log.user_id,
                (log.detail or {})["name"],
                [change["field"] for change in (log.detail or {}).get("changes") or []],
            )
            for log in logs
        ] == [
            ("created", self.user.id, "Spend without conversions", []),
            ("updated", self.user.id, "Spend without conversions", ["resolution"]),
        ]
        assert not any(value in json.dumps(log.detail) for log in logs for value in ("example shoes", "1234567890"))

        other_account = self._resolve({**IDENTITY, "customer_id": "9876543210"})
        assert other_account.status_code == 201
        assert other_account.json()["id"] != first.json()["id"]
        edge_spaces = self._resolve({**IDENTITY, "subject": " example shoes "})
        assert edge_spaces.json()["identity"]["subject"] == " example shoes "
        long_multibyte = self._resolve({**IDENTITY, "subject": "靴" * 1500})
        assert long_multibyte.status_code == 201, long_multibyte.json()
        assert self._resolve({**IDENTITY, "subject": "靴" * 1500}).status_code == 200

    @parameterized.expand(
        [
            ("unknown_rule", {"rule": "pause_everything"}),
            ("account_agnostic_rule_with_an_account", {"rule": "keyword_gap"}),
            ("search_term_rule_with_a_campaign", {"campaign_id": "c1"}),
            ("search_term_rule_without_a_term", {"subject": ""}),
            ("campaign_rule_without_a_campaign", {"rule": "policy_limited", "subject": ""}),
            ("campaign_rule_with_a_subject", {"rule": "policy_limited", "campaign_id": "c1"}),
        ]
    )
    def test_rejects_an_identity_the_rule_cannot_produce(self, _name: str, overrides: dict[str, str]) -> None:
        response = self._resolve({**IDENTITY, **overrides})

        assert response.status_code == 400, response.json()
        assert not RecommendationResolution.objects.for_team(self.team.pk).exists()

    def test_another_team_cannot_delete_a_resolution(self) -> None:
        resolution_id = self._resolve(IDENTITY).json()["id"]
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        other_base = f"/api/projects/{other_team.pk}/marketing_analytics_recommendation_resolutions/"

        assert self.client.delete(f"{other_base}{resolution_id}/").status_code == 404
        assert RecommendationResolution.objects.for_team(self.team.pk).filter(id=resolution_id).exists()

        assert self.client.delete(f"{self.base}{resolution_id}/").status_code == 204
        assert not RecommendationResolution.objects.for_team(self.team.pk).exists()
        deleted = ActivityLog.objects.get(scope="RecommendationResolution", activity="deleted")
        assert ((deleted.detail or {})["name"], (deleted.detail or {})["changes"]) == ("Spend without conversions", [])


@pytest.mark.ee
class TestRecommendationResolutionsWarehouseAccess(WarehouseAccessControlTestMixin):
    resource = "external_data_source"

    def _connect_google_ads(self, team: Team, *, paused: bool) -> ExternalDataSource:
        source = ExternalDataSource.objects.create(
            team=team,
            source_id="google-ads",
            connection_id="google-ads",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="GoogleAds",
        )
        for schema in ("campaign", "campaign_stats"):
            table = DataWarehouseTable.objects.create(
                team=team,
                name=f"googleads_{schema}",
                format=DataWarehouseTable.TableFormat.CSVWithNames,
                url_pattern="",
                external_data_source=source,
                columns={},
            )
            ExternalDataSchema.objects.create(
                team=team,
                source=source,
                name=schema,
                table=table,
                should_sync=not paused,
                last_synced_at=None if paused else datetime.now(UTC),
            )
        return source

    @parameterized.expand(
        [
            ("allowed_member", "editor_user", "source", False, (200, 204)),
            ("denied_member", "no_access_user", "source", False, (403, 403)),
            ("denied_member_on_a_paused_source", "no_access_user", "source", True, (403, 403)),
            ("denied_member_from_another_environment", "no_access_user", "request_from_environment", False, (403, 403)),
            ("member_denied_the_environment_of_the_source", "editor_user", "environment", False, (403, 403)),
        ]
    )
    def test_resolving_needs_access_to_every_recommendation_source(
        self, _name: str, user_attr: str, denial: str, paused: bool, statuses: tuple[int, int]
    ) -> None:
        environment = Team.objects.create(organization=self.organization, parent_team=self.team)
        url_team = environment if denial == "request_from_environment" else self.team
        base = f"/api/projects/{url_team.pk}/marketing_analytics_recommendation_resolutions/"
        existing = RecommendationResolution.objects.for_team(self.team.pk).create(
            team=self.team, **IDENTITY, resolution="dismissed"
        )
        if denial == "environment":
            self._connect_google_ads(environment, paused=paused)
            AccessControl.objects.create(
                team=environment,
                resource="project",
                resource_id=str(environment.id),
                access_level="none",
                organization_member=OrganizationMembership.objects.get(
                    user=getattr(self, user_attr), organization=self.organization
                ),
            )
        else:
            source = self._connect_google_ads(self.team, paused=paused)
            self._create_access_control(self.no_access_user, resource_id=str(source.id), access_level="none")
        self.client.force_login(getattr(self, user_attr))

        created = self.client.post(base, {"identity": IDENTITY, "resolution": "applied"}, format="json")
        deleted = self.client.delete(f"{base}{existing.id}/")

        assert (created.status_code, deleted.status_code) == statuses
