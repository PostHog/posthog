from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import override_settings

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User

from products.growth.backend.enrichment.icp_lists import clear_lists_cache
from products.growth.backend.models import IcpScoringConfig, OrganizationEnrichment, OrganizationEnrichmentFetch

_COMMAND_MODULE = "products.growth.backend.management.commands.backfill_icp_fit_scores"

# REST-shaped and matched (has "id"), but empty enough to score insufficient_data — the
# status doesn't matter here, only that an evaluation happens and gets labeled.
_REST_PAYLOAD: dict[str, Any] = {
    "id": "harmonic-id-1",
    "company_type": "STARTUP",
    "headcount": None,
    "funding": {"funding_total": None, "investors": []},
    "tags_v2": [],
    "traction_metrics": {},
}


@override_settings(CLOUD_DEPLOYMENT="US")
class TestBackfillIcpFitScores(BaseTest):
    def setUp(self):
        super().setUp()
        IcpScoringConfig.objects.create(version="test-lists-1", tags=[], quality_investors=[], is_active=True)
        clear_lists_cache()

    def tearDown(self):
        clear_lists_cache()
        super().tearDown()

    def test_writes_the_backfill_evaluation_kind(self):
        organization = Organization.objects.create(name="acme")
        user = User.objects.create_user(email="founder@acme.com", password=None, first_name="f")
        OrganizationMembership.objects.create(organization=organization, user=user)
        OrganizationEnrichmentFetch.objects.create(
            organization=organization, provider="harmonic", payload=_REST_PAYLOAD
        )

        with patch(f"{_COMMAND_MODULE}.get_regional_ph_client", return_value=MagicMock()):
            call_command("backfill_icp_fit_scores", delay=0)

        record = OrganizationEnrichment.objects.get(organization=organization)
        assert record.data["icp_fit_evaluation_kind"] == "backfill"
        assert record.data["icp_fit_evaluated_at"]
