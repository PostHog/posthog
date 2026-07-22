from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.writer import record_signup_work_email, write_organization_enrichment
from products.growth.backend.models import OrganizationEnrichment


class TestEnrichmentWriter(BaseTest):
    def test_merges_into_existing_record_without_clobbering_other_writers(self):
        OrganizationEnrichment.objects.create(organization=self.organization, data={"company_type_deterministic": "yc"})
        pha_client = MagicMock()

        write_organization_enrichment(
            organization_id=str(self.organization.id),
            fields=EnrichmentFields(company_type="STARTUP", headcount=130),
            pha_client=pha_client,
        )

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data == {
            "company_type_deterministic": "yc",
            "company_type": "STARTUP",
            "headcount": 130,
        }

    def test_creates_record_when_missing(self):
        write_organization_enrichment(
            organization_id=str(self.organization.id),
            fields=EnrichmentFields(industry="Fintech"),
            pha_client=MagicMock(),
        )
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data == {"industry": "Fintech"}

    def test_projects_enrichment_group_properties(self):
        pha_client = MagicMock()
        write_organization_enrichment(
            organization_id=str(self.organization.id),
            fields=EnrichmentFields(company_type="STARTUP", founded_year=2019),
            pha_client=pha_client,
        )
        pha_client.group_identify.assert_called_once_with(
            "organization",
            str(self.organization.id),
            properties={"enrichment_company_type": "STARTUP", "enrichment_founded_year": 2019},
        )

    def test_record_signup_work_email_merges_without_clobbering_provider_data(self):
        record_signup_work_email(organization_id=str(self.organization.id), work_email=False)
        assert OrganizationEnrichment.objects.get(organization=self.organization).data == {"work_email": False}

        write_organization_enrichment(
            organization_id=str(self.organization.id),
            fields=EnrichmentFields(headcount=9),
            pha_client=MagicMock(),
        )
        record_signup_work_email(organization_id=str(self.organization.id), work_email=True)
        assert OrganizationEnrichment.objects.get(organization=self.organization).data == {
            "work_email": True,
            "headcount": 9,
        }

    def test_no_op_when_no_fields_set(self):
        pha_client = MagicMock()
        write_organization_enrichment(
            organization_id=str(self.organization.id),
            fields=EnrichmentFields(),
            pha_client=pha_client,
        )
        assert not OrganizationEnrichment.objects.filter(organization=self.organization).exists()
        pha_client.group_identify.assert_not_called()
