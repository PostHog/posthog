import uuid

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team
from posthog.models.integration import Integration

from products.warehouse_sources.backend.facade import api as facade_api
from products.warehouse_sources.backend.models.external_data_source import (
    ExternalDataSource,
    integration_id_from_job_inputs,
)


class TestIntegrationIdFromJobInputs(SimpleTestCase):
    @parameterized.expand(
        [
            ("int_value", {"salesforce_integration_id": 3}, 3),
            ("string_value", {"google_ads_integration_id": "3"}, 3),
            ("custom_oauth2_excluded", {"auth_oauth2_integration_id": str(uuid.uuid4())}, None),
            ("non_numeric_ignored", {"hubspot_integration_id": "garbage"}, None),
            ("no_integration_key", {"api_key": "secret"}, None),
        ]
    )
    def test_integration_id_from_job_inputs(self, _name, job_inputs, expected):
        assert integration_id_from_job_inputs(job_inputs) == expected


class TestExternalDataSourceIntegrationLink(BaseTest):
    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team, kind="salesforce", integration_id="sf-1", config={}
        )

    def _create_source(self, job_inputs: dict | None, **kwargs) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Salesforce",
            job_inputs=job_inputs,
            **kwargs,
        )

    def test_save_derives_and_clears_integration_link(self):
        source = self._create_source({"salesforce_integration_id": self.integration.id})
        assert source.integration_id == self.integration.id

        source.job_inputs = {"salesforce_api_key": "secret"}
        source.save()
        source.refresh_from_db()
        assert source.integration_id is None

    def test_save_with_update_fields_persists_derived_link(self):
        # Temporal token-refresh paths save with update_fields=["job_inputs"] — the derived
        # link must be added to update_fields or it would silently never persist there.
        source = self._create_source(None)
        source.job_inputs = {"salesforce_integration_id": self.integration.id}
        source.save(update_fields=["job_inputs"])

        source.refresh_from_db()
        assert source.integration_id == self.integration.id

    def test_dangling_and_cross_team_references_are_not_linked(self):
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        other_team_integration = Integration.objects.create(team=other_team, kind="salesforce", config={})

        dangling = self._create_source({"salesforce_integration_id": self.integration.id + 1000})
        cross_team = self._create_source({"salesforce_integration_id": other_team_integration.id})

        assert dangling.integration_id is None
        assert cross_team.integration_id is None

    def test_counts_exclude_deleted_sources(self):
        self._create_source({"salesforce_integration_id": self.integration.id})
        self._create_source({"salesforce_integration_id": self.integration.id}, deleted=True)

        assert facade_api.count_sources_using_integrations(self.team.pk, [self.integration.id]) == {
            self.integration.id: 1
        }
        assert facade_api.list_source_labels_using_integration(self.team.pk, self.integration.id) == ["Salesforce"]
