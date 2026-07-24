import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db.models.fields import BLANK_CHOICE_DASH
from django.http import HttpRequest
from django.http.response import HttpResponseBase
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import escape, format_html
from django.utils.safestring import SafeString

import structlog

from posthog.admin.inline_registry import register_admin_inline
from posthog.api.streaming import streaming_response
from posthog.llm.gateway_client import get_llm_client
from posthog.models.organization import Organization
from posthog.schema_enums import ProductKey

from products.growth.backend.enrichment.labels import (
    UNKNOWN,
    classify_payload,
    recent_latest_fetches_qs,
    signup_email_for_organization,
)
from products.growth.backend.models import (
    EnrichmentLabelResult,
    EnrichmentPromptConfig,
    OrganizationEnrichmentFetch,
    ProductPushCampaign,
)
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


def _config_has_results(config: EnrichmentPromptConfig) -> bool:
    return EnrichmentLabelResult.objects.filter(label_name=config.name, prompt_version=config.version).exists()


# Runtime constraints only (the model keeps plain fields): curated gateway models and the
# archived-Harmonic payload paths worth feeding a prompt. Extend freely; stored rows with
# values outside these lists still render (choices are unioned with the instance's values).
GATEWAY_MODEL_CHOICES = [
    "gpt-5.2",
    "gpt-5.2-pro",
    "gpt-5.1",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4.1",
    "gpt-4.1-mini",
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-haiku-4-5",
]

HARMONIC_INPUT_FIELD_CHOICES = [
    ("name", "Company name"),
    ("description", "Description"),
    ("website.url", "Website URL"),
    ("companyType", "Company type"),
    ("headcount", "Headcount"),
    ("tagsV2", "Tags (tagsV2)"),
    ("funding.fundingStage", "Funding stage"),
    ("funding.fundingTotal", "Total funding"),
    ("funding.lastFundingAt", "Last funding date"),
    ("funding.investors", "Investors"),
    ("location.country", "Country"),
    ("foundingDate.date", "Founding date"),
]


class EnrichmentPromptConfigForm(forms.ModelForm):
    """Label-owner-facing form: dropdowns and checkboxes instead of free text, so a new
    version is a guided copy-and-tweak rather than hand-typed JSON."""

    class Meta:
        model = EnrichmentPromptConfig
        fields = "__all__"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        instance: EnrichmentPromptConfig | None = self.instance if self.instance.pk else None
        if "model" in self.fields:
            models_list = list(GATEWAY_MODEL_CHOICES)
            if instance and instance.model and instance.model not in models_list:
                models_list.append(instance.model)
            self.fields["model"] = forms.ChoiceField(
                choices=[(m, m) for m in models_list],
                help_text="Routed through the internal LLM gateway. gpt-5 models only accept temperature 1.",
            )
        if "input_fields" in self.fields:
            paths = list(HARMONIC_INPUT_FIELD_CHOICES)
            if instance:
                known = {value for value, _ in paths}
                paths += [(p, p) for p in instance.input_fields if p not in known]
            self.fields["input_fields"] = forms.MultipleChoiceField(
                choices=paths,
                widget=forms.CheckboxSelectMultiple,
                required=False,
                label="Input fields",
                help_text="Archived Harmonic payload fields passed to the prompt as the Company data block.",
            )
        if "version" in self.fields:
            self.fields["version"].help_text = (
                "Immutable once the batch runner stores results. Iterating = add a new row "
                "with a new version, e.g. ai-pilled-v2."
            )
        if "prompt_text" in self.fields:
            self.fields["prompt_text"].help_text = (
                "{email} is replaced with the signup email at runtime. The JSON output "
                "instruction is appended automatically - describe only the judgment."
            )
        if "is_active" in self.fields:
            self.fields["is_active"].help_text = "The version the batch runner computes. One active version per label."


# Bounded so the synchronous admin dry-run stays a short page load, not a batch job.
_DRY_RUN_SAMPLE = 10
_DRY_RUN_MAX_SAMPLE = 100
_DRY_RUN_WORKERS = 5


