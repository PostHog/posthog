from datetime import UTC, datetime
from typing import Any

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.db.models.fields import BLANK_CHOICE_DASH
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString

import structlog

from posthog.admin.inline_registry import register_admin_inline
from posthog.models.organization import Organization
from posthog.schema_enums import ProductKey

from products.growth.backend.enrichment.icp_lists import clear_lists_cache
from products.growth.backend.enrichment.labels import MAX_INPUT_COLUMNS, RESERVED_OUTPUT_FIELD_KEYS, UNKNOWN
from products.growth.backend.models import (
    EnrichmentLabelResult,
    EnrichmentPromptConfig,
    IcpScoringConfig,
    ProductPushCampaign,
)
from products.growth.backend.product_push.selection import select_next_product
from products.growth.backend.product_push.service import cancel_campaigns, get_eligible_organization_queryset

# The classifier's only valid output types (enrichment/labels.py's _OUTPUT_FIELD_COERCERS).
ALLOWED_OUTPUT_FIELD_TYPES = frozenset({"boolean", "number", "string"})

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


def product_key_choices() -> list[tuple[str, str]]:
    """ProductKey values with humanized labels, for the admin dropdowns."""
    return [(key.value, humanize_product_key(key.value)) for key in sorted(ProductKey, key=lambda k: k.value)]


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
                choices=product_key_choices(),
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
        # Without a blank choice the add row's <select> submits the first ProductKey,
        # so every org save inserted a phantom campaign and 500ed once one was queued.
        product_key_field = self.fields["product_key"]
        assert isinstance(product_key_field, forms.ChoiceField)  # built in ProductPushCampaignForm.__init__
        product_key_field.choices = BLANK_CHOICE_DASH + product_key_choices()


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


class EnrichmentLabelNameFilter(admin.SimpleListFilter):
    """Sources choices from the tiny EnrichmentPromptConfig table, not a SELECT DISTINCT
    label_name over the (much larger, ever-growing) EnrichmentLabelResult table."""

    title = "label"
    parameter_name = "label_name"

    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin) -> list[tuple[str, str]]:
        names = EnrichmentPromptConfig.objects.order_by("name").values_list("name", flat=True).distinct()
        return [(name, name) for name in names]

    def queryset(
        self, request: HttpRequest, queryset: QuerySet[EnrichmentLabelResult]
    ) -> QuerySet[EnrichmentLabelResult]:
        value = self.value()
        return queryset.filter(label_name=value) if value else queryset


class EnrichmentPromptVersionFilter(admin.SimpleListFilter):
    """Sources choices from the tiny EnrichmentPromptConfig table; see EnrichmentLabelNameFilter."""

    title = "prompt version"
    parameter_name = "prompt_version"

    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin) -> list[tuple[str, str]]:
        versions = EnrichmentPromptConfig.objects.order_by("version").values_list("version", flat=True).distinct()
        return [(version, version) for version in versions]

    def queryset(
        self, request: HttpRequest, queryset: QuerySet[EnrichmentLabelResult]
    ) -> QuerySet[EnrichmentLabelResult]:
        value = self.value()
        return queryset.filter(prompt_version=value) if value else queryset


