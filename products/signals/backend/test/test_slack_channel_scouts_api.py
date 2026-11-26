from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.models import SignalScoutConfig
from products.skills.backend.models.skills import LLMSkill
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource


class TestSlackChannelScoutsAPI(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/signals/slack_channel_scouts/{suffix}"

    def _slack_source(self, team: Team, channels: dict[str, str | None]) -> ExternalDataSource:
        """A Slack source with its fixed tables and one schema per channel id. A None name leaves the channel unsynced."""
        source = ExternalDataSource.objects.create(team=team, source_type="Slack", status="Running", prefix="")
        for schema_name in ("$channels", "$users", *channels):
            label = channels.get(schema_name)
            table = (
                None
                if schema_name in channels and label is None
                else DataWarehouseTable.objects.create(
                    team=team,
                    name=schema_name,
                    format="Parquet",
                    url_pattern=f"https://example.com/{schema_name}",
                    external_data_source=source,
                )
            )
            ExternalDataSchema.objects.create(
                team=team, source=source, name=schema_name, label=label or schema_name, table=table
            )
        return source

    def test_channels_lists_the_synced_channels_of_this_project_only(self) -> None:
        source = self._slack_source(self.team, {"C02": "support", "C01": "bugs", "C03": None})
        other_team = Team.objects.create(organization=self.organization, name="Other")
        self._slack_source(other_team, {"C09": "secret"})

        response = self.client.get(self._url("channels/"))

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {
            "sources": [
                {
                    "id": str(source.id),
                    "channels": [
                        {"id": "C01", "name": "bugs", "table_name": "slack.c01"},
                        {"id": "C03", "name": "C03", "table_name": None},
                        {"id": "C02", "name": "support", "table_name": "slack.c02"},
                    ],
                }
            ]
        }

    def test_create_makes_a_scout_owned_by_the_slack_source(self) -> None:
        source = self._slack_source(self.team, {"C01": "bugs", "C02": "support", "C03": "random"})

        response = self.client.post(
            self._url(),
            {
                "display_name": "Support channels",
                "source_id": str(source.id),
                "channel_ids": ["C01", "C02"],
                "steer": "Billing confusion",
                "emit": False,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        config = SignalScoutConfig.objects.get(team=self.team, skill_name=response.json()["skill_name"])
        assert (config.source_product, config.source_id) == ("slack", str(source.id))
        assert config.display_name == "Support channels"
        assert config.emit is False
        assert config.precheck_query is not None
        assert "slack.c01" in config.precheck_query and "slack.c02" in config.precheck_query
        assert "slack.c03" not in config.precheck_query
        body = LLMSkill.objects.get(team=self.team, name=config.skill_name, is_latest=True).body
        assert "#bugs: `slack.c01`" in body and "Billing confusion" in body
        assert "slack.c03" not in body

    @parameterized.expand(
        [
            ("unsynced_channel", "own", ["C03"]),
            ("unknown_channel", "own", ["C99"]),
            ("another_projects_source", "other", ["C09"]),
        ]
    )
    def test_create_rejects_channels_the_scout_cannot_read(
        self, _name: str, source_owner: str, channel_ids: list[str]
    ) -> None:
        own = self._slack_source(self.team, {"C01": "bugs", "C03": None})
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other = self._slack_source(other_team, {"C09": "secret"})
        source = own if source_owner == "own" else other

        response = self.client.post(
            self._url(),
            {"display_name": "Slack scout", "source_id": str(source.id), "channel_ids": channel_ids},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert not SignalScoutConfig.objects.filter(team=self.team, source_product="slack").exists()

    def test_a_source_the_member_is_denied_is_hidden_and_cannot_be_read_by_a_scout(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        allowed = self._slack_source(self.team, {"C01": "bugs"})
        denied = self._slack_source(self.team, {"C02": "hr-private"})
        member = User.objects.create_and_join(self.organization, "member@example.com", "password")
        AccessControl.objects.create(
            team=self.team,
            resource="external_data_source",
            resource_id=str(denied.id),
            organization_member=OrganizationMembership.objects.get(user=member, organization=self.organization),
            access_level="none",
        )
        self.client.force_login(member)

        listed = self.client.get(self._url("channels/"))
        created = self.client.post(
            self._url(),
            {"display_name": "HR", "source_id": str(denied.id), "channel_ids": ["C02"]},
            format="json",
        )

        assert listed.status_code == status.HTTP_200_OK, listed.json()
        assert [source["id"] for source in listed.json()["sources"]] == [str(allowed.id)]
        assert created.status_code == status.HTTP_400_BAD_REQUEST, created.json()
        assert not SignalScoutConfig.objects.filter(team=self.team, source_id=str(denied.id)).exists()
