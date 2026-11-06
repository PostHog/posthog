from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

import dagster
from parameterized import parameterized

from posthog.models.organization import Organization

from products.growth.backend.models import ProductPushCampaign
from products.growth.dags.custom_product_push_campaigns import custom_product_push_campaigns_job
from products.growth.dags.product_push_campaigns import product_push_campaigns_job


@contextmanager
def _mock_capture() -> Iterator[MagicMock]:
    capture_fn = MagicMock()
    with patch("products.growth.backend.product_push.service.ph_scoped_capture") as mock_csm:
        mock_csm.return_value.__enter__.return_value = capture_fn
        mock_csm.return_value.__exit__.return_value = False
        yield capture_fn


class TestCustomProductPushCampaignsJob(BaseTest):
    def _run_job(self, raise_on_error: bool = True, **config: Any) -> dagster.ExecuteInProcessResult:
        today = timezone.now().date()
        run_config = {
            "ops": {
                "get_custom_product_push_batches_op": {
                    "config": {
                        "organization_ids": [str(self.organization.id)],
                        "product_key": "session_replay",
                        "starts_on": today.isoformat(),
                        "ends_on": (today + timedelta(days=20)).isoformat(),
                        "on_active_campaign": "queue",
                        **config,
                    }
                }
            }
        }
        with _mock_capture():
            return custom_product_push_campaigns_job.execute_in_process(
                run_config=run_config, raise_on_error=raise_on_error
            )

    def _start_active_campaign(self, organization: Organization, product_key: str) -> ProductPushCampaign:
        return ProductPushCampaign.objects.create(
            organization=organization,
            product_key=product_key,
            status=ProductPushCampaign.Status.ACTIVE,
            started_at=timezone.now(),
            ends_at=timezone.now() + timedelta(days=14),
        )

    def test_creates_a_scheduled_tam_campaign_with_the_requested_window(self) -> None:
        other = Organization.objects.create(name="other")
        today = timezone.now().date()

        result = self._run_job(
            organization_ids=[str(self.organization.id), str(other.id)],
            starts_on=(today + timedelta(days=2)).isoformat(),
            ends_on=(today + timedelta(days=9)).isoformat(),
            reason_text="Try replay",
        )

        assert result.success
        campaigns = ProductPushCampaign.objects.all()
        assert campaigns.count() == 2
        for campaign in campaigns:
            assert campaign.status == ProductPushCampaign.Status.SCHEDULED
            assert campaign.source == ProductPushCampaign.Source.TAM
            assert campaign.product_key == "session_replay"
            assert campaign.reason_text == "Try replay"
            assert campaign.scheduled_for == today + timedelta(days=2)
            assert campaign.ends_at is not None
            assert campaign.ends_at.date() == today + timedelta(days=9)

    def test_rerunning_the_same_list_does_not_double_create(self) -> None:
        assert self._run_job().success
        assert self._run_job().success

        assert ProductPushCampaign.objects.filter(organization=self.organization).count() == 1

    @parameterized.expand(
        [
            ("skip", 20, ProductPushCampaign.Status.ACTIVE, False),
            ("queue", 20, ProductPushCampaign.Status.ACTIVE, True),
            ("override", 20, ProductPushCampaign.Status.CANCELLED, True),
            # The running campaign outlasts this window, so a queued push would
            # expire before getting to run — nothing is written for the org.
            ("queue", 5, ProductPushCampaign.Status.ACTIVE, False),
        ]
    )
    def test_policy_decides_what_happens_to_a_running_campaign(
        self, policy: str, window_days: int, running_status: str, creates_campaign: bool
    ) -> None:
        running = self._start_active_campaign(self.organization, "product_analytics")

        assert self._run_job(
            on_active_campaign=policy,
            ends_on=(timezone.now().date() + timedelta(days=window_days)).isoformat(),
        ).success

        running.refresh_from_db()
        assert running.status == running_status
        created = ProductPushCampaign.objects.filter(product_key="session_replay").first()
        assert (created is not None) == creates_campaign
        if created is not None:
            assert created.status == ProductPushCampaign.Status.SCHEDULED
            assert created.position == 1

    def test_the_daily_job_starts_the_campaign_and_keeps_its_window(self) -> None:
        today = timezone.now().date()
        assert self._run_job(ends_on=(today + timedelta(days=3)).isoformat()).success

        with _mock_capture():
            assert product_push_campaigns_job.execute_in_process().success

        campaign = ProductPushCampaign.objects.get(product_key="session_replay")
        assert campaign.status == ProductPushCampaign.Status.ACTIVE
        assert campaign.ends_at is not None
        # The requested window survives, rather than the default 14-day duration.
        assert campaign.ends_at.date() == today + timedelta(days=3)

    def test_a_campaign_whose_window_passed_is_cancelled_instead_of_started(self) -> None:
        assert self._run_job().success
        campaign = ProductPushCampaign.objects.get(product_key="session_replay")
        ProductPushCampaign.objects.filter(id=campaign.id).update(ends_at=timezone.now() - timedelta(days=1))

        with _mock_capture():
            assert product_push_campaigns_job.execute_in_process().success

        campaign.refresh_from_db()
        assert campaign.status == ProductPushCampaign.Status.CANCELLED

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

        assert self._run_job(organization_ids=[str(skipped_org.id)], skip_recently_pushed=False).success

        assert ProductPushCampaign.objects.filter(
            organization=skipped_org, status=ProductPushCampaign.Status.SCHEDULED
        ).exists()

    def test_dry_run_and_max_campaigns_limit_what_is_written(self) -> None:
        assert self._run_job(dry_run=True).success
        assert not ProductPushCampaign.objects.exists()

        other = Organization.objects.create(name="other")
        assert self._run_job(organization_ids=[str(self.organization.id), str(other.id)], max_campaigns=1).success
        assert ProductPushCampaign.objects.count() == 1

    @parameterized.expand(
        [
            ("unknown product", {"product_key": "not_a_product"}, None, None),
            ("unknown policy", {"on_active_campaign": "cancel_everything"}, None, None),
            ("window already past", {}, None, -1),
            ("end before start", {}, 5, 0),
        ]
    )
    def test_invalid_config_fails_the_run(
        self, _name: str, overrides: dict[str, Any], starts_in_days: int | None, ends_in_days: int | None
    ) -> None:
        today = timezone.now().date()
        config = dict(overrides)
        if starts_in_days is not None:
            config["starts_on"] = (today + timedelta(days=starts_in_days)).isoformat()
        if ends_in_days is not None:
            config["ends_on"] = (today + timedelta(days=ends_in_days)).isoformat()

        result = self._run_job(raise_on_error=False, **config)

        assert not result.success
        assert not ProductPushCampaign.objects.exists()
