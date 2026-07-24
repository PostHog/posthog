import re
import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Q
from django.db.models.fields import BLANK_CHOICE_DASH
from django.http import HttpRequest, HttpResponseBadRequest, HttpResponseNotAllowed
from django.http.response import HttpResponseBase
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import path, reverse
from django.utils.html import escape, format_html
from django.utils.safestring import SafeString

import structlog
from openai import OpenAI

from posthog.admin.inline_registry import register_admin_inline
from posthog.api.streaming import streaming_response
from posthog.llm.gateway_client import get_llm_client
from posthog.models.organization import Organization
from posthog.schema_enums import ProductKey

from products.growth.backend.enrichment.labels import (
    UNKNOWN,
    classify_payload,
    recent_latest_fetches_qs,
    signup_domain_for_organization,
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
                help_text="Routed through the internal LLM gateway.",
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
                "{email} is replaced with the signup email domain at runtime. The JSON output "
                "instruction is appended automatically - describe only the judgment."
            )
        if "is_active" in self.fields:
            self.fields["is_active"].help_text = "The version the batch runner computes. One active version per label."


# Bounded so the synchronous admin dry-run stays a short page load, not a batch job.
_DRY_RUN_SAMPLE = 10
_DRY_RUN_MAX_SAMPLE = 100
_DRY_RUN_WORKERS = 5


def _classify_pair(
    config: EnrichmentPromptConfig, pair: tuple[OrganizationEnrichmentFetch, str | None], client: OpenAI
) -> dict[str, Any]:
    fetch, signup_domain = pair
    company = fetch.payload.get("name") or fetch.organization.name
    try:
        verdict = classify_payload(config, fetch.payload, signup_domain, client)
    except Exception as e:
        return {
            "company": company,
            "domain": signup_domain,
            "verdict": "ERROR",
            "confidence": "-",
            "reasoning": str(e)[:200],
        }
    return {
        "company": company,
        "domain": signup_domain,
        "verdict": str(verdict.get(config.name)).lower(),
        "confidence": f"{verdict.get('confidence', 0.0):.2f}",
        "reasoning": verdict.get("reasoning", ""),
    }


def _row_html(row: dict[str, Any]) -> SafeString:
    return format_html(
        '<tr><td>{}</td><td>{}</td><td><span class="verdict verdict-{}">{}</span></td><td>{}</td><td>{}</td></tr>\n',
        row["company"],
        row["domain"] or "-",
        row["verdict"].lower(),
        row["verdict"],
        row["confidence"],
        row["reasoning"],
    )


async def _stream_classifications(
    config: EnrichmentPromptConfig,
    inputs: list[tuple[OrganizationEnrichmentFetch, str | None]],
    client: OpenAI,
    workers: int = _DRY_RUN_WORKERS,
) -> AsyncIterator[dict[str, Any]]:
    """Classify each (fetch, signup_domain) pair concurrently, yielding one verdict as each completes.

    Async generator on purpose: under ASGI, Django fully buffers a sync iterator before
    sending anything, which silently defeats streaming. Shared by the changelist dry-run
    action and the lab run endpoint below.
    """
    loop = asyncio.get_running_loop()
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        tasks = [loop.run_in_executor(pool, _classify_pair, config, pair, client) for pair in inputs]
        for task in asyncio.as_completed(tasks):
            yield await task
    finally:
        pool.shutdown(wait=False)


def _model_choices(current: str = "") -> list[tuple[str, str]]:
    models_list = list(GATEWAY_MODEL_CHOICES)
    if current and current not in models_list:
        models_list.append(current)
    return [(m, m) for m in models_list]


def _input_field_choices(current: list[str] | None = None) -> list[tuple[str, str]]:
    choices = list(HARMONIC_INPUT_FIELD_CHOICES)
    known = {value for value, _ in choices}
    for path_value in current or []:
        if path_value not in known:
            choices.append((path_value, path_value))
    return choices