@admin.register(EnrichmentPromptConfig)
class EnrichmentPromptConfigAdmin(admin.ModelAdmin):
    form = EnrichmentPromptConfigForm
    list_display = ("name", "version", "model", "temperature", "is_active", "created_by", "created_at")
    list_filter = ("name", "is_active")
    search_fields = ("name", "version")
    ordering = ("-created_at",)
    show_full_result_count = False
    list_select_related = ("created_by",)
    actions = ("dry_run_selected",)

    @admin.action(description="Dry run on recent archived orgs (persists nothing)")
    def dry_run_selected(self, request: HttpRequest, queryset: Any) -> HttpResponseBase | None:
        config = queryset.first()
        if config is None or queryset.count() != 1:
            self.message_user(request, "Select exactly one config to dry-run.", level=messages.WARNING)
            return None

        # First POST comes from the changelist action; show the options page. The options
        # page posts back with apply=1 (standard admin intermediate-page pattern).
        if "apply" not in request.POST:
            return render(
                request,
                "admin/growth/enrichment_dry_run_form.html",
                {"config": config, "max_sample": _DRY_RUN_MAX_SAMPLE},
            )

        try:
            sample = min(max(int(request.POST.get("sample") or _DRY_RUN_SAMPLE), 1), _DRY_RUN_MAX_SAMPLE)
        except ValueError:
            sample = _DRY_RUN_SAMPLE
        contains = (request.POST.get("contains") or "").strip()

        candidates = recent_latest_fetches_qs()
        if contains:
            candidates = candidates.filter(
                Q(payload__name__icontains=contains) | Q(organization__name__icontains=contains)
            )
        fetches = list(candidates.select_related("organization")[:sample])

        # All ORM work happens here on the request thread; workers only make LLM calls.
        inputs = [(fetch, signup_email_for_organization(fetch.organization)) for fetch in fetches]
        client = get_llm_client(product="growth")

        def _classify(pair: tuple[OrganizationEnrichmentFetch, str | None]) -> dict[str, Any]:
            fetch, email = pair
            company = fetch.payload.get("name") or fetch.organization.name
            try:
                verdict = classify_payload(config, fetch.payload, email, client)
            except Exception as e:
                return {
                    "company": company,
                    "email": email,
                    "verdict": "ERROR",
                    "confidence": "-",
                    "reasoning": str(e)[:200],
                }
            return {
                "company": company,
                "email": email,
                "verdict": str(verdict.get("ai_pilled")).lower(),
                "confidence": f"{verdict.get('confidence', 0.0):.2f}",
                "reasoning": verdict.get("reasoning", ""),
            }

        # Stream the results page: shell first, then one row per verdict as each LLM call
        # completes, then the summary — a 100-org run shows progress instead of a blank wait.
        shell = render_to_string(
            "admin/growth/enrichment_dry_run.html",
            {"config": config, "total": len(inputs), "contains": contains},
            request=request,
        )
        head, rest = shell.split("<!--ROWS-->")
        mid, tail = rest.split("<!--SUMMARY-->")

        def _row_html(row: dict[str, Any]) -> str:
            return format_html(
                "<tr><td>{}</td><td>{}</td>"
                '<td><span class="verdict verdict-{}">{}</span></td>'
                "<td>{}</td><td>{}</td></tr>\n",
                row["company"],
                row["email"] or "-",
                row["verdict"].lower(),
                row["verdict"],
                row["confidence"],
                row["reasoning"],
            )

        # Async iterator on purpose: under ASGI, Django fully buffers a *sync* iterator
        # before sending anything, which silently defeats the streaming.
        async def _stream() -> AsyncIterator[str]:
            yield head
            unknown = errors = 0
            if not inputs:
                yield '<tr><td colspan="5">No archived orgs matched.</td></tr>'
            else:
                loop = asyncio.get_running_loop()
                pool = ThreadPoolExecutor(max_workers=_DRY_RUN_WORKERS)
                try:
                    for task in asyncio.as_completed([loop.run_in_executor(pool, _classify, pair) for pair in inputs]):
                        row = await task
                        unknown += row["verdict"] == UNKNOWN
                        errors += row["verdict"] == "ERROR"
                        yield _row_html(row)
                finally:
                    pool.shutdown(wait=False)
            yield mid
            yield escape(f"classified {len(inputs) - unknown - errors}, unknown {unknown}, errors {errors}")
            yield tail

        # No ORM work happens inside the stream (inputs are prefetched above), so the
        # request-thread connections can be released before streaming starts.
        return streaming_response(_stream(), content_type="text/html; charset=utf-8")

    def get_changeform_initial_data(self, request: HttpRequest) -> dict[str, Any]:
        # A new version is almost always a tweak of the newest one: prefill everything
        # except the version string, which the owner must choose.
        initial: dict[str, Any] = dict(super().get_changeform_initial_data(request))
        latest = EnrichmentPromptConfig.objects.order_by("-created_at").first()
        if latest is not None and "name" not in initial:
            initial.update(
                {
                    "name": latest.name,
                    "prompt_text": latest.prompt_text,
                    "model": latest.model,
                    "temperature": latest.temperature,
                    "input_fields": latest.input_fields,
                }
            )
        return initial

    def get_readonly_fields(self, request: HttpRequest, obj: EnrichmentPromptConfig | None = None) -> tuple[str, ...]:
        readonly: tuple[str, ...] = ("id", "created_by", "created_at")
        # Belt for the model save() guard: render the frozen fields read-only so the label
        # owner sees "make a new version" instead of a save error.
        if obj is not None and _config_has_results(obj):
            readonly = (*readonly, *EnrichmentPromptConfig.FROZEN_FIELDS)
        return readonly

    def has_delete_permission(self, request: HttpRequest, obj: EnrichmentPromptConfig | None = None) -> bool:
        if obj is not None and _config_has_results(obj):
            return False
        return super().has_delete_permission(request, obj)

    def delete_queryset(self, request: HttpRequest, queryset: Any) -> None:
        # Bulk delete uses queryset.delete(), which skips the model's provenance guard —
        # route through instance deletes so it always runs.
        for config in queryset:
            config.delete()

    def save_model(self, request: HttpRequest, obj: EnrichmentPromptConfig, form: Any, change: bool) -> None:
        if not change and request.user.is_authenticated:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(EnrichmentLabelResult)
class EnrichmentLabelResultAdmin(admin.ModelAdmin):
    """Read-only: rows are written only by the batch runner."""

    list_display = ("organization_link", "label_name", "prompt_version", "verdict", "model", "created_at")
    list_filter = ("label_name", "prompt_version")
    search_fields = ("organization__name",)
    ordering = ("-created_at",)
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
        return str(result.output.get("ai_pilled", "?"))
