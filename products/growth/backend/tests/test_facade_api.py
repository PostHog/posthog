import datetime as dt

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models.organization import Organization

from products.growth.backend.facade import api
from products.growth.backend.facade.contracts import ProductPushCampaignSummary
from products.growth.backend.models import EnrichmentPromptConfig, ProductPushCampaign


class TestActiveProductPushCampaigns(BaseTest):
    def _campaign(
        self,
        organization: Organization,
        *,
        product_key: str,
        status: str,
        started_ago: dt.timedelta,
        reason_text: str | None = None,
    ) -> None:
        ProductPushCampaign.objects.create(
            organization=organization,
            product_key=product_key,
            status=status,
            started_at=timezone.now() - started_ago,
            reason_text=reason_text,
        )

    def test_returns_only_campaigns_active_and_started_by_the_cutoff(self):
        cutoff = timezone.now() - dt.timedelta(days=1)
        self._campaign(
            self.organization,
            product_key="session_replay",
            status=ProductPushCampaign.Status.ACTIVE,
            started_ago=dt.timedelta(days=3),
            reason_text="Give replay a go",
        )
        self._campaign(
            self.organization,
            product_key="surveys",
            status=ProductPushCampaign.Status.ADOPTED,
            started_ago=dt.timedelta(days=2),
        )
        self._campaign(
            self.organization,
            product_key="error_tracking",
            status=ProductPushCampaign.Status.SCHEDULED,
            started_ago=dt.timedelta(days=2),
        )
        started_late = Organization.objects.create(name="started late")
        self._campaign(
            started_late,
            product_key="session_replay",
            status=ProductPushCampaign.Status.ACTIVE,
            started_ago=dt.timedelta(hours=1),
        )

        assert api.active_product_push_campaigns(self.organization.id, started_before=cutoff) == (
            ProductPushCampaignSummary(product_key="session_replay", reason_text="Give replay a go"),
        )
        assert api.active_product_push_campaigns(started_late.id, started_before=cutoff) == ()


class TestEnsureLabelConfig(BaseTest):
    def _ensure(self, version: str) -> bool:
        return api.ensure_label_config(
            name="test_label",
            version=version,
            prompt_text="... Email: {email}",
            model="gpt-5-mini",
            input_fields=["name"],
            output_fields=[{"key": "is_ai", "type": "boolean", "description": ""}],
        )

    def test_promotes_a_new_config_only_while_no_other_version_is_active(self):
        assert self._ensure("v1") is True
        assert self._ensure("v1") is False
        assert self._ensure("v2") is False

        assert list(
            EnrichmentPromptConfig.objects.filter(name="test_label")
            .order_by("version")
            .values_list("version", "is_active")
        ) == [("v1", True), ("v2", False)]
