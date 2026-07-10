from datetime import UTC, datetime
from typing import Any

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString

import structlog

from posthog.admin.inline_registry import register_admin_inline
from posthog.models.organization import Organization
from posthog.schema_enums import ProductKey

from products.growth.backend.models import ProductPushCampaign
from products.growth.backend.product_push.selection import select_next_product
from products.growth.backend.product_push.service import cancel_campaigns, get_eligible_organization_queryset

logger = structlog.get_logger(__name__)

# Words that should stay upper-cased when a product key is humanized for the admin dropdown.
_PRODUCT_KEY_ACRONYMS = {"ai", "api", "cdp", "llm", "mcp", "sdk"}


def humanize_product_key(product_key: str) -> str:
    """'llm_clusters' -> 'LLM clusters', 'product_analytics' -> 'Product analytics'."""
    words = product_key.split("_")
    parts = [w.upper() if w in _PRODUCT_KEY_ACRONYMS else w for w in words]
    if parts and parts[0].islower():
        parts[0] = parts[0].capitalize()
    return " ".join(parts)


class ProductPushCampaignForm(forms.ModelForm):
    """TAM-facing form: product_key constrained to ProductKey at runtime (the model
    keeps a plain CharField so the enum can grow without migrations), and rows that
    already started or closed only accept reason_text edits."""

    class Meta:
        model = ProductPushCampaign
        fields = "__all__"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if "product_key" in self.fields:
            self.fields["product_key"] = forms.ChoiceField(
                # Display humanized names but keep the raw ProductKey as the stored value.
                choices=[
                    (key.value, humanize_product_key(key.value)) for key in sorted(ProductKey, key=lambda k: k.value)
                ],
                label="Product",
                help_text="Which product to promote in the org's in-app push card.",
            )
        # The model field names read like internals; give the TAM plainer labels and hints.
        if "position" in self.fields:
            self.fields["position"].label = "Queue position"
            self.fields["position"].help_text = (
                "Order among this org's scheduled campaigns - lower runs sooner (0 is next up). "
                "Leave at 0 to let the daily job pick the order."
            )
        if "reason_text" in self.fields:
            self.fields["reason_text"].label = "Promo copy"
        if "scheduled_for" in self.fields:
            self.fields["scheduled_for"].label = "Start no earlier than"

    def clean(self) -> dict[str, Any] | None:
        cleaned_data = super().clean()
        # self.instance still holds DB values here (_post_clean runs after clean).
        if self.instance.pk and self.instance.status != ProductPushCampaign.Status.SCHEDULED:
            immutable_changes = set(self.changed_data) - {"reason_text"}
            if immutable_changes:
                raise ValidationError(
                    f"Campaign is {self.instance.status}; only the reason text can still be edited "
                    f"(attempted: {', '.join(sorted(immutable_changes))}). Use the cancel action to stop it."
                )
        return cleaned_data


@admin.register(ProductPushCampaign)
class ProductPushCampaignAdmin(admin.ModelAdmin):
    form = ProductPushCampaignForm
    # FK to posthog.Organization — without this the add view renders a <select>
    # of every org on Cloud, which times out.
    autocomplete_fields = ("organization",)
    list_display = (
        "id",
        "organization_link",
        "product_key",
        "status",
        "position",
        "scheduled_for",
        "started_at",
        "ends_at",
        "ended_at",
        "source",
        "created_by",
    )
    list_display_links = ("id",)
    list_editable = ("position", "scheduled_for")
    list_filter = ("status", "source", "product_key")
    search_fields = ("id", "organization__name", "product_key")
    ordering = ("-created_at",)
    show_full_result_count = False
    list_select_related = ("organization", "created_by")
    actions = ("cancel_selected_campaigns",)

    fields = (
        "id",
        "organization",
        "product_key",
        "status",
        "position",
        "scheduled_for",
        "reason_text",
        "started_at",
        "ends_at",
        "ended_at",
        "source",
        "created_by",
        "created_at",
        "updated_at",
    )

    def get_readonly_fields(self, request: HttpRequest, obj: ProductPushCampaign | None = None) -> tuple[str, ...]:
        # Lifecycle fields are only ever written by the campaign service / dag.
        readonly: tuple[str, ...] = (
            "id",
            "status",
            "started_at",
            "ends_at",
            "ended_at",
            "source",
            "created_by",
            "created_at",
            "updated_at",
        )
        if obj is None:
            return readonly
        readonly = (*readonly, "organization")
        if obj.status != ProductPushCampaign.Status.SCHEDULED:
            # Belt: the form's clean() is the braces (it also covers list_editable).
            readonly = (*readonly, "product_key", "position", "scheduled_for")
        return readonly

    def get_fields(self, request: HttpRequest, obj: ProductPushCampaign | None = None) -> Any:
        if obj is None:
            return ("organization", "product_key", "position", "scheduled_for", "reason_text")
        return self.fields

    def get_changelist_form(self, request: HttpRequest, **kwargs: Any) -> Any:
        # list_editable rows must go through the same guard as the change form.
        kwargs.setdefault("form", ProductPushCampaignForm)
        return super().get_changelist_form(request, **kwargs)

    def has_delete_permission(self, request: HttpRequest, obj: ProductPushCampaign | None = None) -> bool:
        # Deleting a SCHEDULED row just removes it from the queue; started/closed
        # rows are the push history and must survive.
        if obj is not None and obj.status != ProductPushCampaign.Status.SCHEDULED:
            return False
        return super().has_delete_permission(request, obj)

    def save_model(self, request: HttpRequest, obj: ProductPushCampaign, form: Any, change: bool) -> None:
        if not change:
            obj.source = ProductPushCampaign.Source.TAM
            if request.user.is_authenticated:
                obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="Cancel selected campaigns (scheduled or active)")
    def cancel_selected_campaigns(self, request: HttpRequest, queryset: Any) -> None:
        cancelled = cancel_campaigns(
            [str(campaign_id) for campaign_id in queryset.values_list("id", flat=True)],
            now=datetime.now(tz=UTC),
        )
        skipped = queryset.count() - cancelled
        message = f"Cancelled {cancelled} campaign(s)."
        if skipped:
            message += f" {skipped} already-closed row(s) were left untouched."
        self.message_user(request, message, level=messages.INFO)

    @admin.display(description="Organization", ordering="organization__name")
    def organization_link(self, campaign: ProductPushCampaign) -> SafeString:
        url = reverse("admin:posthog_organization_change", args=[campaign.organization_id])
        return format_html('<a href="{}">{}</a>', url, campaign.organization.name)


