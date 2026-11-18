from datetime import timedelta

from posthog.test.base import BaseTest

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from products.growth.backend.enrichment.scoring_lab import preview_scoring_formula
from products.growth.backend.models import (
    EnrichmentLabelResult,
    EnrichmentPromptConfig,
    IcpScoringConfig,
    OrganizationEnrichmentFetch,
)


class TestScoringContext(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.email = "operator@inventory.example.com"
        self.user.save(update_fields=["email"])
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        EnrichmentPromptConfig.objects.update(is_active=False)
        self.config = EnrichmentPromptConfig.objects.create(
            name="company_segment",
            version="segment-v1",
            prompt_text="Classify the supplied company facts.",
            model="gpt-5-mini",
            input_fields=["description"],
            output_fields=[
                {"key": "enterprise", "type": "boolean"},
                {"key": "self_serve", "type": "boolean"},
                {"key": "team_size", "type": "number"},
                {"key": "summary", "type": "string"},
                {"key": "uncertain", "type": "boolean"},
            ],
            is_active=True,
        )
        self.scoring = IcpScoringConfig.objects.create(
            version="context-v1", tags=[], quality_investors=[], is_active=True
        )
        self.fetch = OrganizationEnrichmentFetch.objects.create(
            organization=self.organization,
            provider="harmonic",
            payload={"id": "synthetic-inventory-company", "headcount": 8, "description": "Inventory software."},
        )
        self.output = {
            "enterprise": True,
            "self_serve": False,
            "team_size": 42,
            "summary": "Business software",
            "uncertain": "unknown",
        }
        self.result = EnrichmentLabelResult.objects.create(
            organization=self.organization,
            fetch=self.fetch,
            label_name=self.config.name,
            prompt_version=self.config.version,
            prompt_hash=self.config.content_hash,
            model=self.config.model,
            output={**self.output, "meta": {"tool_calls": []}, "unconfigured": "not an input"},
            inputs={"signup_domain": "inventory.example.com"},
        )

    def test_preview_reads_all_configured_output_fields_from_a_non_ai_label(self):
        source = """
            let points := if(enrichments.company_segment.enterprise == true, 12, 0);
            return {'status': 'scored', 'score': points, 'components': {'enterprise': points}};
        """

        second_config = EnrichmentPromptConfig.objects.create(
            name="recruitment",
            version="recruitment-v1",
            prompt_text="Classify whether the company is recruiting engineers.",
            model="gpt-5-mini",
            input_fields=["description"],
            output_fields=[{"key": "hiring", "type": "boolean"}],
            is_active=True,
        )
        second_result = EnrichmentLabelResult.objects.create(
            organization=self.organization,
            fetch=self.fetch,
            label_name=second_config.name,
            prompt_version=second_config.version,
            prompt_hash=second_config.content_hash,
            model=second_config.model,
            output={"hiring": False},
            inputs={"signup_domain": "inventory.example.com"},
        )

        with CaptureQueriesContext(connection) as queries:
            preview = preview_scoring_formula(self.scoring, self.scoring, source, 1)

        assert len(preview) == 1
        assert preview[0].error is None
        assert preview[0].preview is not None
        assert preview[0].preview.score == 12
        assert preview[0].inputs["enrichments"] == {"company_segment": self.output, "recruitment": {"hiring": False}}
        assert preview[0].preview.input_versions == {
            "current_fetch": str(self.fetch.id),
            "enrichment/company_segment": str(self.result.id),
            "enrichment/recruitment": str(second_result.id),
        }
        assert not any(
            query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) or "FOR UPDATE" in query["sql"]
            for query in queries
        )

    @parameterized.expand(
        [
            ("consent_revoked",),
            ("signup_identity_changed",),
            ("different_result_domain",),
            ("old_prompt_version",),
            ("old_prompt_hash",),
            ("inactive_config",),
            ("different_fetch",),
            ("fallback_company_facts",),
        ]
    )
    def test_preview_excludes_ineligible_saved_outputs(self, change):
        if change == "consent_revoked":
            self.organization.is_ai_data_processing_approved = False
            self.organization.save(update_fields=["is_ai_data_processing_approved"])
        elif change == "signup_identity_changed":
            self.user.email = "operator@different.example.com"
            self.user.save(update_fields=["email"])
        elif change == "different_result_domain":
            self.result.inputs = {"signup_domain": "different.example.com"}
            self.result.save(update_fields=["inputs"])
        elif change == "old_prompt_version":
            self.result.prompt_version = "retired-version"
            self.result.save(update_fields=["prompt_version"])
        elif change == "old_prompt_hash":
            self.result.prompt_hash = "outdated-hash"
            self.result.save(update_fields=["prompt_hash"])
        elif change == "inactive_config":
            self.config.is_active = False
            self.config.save(update_fields=["is_active"])
        elif change == "different_fetch":
            latest = OrganizationEnrichmentFetch.objects.create(
                organization=self.organization, provider="harmonic", payload=self.fetch.payload
            )
            OrganizationEnrichmentFetch.objects.filter(pk=latest.pk).update(
                fetched_at=self.fetch.fetched_at + timedelta(seconds=1)
            )
        elif change == "fallback_company_facts":
            fetched_at = self.fetch.fetched_at + timedelta(seconds=1)
            self.fetch = OrganizationEnrichmentFetch.objects.create(
                organization=self.organization, provider="harmonic", payload={"companyFound": False}
            )
            OrganizationEnrichmentFetch.objects.filter(pk=self.fetch.pk).update(fetched_at=fetched_at)
            self.result.fetch = self.fetch
            self.result.output = {"uncertain": "unknown"}
            self.result.save(update_fields=["fetch", "output"])

        source = "return {'status': 'scored', 'score': 0, 'components': {}};"
        preview = preview_scoring_formula(self.scoring, self.scoring, source, 1)

        assert preview[0].error is None
        assert preview[0].inputs["enrichments"] == {}
        assert preview[0].preview is not None
        assert set(preview[0].preview.input_versions) == {"current_fetch"}