@admin.register(EnrichmentLabelResult)
class EnrichmentLabelResultAdmin(admin.ModelAdmin):
    """Read-only: rows are written only by the batch runner."""

    list_display = ("organization_link", "label_name", "prompt_version", "verdict", "model", "created_at")
    list_filter = (EnrichmentLabelNameFilter, EnrichmentPromptVersionFilter)
    # organization_id__exact avoids the join to posthog_organization: construct_search casts the
    # FK id to text for an exact match rather than an ILIKE, which UUID columns don't support.
    search_fields = ("organization_id__exact",)
    # The PK is a time-ordered uuid7, so -id is both "newest first" and served off the primary
    # key index — no separate index or per-page sort needed, unlike -created_at.
    ordering = ("-id",)
    show_full_result_count = False
    list_select_related = ("organization",)
    readonly_fields = (
        "id",
        "organization",
        "fetch",
        "label_name",
        "prompt_version",
        "prompt_hash",
        "model",
        "output",
        "created_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: EnrichmentLabelResult | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: EnrichmentLabelResult | None = None) -> bool:
        return False

    @admin.display(description="Organization", ordering="organization__name")
    def organization_link(self, result: EnrichmentLabelResult) -> SafeString:
        url = reverse("admin:posthog_organization_change", args=[result.organization_id])
        return format_html('<a href="{}">{}</a>', url, result.organization.name)

    @admin.display(description="Verdict")
    def verdict(self, result: EnrichmentLabelResult) -> str:
        # Read out of the stored output rather than looking the config up per row: label_name is
        # a human name, never an output key, and the output's key order follows output_fields.
        for key, value in result.output.items():
            if key not in RESERVED_OUTPUT_FIELD_KEYS and (isinstance(value, bool) or value == UNKNOWN):
                return f"{key}={str(value).lower()}"
        return "?"


class EnrichmentPromptConfigForm(forms.ModelForm):
    class Meta:
        model = EnrichmentPromptConfig
        fields = "__all__"

    def clean_input_fields(self) -> list[str]:
        input_fields = self.cleaned_data.get("input_fields")
        if not isinstance(input_fields, list) or not all(isinstance(field, str) and field for field in input_fields):
            raise ValidationError("input_fields must be a list of non-empty strings.")
        if len(input_fields) > MAX_INPUT_COLUMNS:
            raise ValidationError(
                f"input_fields has {len(input_fields)} entries; only the first {MAX_INPUT_COLUMNS} reach the prompt."
            )
        return input_fields

    def clean_output_fields(self) -> list[dict[str, Any]]:
        output_fields = self.cleaned_data.get("output_fields")
        if not isinstance(output_fields, list):
            raise ValidationError("output_fields must be a list of objects.")
        for entry in output_fields:
            if not isinstance(entry, dict):
                raise ValidationError(f"output_fields entry {entry!r} must be an object.")
            key = entry.get("key")
            field_type = entry.get("type")
            if not key or not isinstance(key, str):
                raise ValidationError(f"output_fields entry {entry!r} is missing a non-empty 'key'.")
            if key in RESERVED_OUTPUT_FIELD_KEYS:
                raise ValidationError(
                    f"output_fields key {key!r} is reserved for provenance {sorted(RESERVED_OUTPUT_FIELD_KEYS)}."
                )
            if field_type not in ALLOWED_OUTPUT_FIELD_TYPES:
                raise ValidationError(
                    f"output_fields entry {key!r} has type {field_type!r}; must be one of "
                    f"{sorted(ALLOWED_OUTPUT_FIELD_TYPES)}."
                )
            if (entry.get("min") is None) != (entry.get("max") is None):
                raise ValidationError(f"output_fields entry {key!r} must declare both 'min' and 'max', or neither.")
            if entry.get("min") is not None:
                if field_type != "number":
                    raise ValidationError(f"output_fields entry {key!r} has a range but is not a number.")
                try:
                    low, high = float(entry["min"]), float(entry["max"])
                except (TypeError, ValueError):
                    raise ValidationError(f"output_fields entry {key!r} has a non-numeric 'min' or 'max'.")
                if low > high:
                    raise ValidationError(f"output_fields entry {key!r} has 'min' {low} above 'max' {high}.")
        return output_fields


@admin.register(EnrichmentPromptConfig)
class EnrichmentPromptConfigAdmin(admin.ModelAdmin):
    """Where the label owner iterates: a behavior change is a new row, never an in-place edit
    (see the model docstring), so this form validates the output/input contract on the way in
    and locks behavior-defining fields once a config has computed results."""

    form = EnrichmentPromptConfigForm
    list_display = ("name", "version", "is_active", "model", "created_by", "created_at")
    list_filter = ("name", "is_active")
    search_fields = ("name", "version")
    ordering = ("-created_at",)
    show_full_result_count = False

    def get_readonly_fields(self, request: HttpRequest, obj: EnrichmentPromptConfig | None = None) -> tuple[str, ...]:
        # created_by is always readonly (set from request.user in save_model below), which also
        # satisfies this repo's FK-widget rule without needing autocomplete_fields for it.
        readonly: tuple[str, ...] = ("id", "created_by", "created_at")
        if obj is None:
            return readonly
        has_results = EnrichmentLabelResult.objects.filter(label_name=obj.name, prompt_version=obj.version).exists()
        if has_results:
            readonly = (*readonly, "name", "version", "prompt_text", "model", "input_fields", "output_fields")
        return readonly

    def save_model(
        self, request: HttpRequest, obj: EnrichmentPromptConfig, form: forms.ModelForm, change: bool
    ) -> None:
        if not change and request.user.is_authenticated:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(IcpScoringConfig)
class IcpScoringConfigAdmin(admin.ModelAdmin):
    """Versioned curated-list rows for V0.5 ICP scoring. Rows are created by the
    sync_icp_scoring_lists command from the RevOps sheet exports; the admin exists to
    inspect rows and move the active flag (activate here after a non---activate sync).
    A list change is always a new row, so behavior-defining fields lock on save."""

    list_display = ("version", "is_active", "tag_rows", "investor_rows", "created_by", "created_at")
    list_filter = ("is_active",)
    search_fields = ("version",)
    ordering = ("-created_at",)
    show_full_result_count = False

    @admin.display(description="Tag rows")
    def tag_rows(self, obj: IcpScoringConfig) -> int:
        return len(obj.tags) if isinstance(obj.tags, list) else 0

    @admin.display(description="Investors")
    def investor_rows(self, obj: IcpScoringConfig) -> int:
        return len(obj.quality_investors) if isinstance(obj.quality_investors, list) else 0

    def get_readonly_fields(self, request: HttpRequest, obj: IcpScoringConfig | None = None) -> tuple[str, ...]:
        readonly: tuple[str, ...] = ("id", "created_by", "created_at")
        if obj is not None:
            readonly = (*readonly, "version", "tags", "quality_investors")
        return readonly

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: IcpScoringConfig | None = None) -> bool:
        return False

    def save_model(self, request: HttpRequest, obj: IcpScoringConfig, form: forms.ModelForm, change: bool) -> None:
        if not change and request.user.is_authenticated:
            obj.created_by = request.user
        if obj.is_active:
            # Activation moves the flag: the one-active partial unique constraint would
            # otherwise reject the save with an IntegrityError.
            IcpScoringConfig.objects.filter(is_active=True).exclude(pk=obj.pk).update(is_active=False)
        super().save_model(request, obj, form, change)
        clear_lists_cache()
