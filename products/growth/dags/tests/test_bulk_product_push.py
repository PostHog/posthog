from contextlib import contextmanager
from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.models.organization import Organization

from products.growth.backend.models import ProductPushCampaign
from products.growth.dags.bulk_product_push import bulk_product_push_job


@contextmanager
def _mock_capture():
    capture_fn: Any = MagicMock()
    with patch("products.growth.backend.product_push.service.ph_scoped_capture") as mock_csm:
        mock_csm.return_value.__enter__.return_value = capture_fn
        mock_csm.return_value.__exit__.return_value = False
        yield capture_fn


class TestBulkProductPushJob(BaseTest):
    def _run_job(self, raise_on_error: bool = True, **config: Any) -> Any:
        run_config = {
            "ops": {
                "get_bulk_push_batches_op": {
                    "config": {
                        "organization_ids": [str(self.organization.id)],
                        "product_key": "session_replay",
                        **config,
                    }
                }
            }
        }
        with _mock_capture():
            return bulk_product_push_job.execute_in_process(run_config=run_config, raise_on_error=raise_on_error)

    def test_queues_a_scheduled_tam_campaign_per_organization(self) -> None:
        other = Organization.objects.create(name="other")

        result = self._run_job(organization_ids=[str(self.organization.id), str(other.id)], reason_text="Try replay")

        assert result.success
        campaigns = ProductPushCampaign.objects.all()
        assert campaigns.count() == 2
        for campaign in campaigns:
            assert campaign.status == ProductPushCampaign.Status.SCHEDULED
            assert campaign.source == ProductPushCampaign.Source.TAM
            assert campaign.product_key == "session_replay"
            assert campaign.reason_text == "Try replay"
            # Undated, so the daily sweep still applies grace period and cooldown.
            assert campaign.scheduled_for is None

    def test_rerunning_the_same_list_does_not_double_create(self) -> None:
        assert self._run_job().success
        assert self._run_job().success

        assert ProductPushCampaign.objects.filter(organization=self.organization).count() == 1

    def test_queues_behind_an_active_campaign_of_another_product(self) -> None:
        ProductPushCampaign.objects.create(
            organization=self.organization,
            product_key="product_analytics",
            status=ProductPushCampaign.Status.ACTIVE,
            started_at=timezone.now(),
        )

        assert self._run_job().success

        queued = ProductPushCampaign.objects.get(organization=self.organization, product_key="session_replay")
        assert queued.status == ProductPushCampaign.Status.SCHEDULED
        assert queued.position == 1

    def test_skips_organizations_that_adopted_or_recently_skipped_the_product(self) -> None:
        adopted_org = Organization.objects.create(name="adopted")
        ProductPushCampaign.objects.create(
            organization=adopted_org,
            product_key="session_replay",
            status=ProductPushCampaign.Status.ADOPTED,
            ended_at=timezone.now() - timedelta(days=1),
        )
        skipped_org = Organization.objects.create(name="skipped")
        ProductPushCampaign.objects.create(
            organization=skipped_org,
            product_key="session_replay",
            status=ProductPushCampaign.Status.SKIPPED,
            ended_at=timezone.now() - timedelta(days=1),
        )

        assert self._run_job(organization_ids=[str(adopted_org.id), str(skipped_org.id)]).success

        assert not ProductPushCampaign.objects.filter(status=ProductPushCampaign.Status.SCHEDULED).exists()

    def test_bypass_cadence_dates_the_campaign_and_ignores_the_retry_cooldown(self) -> None:
        ProductPushCampaign.objects.create(
            organization=self.organization,
            product_key="session_replay",
            status=ProductPushCampaign.Status.SKIPPED,
            ended_at=timezone.now() - timedelta(days=1),
        )

        assert self._run_job(bypass_cadence=True).success

        queued = ProductPushCampaign.objects.get(
            organization=self.organization, status=ProductPushCampaign.Status.SCHEDULED
        )
        assert queued.scheduled_for == timezone.now().date()

    def test_dry_run_and_max_campaigns_limit_what_is_written(self) -> None:
        assert self._run_job(dry_run=True).success
        assert not ProductPushCampaign.objects.exists()

        other = Organization.objects.create(name="other")
        assert self._run_job(organization_ids=[str(self.organization.id), str(other.id)], max_campaigns=1).success
        assert ProductPushCampaign.objects.count() == 1

    def test_invalid_product_key_fails_the_run(self) -> None:
        result = self._run_job(raise_on_error=False, product_key="not_a_product")

        assert not result.success
        assert not ProductPushCampaign.objects.exists()
