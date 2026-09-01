from typing import Any

from posthog.test.base import NonAtomicTestMigrations


class PublicResearchConsentMigrationTest(NonAtomicTestMigrations):
    migrate_from = "0006_pulse_run_history_and_artifact_publication_indexes"
    migrate_to = "0007_proactivesubscriptionconfig_public_research_enabled"

    CLASS_DATA_LEVEL_SETUP = False

    @property
    def app(self) -> str:
        return "subscriptions"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        PublicResearchSubject = apps.get_model("subscriptions", "PublicResearchSubject")
        ProactiveSubscriptionConfig = apps.get_model("subscriptions", "ProactiveSubscriptionConfig")

        organization = Organization.objects.create(name="Public research migration organization")
        project = Project.objects.create(id=999993, organization=organization, name="Public research migration project")
        team = Team.objects.create(organization=organization, project=project, name="Public research migration team")
        subject = PublicResearchSubject.all_teams.create(
            team=team,
            name="Legacy reviewed subject",
            canonical_domain="example.com",
        )
        legacy_config = ProactiveSubscriptionConfig.all_teams.create(
            team=team,
            subscription_id=1,
            enabled=True,
            public_research_subject=subject,
        )
        plain_config = ProactiveSubscriptionConfig.all_teams.create(
            team=team,
            subscription_id=2,
            enabled=True,
        )
        self.team_id = team.id
        self.legacy_config_id = legacy_config.id
        self.plain_config_id = plain_config.id

    def test_existing_configs_remain_opted_out_while_new_configs_default_on(self) -> None:
        assert self.apps is not None
        ProactiveSubscriptionConfig = self.apps.get_model("subscriptions", "ProactiveSubscriptionConfig")

        assert ProactiveSubscriptionConfig.all_teams.get(id=self.legacy_config_id).public_research_enabled is False
        assert ProactiveSubscriptionConfig.all_teams.get(id=self.plain_config_id).public_research_enabled is False

        created = ProactiveSubscriptionConfig.all_teams.create(
            team_id=self.team_id,
            subscription_id=3,
            enabled=True,
        )
        assert created.public_research_enabled is True
