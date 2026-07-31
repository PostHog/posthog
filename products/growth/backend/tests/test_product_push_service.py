from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.models.organization import Organization
from posthog.models.product_intent.product_intent import ProductIntent

from products.growth.backend.models import ProductPushCampaign
from products.growth.backend.product_push.cadence import CAMPAIGN_DURATION_DAYS
from products.growth.backend.product_push.service import (
    cancel_campaigns,
    evaluate_and_close_campaign_batch,
    get_eligible_organization_queryset,
    start_campaigns_for_org_batch,
)


class TestProductPushService(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = timezone.now()
        self._age_organization(self.organization, days=40)

    def _age_organization(self, organization: Organization, days: int) -> None:
        Organization.objects.filter(id=organization.id).update(created_at=self.now - timedelta(days=days))
        organization.refresh_from_db()

    def _active_campaign(self, product_key: str, started_days_ago: int = 5) -> ProductPushCampaign:
        started_at = self.now - timedelta(days=started_days_ago)
        return ProductPushCampaign.objects.create(
            organization=self.organization,
            product_key=product_key,
            status=ProductPushCampaign.Status.ACTIVE,
            started_at=started_at,
            ends_at=started_at + timedelta(days=CAMPAIGN_DURATION_DAYS),
        )

    # --- starting -----------------------------------------------------------

    def test_start_creates_active_campaign_and_rerun_is_a_noop(self) -> None:
        with patch("products.growth.backend.product_push.service.ph_scoped_capture") as mock_scoped:
            mock_capture = MagicMock()
            mock_scoped.return_value.__enter__.return_value = mock_capture
            result = start_campaigns_for_org_batch([str(self.organization.id)], self.now)

        assert result.started == 1
        campaign = ProductPushCampaign.objects.get(organization=self.organization)
        assert campaign.status == ProductPushCampaign.Status.ACTIVE
        assert campaign.product_key == "product_analytics"
        assert campaign.source == ProductPushCampaign.Source.AUTO
        assert campaign.started_at == self.now
        assert campaign.ends_at == self.now + timedelta(days=CAMPAIGN_DURATION_DAYS)
        assert mock_capture.call_args.kwargs["event"] == "product push campaign started"
        assert mock_capture.call_args.kwargs["distinct_id"] == str(self.organization.id)

        rerun = start_campaigns_for_org_batch([str(self.organization.id)], self.now)
        assert rerun.started == 0
        assert rerun.not_eligible == 1
        assert ProductPushCampaign.objects.filter(organization=self.organization).count() == 1

    def test_start_promotes_due_tam_row_instead_of_creating(self) -> None:
        scheduled = ProductPushCampaign.objects.create(
            organization=self.organization,
            product_key="surveys",
            status=ProductPushCampaign.Status.SCHEDULED,
            source=ProductPushCampaign.Source.TAM,
        )

        result = start_campaigns_for_org_batch([str(self.organization.id)], self.now)

        assert result.started == 1
        scheduled.refresh_from_db()
        assert scheduled.status == ProductPushCampaign.Status.ACTIVE
        assert scheduled.source == ProductPushCampaign.Source.TAM
        assert scheduled.started_at == self.now
        assert ProductPushCampaign.objects.filter(organization=self.organization).count() == 1

    def test_org_in_signup_grace_period_does_not_start(self) -> None:
        self._age_organization(self.organization, days=5)

        result = start_campaigns_for_org_batch([str(self.organization.id)], self.now)

        assert result.started == 0
        assert result.not_eligible == 1

    def test_cooldown_blocks_auto_start_but_due_dated_pin_bypasses_it(self) -> None:
        ProductPushCampaign.objects.create(
            organization=self.organization,
            product_key="session_replay",
            status=ProductPushCampaign.Status.SKIPPED,
            ended_at=self.now - timedelta(days=2),
        )

        result = start_campaigns_for_org_batch([str(self.organization.id)], self.now)
        assert result.started == 0
        assert result.not_eligible == 1

        ProductPushCampaign.objects.create(
            organization=self.organization,
            product_key="surveys",
            status=ProductPushCampaign.Status.SCHEDULED,
            source=ProductPushCampaign.Source.TAM,
            scheduled_for=self.now.date(),
        )

        result = start_campaigns_for_org_batch([str(self.organization.id)], self.now)
        assert result.started == 1
        assert (
            ProductPushCampaign.objects.get(
                organization=self.organization, status=ProductPushCampaign.Status.ACTIVE
            ).product_key
            == "surveys"
        )

    def test_dry_run_writes_nothing(self) -> None:
        result = start_campaigns_for_org_batch([str(self.organization.id)], self.now, dry_run=True)

        assert result.would_start == 1
        assert result.started == 0
        assert not ProductPushCampaign.objects.filter(organization=self.organization).exists()

    # --- closing ------------------------------------------------------------

    def test_activated_intent_during_campaign_closes_as_adopted(self) -> None:
        campaign = self._active_campaign("product_analytics")
        ProductIntent.objects.create(team=self.team, product_type="product_analytics", activated_at=self.now)

        result = evaluate_and_close_campaign_batch([str(campaign.id)], self.now)

        assert result.adopted == 1
        campaign.refresh_from_db()
        assert campaign.status == ProductPushCampaign.Status.ADOPTED
        assert campaign.ended_at == self.now
        assert campaign.metadata["adoption_signal"] == "intent_activated"
        assert campaign.metadata["adoption_team_id"] == self.team.id

    def test_activation_before_campaign_start_does_not_count(self) -> None:
        campaign = self._active_campaign("product_analytics", started_days_ago=5)
        intent = ProductIntent.objects.create(team=self.team, product_type="product_analytics")
        ProductIntent.objects.filter(id=intent.id).update(
            activated_at=self.now - timedelta(days=10), activation_last_checked_at=self.now
        )

        result = evaluate_and_close_campaign_batch([str(campaign.id)], self.now)

        assert result.adopted == 0
        campaign.refresh_from_db()
        assert campaign.status == ProductPushCampaign.Status.ACTIVE

    def test_expired_campaign_without_adoption_closes_as_skipped(self) -> None:
        campaign = self._active_campaign("product_analytics", started_days_ago=CAMPAIGN_DURATION_DAYS + 1)

        with patch("products.growth.backend.product_push.service.ph_scoped_capture") as mock_scoped:
            mock_capture = MagicMock()
            mock_scoped.return_value.__enter__.return_value = mock_capture
            result = evaluate_and_close_campaign_batch([str(campaign.id)], self.now)

        assert result.skipped == 1
        campaign.refresh_from_db()
        assert campaign.status == ProductPushCampaign.Status.SKIPPED
        assert campaign.ended_at == self.now
        assert mock_capture.call_args.kwargs["event"] == "product push campaign skipped"

    def test_intent_created_during_campaign_adopts_product_without_activation_criterion(self) -> None:
        campaign = self._active_campaign("web_analytics")
        ProductIntent.objects.create(team=self.team, product_type="web_analytics")

        result = evaluate_and_close_campaign_batch([str(campaign.id)], self.now)

        assert result.adopted == 1
        campaign.refresh_from_db()
        assert campaign.metadata["adoption_signal"] == "intent_created"

    def test_sweep_rechecks_stale_intents_so_quiet_activation_is_detected(self) -> None:
        campaign = self._active_campaign("product_analytics")
        ProductIntent.objects.create(team=self.team, product_type="product_analytics")

        def fake_check(intent: ProductIntent, skip_reporting: bool = False) -> bool:
            intent.activated_at = timezone.now()
            intent.save()
            return True

        with patch.object(ProductIntent, "check_and_update_activation", autospec=True, side_effect=fake_check):
            result = evaluate_and_close_campaign_batch([str(campaign.id)], self.now)

        assert result.adopted == 1
        campaign.refresh_from_db()
        assert campaign.status == ProductPushCampaign.Status.ADOPTED

    # --- eligibility query ----------------------------------------------------

    def test_eligible_organization_queryset_applies_grace_cooldown_and_pin_rules(self) -> None:
        young = Organization.objects.create(name="young")
        self._age_organization(young, days=5)

        with_active = Organization.objects.create(name="active")
        self._age_organization(with_active, days=40)
        ProductPushCampaign.objects.create(
            organization=with_active,
            product_key="surveys",
            status=ProductPushCampaign.Status.ACTIVE,
            started_at=self.now,
        )

        cooling = Organization.objects.create(name="cooling")
        self._age_organization(cooling, days=40)
        ProductPushCampaign.objects.create(
            organization=cooling,
            product_key="surveys",
            status=ProductPushCampaign.Status.SKIPPED,
            ended_at=self.now - timedelta(days=2),
        )

        cooling_with_pin = Organization.objects.create(name="cooling-with-pin")
        self._age_organization(cooling_with_pin, days=40)
        ProductPushCampaign.objects.create(
            organization=cooling_with_pin,
            product_key="surveys",
            status=ProductPushCampaign.Status.SKIPPED,
            ended_at=self.now - timedelta(days=2),
        )
        ProductPushCampaign.objects.create(
            organization=cooling_with_pin,
            product_key="error_tracking",
            status=ProductPushCampaign.Status.SCHEDULED,
            scheduled_for=self.now.date(),
        )

        internal = Organization.objects.create(name="internal", for_internal_metrics=True)
        self._age_organization(internal, days=40)

        eligible_ids = set(get_eligible_organization_queryset(self.now).values_list("id", flat=True))

        assert self.organization.id in eligible_ids
        assert cooling_with_pin.id in eligible_ids
        assert young.id not in eligible_ids
        assert with_active.id not in eligible_ids
        assert cooling.id not in eligible_ids
        assert internal.id not in eligible_ids

    # --- cancelling -----------------------------------------------------------

    def test_cancel_only_touches_scheduled_and_active_rows(self) -> None:
        active = self._active_campaign("product_analytics")
        scheduled = ProductPushCampaign.objects.create(
            organization=self.organization, product_key="surveys", status=ProductPushCampaign.Status.SCHEDULED
        )
        adopted = ProductPushCampaign.objects.create(
            organization=self.organization,
            product_key="web_analytics",
            status=ProductPushCampaign.Status.ADOPTED,
            ended_at=self.now - timedelta(days=1),
        )

        cancelled_count = cancel_campaigns([str(active.id), str(scheduled.id), str(adopted.id)], self.now)

        assert cancelled_count == 2
        active.refresh_from_db()
        scheduled.refresh_from_db()
        adopted.refresh_from_db()
        assert active.status == ProductPushCampaign.Status.CANCELLED
        assert active.ended_at == self.now
        assert scheduled.status == ProductPushCampaign.Status.CANCELLED
        assert adopted.status == ProductPushCampaign.Status.ADOPTED
