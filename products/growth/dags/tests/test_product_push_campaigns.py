from contextlib import contextmanager
from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.models.organization import Organization

from products.growth.backend.models import ProductPushCampaign
from products.growth.backend.product_push.cadence import CAMPAIGN_DURATION_DAYS
from products.growth.dags.product_push_campaigns import product_push_campaigns_job


@contextmanager
def _mock_capture():
    capture_fn: Any = MagicMock()
    with patch("products.growth.backend.product_push.service.ph_scoped_capture") as mock_csm:
        mock_csm.return_value.__enter__.return_value = capture_fn
        mock_csm.return_value.__exit__.return_value = False
        yield capture_fn


class TestProductPushCampaignsJob(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._age_organization(self.organization, days=40)

    def _age_organization(self, organization: Organization, days: int) -> None:
        Organization.objects.filter(id=organization.id).update(created_at=timezone.now() - timedelta(days=days))

    def _run_job(self, start_config: dict | None = None) -> Any:
        run_config = {"ops": {"get_eligible_org_batches_op": {"config": start_config}}} if start_config else None
        with _mock_capture():
            return product_push_campaigns_job.execute_in_process(run_config=run_config)

    def test_first_run_with_no_active_campaigns_still_starts_for_eligible_org(self) -> None:
        result = self._run_job()

        assert result.success
        campaign = ProductPushCampaign.objects.get(organization=self.organization)
        assert campaign.status == ProductPushCampaign.Status.ACTIVE
        assert campaign.product_key == "product_analytics"

    def test_expired_campaign_is_skipped_and_cooldown_blocks_a_same_run_restart(self) -> None:
        started_at = timezone.now() - timedelta(days=CAMPAIGN_DURATION_DAYS + 1)
        campaign = ProductPushCampaign.objects.create(
            organization=self.organization,
            product_key="product_analytics",
            status=ProductPushCampaign.Status.ACTIVE,
            started_at=started_at,
            ends_at=started_at + timedelta(days=CAMPAIGN_DURATION_DAYS),
        )

        result = self._run_job()

        assert result.success
        campaign.refresh_from_db()
        assert campaign.status == ProductPushCampaign.Status.SKIPPED
        assert not ProductPushCampaign.objects.filter(
            organization=self.organization, status=ProductPushCampaign.Status.ACTIVE
        ).exists()

    def test_dry_run_and_zero_rollout_write_nothing(self) -> None:
        result = self._run_job({"dry_run": True})
        assert result.success
        assert not ProductPushCampaign.objects.exists()

        result = self._run_job({"rollout_percentage": 0.0})
        assert result.success
        assert not ProductPushCampaign.objects.exists()

    def test_organization_ids_override_and_max_starts_cap(self) -> None:
        other = Organization.objects.create(name="other")
        self._age_organization(other, days=40)

        result = self._run_job({"organization_ids": [str(other.id)]})
        assert result.success
        assert not ProductPushCampaign.objects.filter(organization=self.organization).exists()
        assert ProductPushCampaign.objects.filter(organization=other).count() == 1

        ProductPushCampaign.objects.all().delete()

        result = self._run_job({"max_starts": 1})
        assert result.success
        assert ProductPushCampaign.objects.filter(status=ProductPushCampaign.Status.ACTIVE).count() == 1
