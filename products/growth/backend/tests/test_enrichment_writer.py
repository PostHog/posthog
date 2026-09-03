from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.fit_score import IcpFitResult
from products.growth.backend.enrichment.writer import record_signup_work_email, write_organization_enrichment
from products.growth.backend.models import OrganizationEnrichment


def _fit(score=72, **overrides):
    kwargs = {
        "status": "scored",
        "score": score,
        "components": {"traction": 25, "capital": 30, "ai_pilled": 15, "headcount_growth": 0, "software_relevance": 2},
        "quality_investor": True,
        "data_coverage": 3,
        "low_confidence": False,
        "agency_flag": False,
        "nonprofit_flag": False,
        "lists_version": "lists-1",
    }
    kwargs.update(overrides)
    return IcpFitResult(**kwargs)


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

    def test_legacy_clay_score_still_writes_its_own_keys(self):
        # The clay score keeps its exact master behavior: same keys, same version stamp,
        # same person mirror — its threshold-tuned consumers must not notice this PR.
        pha_client = MagicMock()
        write_organization_enrichment(
            organization_id=str(self.organization.id),
            fields=EnrichmentFields(company_type="STARTUP"),
            pha_client=pha_client,
            icp_score=12,
            mirror_distinct_id="signer",
        )

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_score"] == 12
        assert record.data["icp_score_version"] == "clay-parity-2"
        properties = pha_client.group_identify.call_args.kwargs["properties"]
        assert properties["icp_score"] == 12
        pha_client.set.assert_called_once_with(
            distinct_id="signer", properties={"icp_score": 12, "icp_score_version": "clay-parity-2"}
        )

    def test_fit_writes_its_own_key_family_next_to_the_clay_score(self):
        pha_client = MagicMock()
        write_organization_enrichment(
            organization_id=str(self.organization.id),
            fields=EnrichmentFields(company_type="STARTUP"),
            pha_client=pha_client,
            icp_score=9,
            fit=_fit(),
        )

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        # The two families never share a key.
        assert record.data["icp_score"] == 9
        assert record.data["icp_fit_score"] == 72
        assert record.data["icp_fit_version"] == "v0.5"
        assert record.data["icp_fit_status"] == "scored"
        assert record.data["icp_fit_lists_version"] == "lists-1"
        assert record.data["icp_fit_components"]["capital"] == 30
        assert record.data["icp_fit_flags"] == {
            "quality_investor": True,
            "data_coverage": 3,
            "low_confidence": False,
            "agency_flag": False,
            "nonprofit_flag": False,
        }
        properties = pha_client.group_identify.call_args.kwargs["properties"]
        assert properties["icp_score"] == 9
        assert properties["icp_fit_score"] == 72
        assert properties["icp_fit_version"] == "v0.5"
        assert properties["icp_fit_status"] == "scored"

    def test_fit_only_write_carries_no_field_or_clay_keys(self):
        # The fit backfill passes fields=None and no clay score: only icp_fit_* keys move.
        pha_client = MagicMock()
        write_organization_enrichment(
            organization_id=str(self.organization.id),
            fields=None,
            pha_client=pha_client,
            fit=_fit(score=41),
        )

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_fit_score"] == 41
        assert "company_type" not in record.data
        assert "icp_score" not in record.data
        properties = pha_client.group_identify.call_args.kwargs["properties"]
        assert set(properties) == {"icp_fit_score", "icp_fit_version", "icp_fit_status"}

    def test_scoreless_fit_evaluation_strips_stale_numeric_keys_from_the_record(self):
        OrganizationEnrichment.objects.create(
            organization=self.organization,
            data={
                "icp_fit_score": 62,
                "icp_fit_version": "v0.5",
                "icp_fit_components": {"traction": 30},
                "icp_score": 6,  # clay key must survive fit stripping
                "work_email": True,
            },
        )
        pha_client = MagicMock()
        write_organization_enrichment(
            organization_id=str(self.organization.id),
            fields=None,
            pha_client=pha_client,
            fit=IcpFitResult(status="insufficient_data", lists_version="lists-1"),
        )

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data == {
            "work_email": True,
            "icp_score": 6,
            "icp_fit_status": "insufficient_data",
            "icp_fit_version": "v0.5",
            "icp_fit_lists_version": "lists-1",
        }
        # Group properties cannot be deleted, so only the status key is projected: pairing
        # the fresh version with the group's stale numeric score would misattribute it.
        properties = pha_client.group_identify.call_args.kwargs["properties"]
        assert properties == {"icp_fit_status": "insufficient_data"}

    def test_disqualification_after_a_scored_pass_strips_the_stale_components_and_flags(self):
        pha_client = MagicMock()
        write_organization_enrichment(
            organization_id=str(self.organization.id), fields=None, pha_client=pha_client, fit=_fit(score=62)
        )
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_fit_components"]["capital"] == 30
        assert "icp_fit_flags" in record.data

        write_organization_enrichment(
            organization_id=str(self.organization.id),
            fields=None,
            pha_client=pha_client,
            fit=IcpFitResult(status="disqualified", score=0, dq_reason="role=student"),
        )
        record.refresh_from_db()
        assert record.data["icp_fit_score"] == 0
        assert record.data["icp_fit_dq_reason"] == "role=student"
        assert "icp_fit_components" not in record.data
        assert "icp_fit_flags" not in record.data

    def test_scored_pass_after_a_disqualification_clears_the_dq_reason(self):
        pha_client = MagicMock()
        write_organization_enrichment(
            organization_id=str(self.organization.id),
            fields=None,
            pha_client=pha_client,
            fit=IcpFitResult(status="disqualified", score=0, dq_reason="company_type=SCHOOL"),
        )
        write_organization_enrichment(
            organization_id=str(self.organization.id), fields=None, pha_client=pha_client, fit=_fit()
        )

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_fit_score"] == 72
        assert "icp_fit_dq_reason" not in record.data

    def test_fit_mirror_carries_status_through_a_scored_to_insufficient_data_transition(self):
        pha_client = MagicMock()
        write_organization_enrichment(
            organization_id=str(self.organization.id),
            fields=None,
            pha_client=pha_client,
            fit=_fit(score=55),
            fit_mirror_distinct_id="signer",
        )
        pha_client.set.assert_called_once_with(
            distinct_id="signer",
            properties={"icp_fit_score": 55, "icp_fit_version": "v0.5", "icp_fit_status": "scored"},
        )

        pha_client.reset_mock()
        write_organization_enrichment(
            organization_id=str(self.organization.id),
            fields=None,
            pha_client=pha_client,
            fit=IcpFitResult(status="insufficient_data"),
            fit_mirror_distinct_id="signer",
        )
        pha_client.set.assert_called_once_with(distinct_id="signer", properties={"icp_fit_status": "insufficient_data"})

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

    def test_record_signup_work_email_lowercases_and_skips_blank_roles(self):
        record_signup_work_email(organization_id=str(self.organization.id), work_email=True, signup_role="Founder")
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data == {"work_email": True, "signup_role": "founder"}

        record_signup_work_email(organization_id=str(self.organization.id), work_email=True, signup_role="  ")
        record.refresh_from_db()
        assert record.data["signup_role"] == "founder"  # blank role never clobbers a recorded one

    def test_no_op_when_no_fields_and_no_scores(self):
        pha_client = MagicMock()
        write_organization_enrichment(
            organization_id=str(self.organization.id),
            fields=EnrichmentFields(),
            pha_client=pha_client,
        )
        assert not OrganizationEnrichment.objects.filter(organization=self.organization).exists()
        pha_client.group_identify.assert_not_called()
