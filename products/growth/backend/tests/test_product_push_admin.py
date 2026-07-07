from typing import Any

from posthog.test.base import BaseTest

from django.contrib.admin import AdminSite
from django.test import RequestFactory
from django.urls import reverse

from posthog.models.organization import Organization

from products.growth.backend.admin import ProductPushCampaignAdmin, ProductPushCampaignInline
from products.growth.backend.models import ProductPushCampaign


class TestProductPushCampaignAdmin(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.admin = ProductPushCampaignAdmin(ProductPushCampaign, AdminSite())
        self.request_factory = RequestFactory()

    def _request(self) -> Any:
        request = self.request_factory.get("/admin/growth/productpushcampaign/")
        request.user = self.user
        return request

    def test_organization_page_renders_schedule_inline_with_next_up_preview(self) -> None:
        ProductPushCampaign.objects.create(
            organization=self.organization, product_key="surveys", status=ProductPushCampaign.Status.SCHEDULED
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("admin:posthog_organization_change", args=[self.organization.pk]))

        assert response.status_code == 200
        assert "Next auto pick: surveys" in response.content.decode()

    def test_campaign_changelist_renders(self) -> None:
        ProductPushCampaign.objects.create(
            organization=self.organization, product_key="surveys", status=ProductPushCampaign.Status.ACTIVE
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("admin:growth_productpushcampaign_changelist"))

        assert response.status_code == 200

    def test_changelist_edits_are_rejected_once_a_campaign_left_the_queue(self) -> None:
        skipped = ProductPushCampaign.objects.create(
            organization=self.organization, product_key="surveys", status=ProductPushCampaign.Status.SKIPPED
        )
        scheduled = ProductPushCampaign.objects.create(
            organization=self.organization, product_key="error_tracking", status=ProductPushCampaign.Status.SCHEDULED
        )
        # The changelist edits rows through the formset's field-limited form.
        form_class = self.admin.get_changelist_formset(self._request()).form

        skipped_form = form_class(instance=skipped, data={"position": "5", "scheduled_for": ""})
        assert not skipped_form.is_valid()
        assert "cancel action" in str(skipped_form.errors)

        scheduled_form = form_class(instance=scheduled, data={"position": "5", "scheduled_for": ""})
        assert scheduled_form.is_valid(), scheduled_form.errors

    def test_reason_text_stays_editable_on_a_started_campaign(self) -> None:
        active = ProductPushCampaign.objects.create(
            organization=self.organization, product_key="surveys", status=ProductPushCampaign.Status.ACTIVE
        )
        request = self._request()
        form_class = self.admin.get_form(request, obj=active, change=True)

        form = form_class(instance=active, data={"reason_text": "Fresh copy for the promo card"})

        assert form.is_valid(), form.errors

    def test_inline_rows_are_attributed_to_the_tam_who_added_them(self) -> None:
        inline = ProductPushCampaignInline(Organization, AdminSite())
        request = self.request_factory.post("/admin/posthog/organization/")
        request.user = self.user
        formset_class = inline.get_formset(request, self.organization)
        prefix = formset_class.get_default_prefix()

        formset = formset_class(
            instance=self.organization,
            data={
                f"{prefix}-TOTAL_FORMS": "1",
                f"{prefix}-INITIAL_FORMS": "0",
                f"{prefix}-MIN_NUM_FORMS": "0",
                f"{prefix}-MAX_NUM_FORMS": "1000",
                f"{prefix}-0-id": "",
                f"{prefix}-0-product_key": "surveys",
                f"{prefix}-0-position": "0",
                f"{prefix}-0-scheduled_for": "",
                f"{prefix}-0-reason_text": "",
            },
        )

        assert formset.is_valid(), formset.errors
        (campaign,) = formset.save()
        assert campaign.status == ProductPushCampaign.Status.SCHEDULED
        assert campaign.source == ProductPushCampaign.Source.TAM
        assert campaign.created_by == self.user