class ProductPushCampaignInlineForm(ProductPushCampaignForm):
    class Meta:
        model = ProductPushCampaign
        exclude = ("organization",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # The extra "add" row must be able to submit an empty product. Without a blank
        # choice its <select> defaults to the first ProductKey, so merely saving the
        # Organization inserts a phantom campaign - and 500s on
        # uniq_pending_product_push_per_org_product once that product is already queued.
        self.fields["product_key"].choices = [("", "---------"), *self.fields["product_key"].choices]


class ProductPushCampaignInline(admin.TabularInline):
    """An organization's push schedule and history on the Organization admin page.

    TAMs steer the queue here: add a row (defaults to scheduled, promoted by the
    daily job), reorder via position, or pin to a date via scheduled_for.
    """

    model = ProductPushCampaign
    form = ProductPushCampaignInlineForm
    extra = 1
    show_change_link = True
    can_delete = False
    template = "admin/growth/edit_inline/campaign_tabular.html"
    ordering = ("status", "position", "-created_at")

    fields = ("product_key", "status", "position", "scheduled_for", "reason_text", "started_at", "ended_at", "source")
    readonly_fields = ("status", "started_at", "ended_at", "source")

    def get_formset(self, request: HttpRequest, obj: Organization | None = None, **kwargs: Any) -> Any:
        formset_class = super().get_formset(request, obj, **kwargs)
        user = request.user

        class CampaignFormSet(formset_class):  # type: ignore[valid-type,misc]
            # Rows added through the inline are saved by OrganizationAdmin's default
            # save_formset (which core owns), so TAM attribution happens here.
            def save_new(self, form: Any, commit: bool = True) -> ProductPushCampaign:
                instance: ProductPushCampaign = super().save_new(form, commit=False)
                instance.source = ProductPushCampaign.Source.TAM
                if instance.created_by_id is None and user.is_authenticated:
                    instance.created_by = user
                if commit:
                    instance.save()
                return instance

        CampaignFormSet.next_up_preview = _next_up_preview(obj) if obj is not None else ""
        return CampaignFormSet


def _next_up_preview(organization: Organization) -> str:
    """One line telling the TAM what the daily job would do for this org next."""
    try:
        now = datetime.now(tz=UTC)
        active = ProductPushCampaign.objects.filter(
            organization=organization, status=ProductPushCampaign.Status.ACTIVE
        ).first()
        if active is not None:
            ends = f", ends {active.ends_at:%Y-%m-%d}" if active.ends_at else ""
            return f"Pushing now: {active.product_key}{ends}."

        selection = select_next_product(organization, now)
        if selection is None:
            return "Next auto pick: nothing — every blessed product is already used, pending, or in retry cooldown."

        origin = "TAM-scheduled" if selection.scheduled_campaign is not None else "blessed order"
        eligible_now = get_eligible_organization_queryset(now).filter(id=organization.id).exists()
        timing = "org is eligible now" if eligible_now else "waiting on signup grace / cooldown"
        return f"Next auto pick: {selection.product_key} ({origin}); {timing}."
    except Exception:
        # The preview is informational — never break the Organization page over it.
        logger.exception("product_push_next_up_preview_failed", organization_id=str(organization.id))
        return ""


# Surface the inline on core's Organization admin page without core importing the
# product. OrganizationAdmin pulls it in via get_inlines() — see posthog.admin.inline_registry.
register_admin_inline(Organization, ProductPushCampaignInline)