_LABEL_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _suggest_next_version(version: str) -> str:
    """Bump a trailing -v<int> or v<int> segment; otherwise append -v2."""
    if not version:
        return "v1"
    match = re.match(r"^(.*?)(-?)v(\d+)$", version)
    if match:
        prefix, sep, num = match.groups()
        return f"{prefix}{sep}v{int(num) + 1}"
    return f"{version}-v2"


class EnrichmentLabEditorForm(forms.Form):
    """Prompt/model/input-fields triad shared by the lab run and save endpoints - the same
    trio EnrichmentPromptConfigForm validates, minus the name/version that only save needs.

    Choices extend only from a PERSISTED config's values (a version whose model predates the
    curated list must still load), never from the submitted data - extending from self.data
    would make every submitted value trivially valid and turn the allowlist into a no-op.
    """

    prompt_text = forms.CharField(widget=forms.Textarea)
    model = forms.ChoiceField(choices=[])
    input_fields = forms.MultipleChoiceField(choices=[], required=False)

    def __init__(self, *args: Any, persisted: EnrichmentPromptConfig | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        persisted_model = persisted.model if persisted else ""
        persisted_fields = list(persisted.input_fields) if persisted else []
        self.fields["model"] = forms.ChoiceField(choices=_model_choices(persisted_model))
        self.fields["input_fields"] = forms.MultipleChoiceField(
            choices=_input_field_choices(persisted_fields), required=False
        )


class EnrichmentLabRunForm(EnrichmentLabEditorForm):
    sample = forms.IntegerField(required=False, min_value=1)
    contains = forms.CharField(required=False)

    def clean_sample(self) -> int:
        sample = self.cleaned_data.get("sample") or _DRY_RUN_SAMPLE
        return min(sample, _DRY_RUN_MAX_SAMPLE)


class EnrichmentLabSaveForm(EnrichmentLabEditorForm):
    version = forms.CharField()

    def __init__(self, *args: Any, label: str, **kwargs: Any) -> None:
        self._label = label
        super().__init__(*args, **kwargs)

    def clean_version(self) -> str:
        version = self.cleaned_data["version"]
        if EnrichmentPromptConfig.objects.filter(name=self._label, version=version).exists():
            raise ValidationError(f"Version {version!r} already exists for {self._label}.")
        return version

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        is_new_label = not EnrichmentPromptConfig.objects.filter(name=self._label).exists()
        if is_new_label and not _LABEL_SLUG_RE.match(self._label):
            raise ValidationError(
                f"{self._label!r} is not a valid label slug (lowercase, starts with a letter, "
                "letters/digits/underscore only)."
            )
        return cleaned


@admin.register(EnrichmentPromptConfig)
class EnrichmentPromptConfigAdmin(admin.ModelAdmin):
    form = EnrichmentPromptConfigForm
    list_display = ("name", "version", "model", "is_active", "created_by", "created_at", "lab_link")
    list_filter = ("name", "is_active")
    search_fields = ("name", "version")
    ordering = ("-created_at",)
    show_full_result_count = False
    list_select_related = ("created_by",)
    actions = ("dry_run_selected",)

    def get_urls(self) -> list[Any]:
        # Custom paths come first: <path:object_id>/... from super() would otherwise
        # never let "lab/<label>/..." match first, since object_id also accepts slashes.
        custom_urls = [
            path(
                "lab/<str:label>/save/",
                self.admin_site.admin_view(self.lab_save_view),
                name="growth_enrichmentpromptconfig_lab_save",
            ),
            path(
                "lab/<str:label>/run/",
                self.admin_site.admin_view(self.lab_run_view),
                name="growth_enrichmentpromptconfig_lab_run",
            ),
            path(
                "lab/<str:label>/",
                self.admin_site.admin_view(self.lab_view),
                name="growth_enrichmentpromptconfig_lab",
            ),
        ]
        return custom_urls + super().get_urls()

    @admin.display(description="Lab")
    def lab_link(self, config: EnrichmentPromptConfig) -> SafeString:
        url = reverse("admin:growth_enrichmentpromptconfig_lab", args=[config.name])
        return format_html('<a href="{}">Open lab</a>', url)

    def _select_lab_version(
        self, request: HttpRequest, versions: list[EnrichmentPromptConfig]
    ) -> EnrichmentPromptConfig | None:
        version_id = request.GET.get("version")
        if version_id:
            for version in versions:
                if str(version.pk) == version_id:
                    return version
        active = next((version for version in versions if version.is_active), None)
        if active is not None:
            return active
        return versions[0] if versions else None

    def _lab_context(
        self,
        request: HttpRequest,
        label: str,
        versions: list[EnrichmentPromptConfig],
        selected: EnrichmentPromptConfig | None,
        *,
        prompt_text: str | None = None,
        model: str | None = None,
        input_fields: list[str] | None = None,
        version_input: str | None = None,
        errors: list[str] | None = None,
    ) -> dict[str, Any]:
        prompt_text = prompt_text if prompt_text is not None else (selected.prompt_text if selected else "")
        model = model if model is not None else (selected.model if selected else "")
        input_fields = input_fields if input_fields is not None else (list(selected.input_fields) if selected else [])
        version_input = (
            version_input if version_input is not None else _suggest_next_version(selected.version if selected else "")
        )
        return {
            **self.admin_site.each_context(request),
            "label": label,
            "versions": versions,
            "selected": selected,
            "prompt_text": prompt_text,
            "model": model,
            "input_fields": set(input_fields),
            "model_choices": _model_choices(model),
            "input_field_choices": _input_field_choices(input_fields),
            "version_input": version_input,
            "sample_default": _DRY_RUN_SAMPLE,
            "sample_max": _DRY_RUN_MAX_SAMPLE,
            "errors": errors or [],
            "changelist_url": reverse("admin:growth_enrichmentpromptconfig_changelist"),
        }

    def lab_view(self, request: HttpRequest, label: str) -> HttpResponseBase:
        versions = list(EnrichmentPromptConfig.objects.filter(name=label).order_by("-created_at"))
        selected = self._select_lab_version(request, versions)
        context = self._lab_context(request, label, versions, selected)
        return render(request, "admin/growth/enrichment_lab.html", context)

    def lab_run_view(self, request: HttpRequest, label: str) -> HttpResponseBase:
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        # A legacy model/input-field stays runnable only if some saved version of this
        # label already uses it; otherwise the curated allowlist is the boundary.
        persisted = EnrichmentPromptConfig.objects.filter(name=label, model=request.POST.get("model", "")).first()
        form = EnrichmentLabRunForm(data=request.POST, persisted=persisted)
        if not form.is_valid():
            errors = "; ".join(e for field_errors in form.errors.values() for e in field_errors)
            return HttpResponseBadRequest(escape(errors), content_type="text/plain")

        contains = form.cleaned_data["contains"].strip()
        candidates = recent_latest_fetches_qs()
        if contains:
            candidates = candidates.filter(
                Q(payload__name__icontains=contains) | Q(organization__name__icontains=contains)
            )
        fetches = list(candidates.select_related("organization")[: form.cleaned_data["sample"]])

        # All ORM work happens here on the request thread; workers only make LLM calls.
        inputs = [(fetch, signup_domain_for_organization(fetch.organization)) for fetch in fetches]
        client = get_llm_client(product="growth")

        # Unsaved on purpose: the lab run classifies against whatever is in the editor right
        # now, nothing is persisted, and "lab-draft" never collides with a real version string.
        draft_config = EnrichmentPromptConfig(
            name=label,
            version="lab-draft",
            prompt_text=form.cleaned_data["prompt_text"],
            model=form.cleaned_data["model"],
            input_fields=form.cleaned_data["input_fields"],
        )

        # Stream only row fragments plus a marked summary row - the page shell is already
        # loaded, unlike the changelist action which streams a full page.
        async def _stream() -> AsyncIterator[str]:
            unknown = errors = 0
            if not inputs:
                yield '<tr><td colspan="5">No archived orgs matched.</td></tr>'
            else:
                async for row in _stream_classifications(draft_config, inputs, client):
                    unknown += row["verdict"] == UNKNOWN
                    errors += row["verdict"] == "ERROR"
                    yield _row_html(row)
            summary = f"classified {len(inputs) - unknown - errors}, unknown {unknown}, errors {errors}"
            yield format_html('<tr data-lab-summary="1"><td colspan="5">{}</td></tr>', summary)

        # No ORM work happens inside the stream (inputs are prefetched above), so the
        # request-thread connections can be released before streaming starts.
        return streaming_response(_stream(), content_type="text/html; charset=utf-8")

    def lab_save_view(self, request: HttpRequest, label: str) -> HttpResponseBase:
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        persisted = EnrichmentPromptConfig.objects.filter(name=label, model=request.POST.get("model", "")).first()
        form = EnrichmentLabSaveForm(data=request.POST, label=label, persisted=persisted)
        versions = list(EnrichmentPromptConfig.objects.filter(name=label).order_by("-created_at"))
        if not form.is_valid():
            errors = [e for field_errors in form.errors.values() for e in field_errors]
            selected = self._select_lab_version(request, versions)
            context = self._lab_context(
                request,
                label,
                versions,
                selected,
                prompt_text=request.POST.get("prompt_text", ""),
                model=request.POST.get("model", ""),
                input_fields=request.POST.getlist("input_fields"),
                version_input=request.POST.get("version", ""),
                errors=errors,
            )
            return render(request, "admin/growth/enrichment_lab.html", context)

        try:
            config = EnrichmentPromptConfig.objects.create(
                name=label,
                version=form.cleaned_data["version"],
                prompt_text=form.cleaned_data["prompt_text"],
                model=form.cleaned_data["model"],
                input_fields=form.cleaned_data["input_fields"],
                is_active=False,
                created_by=request.user if request.user.is_authenticated else None,
            )
        except IntegrityError:
            # clean_version() is check-then-act; two concurrent saves of the same version
            # race past it and the unique constraint decides - surface the loser cleanly.
            selected = self._select_lab_version(request, versions)
            context = self._lab_context(
                request,
                label,
                versions,
                selected,
                prompt_text=request.POST.get("prompt_text", ""),
                model=request.POST.get("model", ""),
                input_fields=request.POST.getlist("input_fields"),
                version_input=request.POST.get("version", ""),
                errors=[f"Version {form.cleaned_data['version']!r} already exists for {label}."],
            )
            return render(request, "admin/growth/enrichment_lab.html", context)
        messages.success(request, f"Saved {label} {config.version}.")
        lab_url = reverse("admin:growth_enrichmentpromptconfig_lab", args=[label])
        return redirect(f"{lab_url}?version={config.pk}")

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
        inputs = [(fetch, signup_domain_for_organization(fetch.organization)) for fetch in fetches]
        client = get_llm_client(product="growth")

        # Stream the results page: shell first, then one row per verdict as each LLM call
        # completes, then the summary — a 100-org run shows progress instead of a blank wait.
        shell = render_to_string(
            "admin/growth/enrichment_dry_run.html",
            {"config": config, "total": len(inputs), "contains": contains},
            request=request,
        )
        head, rest = shell.split("<!--ROWS-->")
        mid, tail = rest.split("<!--SUMMARY-->")

        async def _stream() -> AsyncIterator[str]:
            yield head
            unknown = errors = 0
            if not inputs:
                yield '<tr><td colspan="5">No archived orgs matched.</td></tr>'
            else:
                async for row in _stream_classifications(config, inputs, client):
                    unknown += row["verdict"] == UNKNOWN
                    errors += row["verdict"] == "ERROR"
                    yield _row_html(row)
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
        return str(result.output.get(result.label_name, "?"))
