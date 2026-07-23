import json
import hashlib
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q

from posthog.models.utils import UpdatedMetaFields, UUIDModel


class ProductPushCampaign(UUIDModel, UpdatedMetaFields):
    """One product pushed to a whole organization for a bounded window.

    A single table holds the queue (SCHEDULED), the current push (ACTIVE), and the
    history (ADOPTED / SKIPPED / CANCELLED) — promoting a scheduled row to active is
    a status flip, not a row move. Cadence, selection, and transitions live in
    products/growth/backend/product_push/.
    """

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        ACTIVE = "active", "Active"
        ADOPTED = "adopted", "Adopted"
        SKIPPED = "skipped", "Skipped"
        CANCELLED = "cancelled", "Cancelled"

    class Source(models.TextChoices):
        AUTO = "auto", "Auto"
        TAM = "tam", "TAM"

    # No DB constraints on the FKs: posthog_organization and posthog_user are hot
    # tables, and building an FK constraint takes a lock on the referenced parent
    # (see safe-django-migrations.md "Foreign keys to hot tables").
    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="product_push_campaigns",
        db_constraint=False,
    )
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
    )

    # A ProductKey value. Plain CharField (like ProductIntent.product_type) so the
    # enum can grow without a migration; the admin form constrains input at runtime.
    product_key = models.CharField(max_length=255)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SCHEDULED)

    # Ordering among an org's SCHEDULED rows; lower starts sooner.
    position = models.PositiveIntegerField(default=0)

    scheduled_for = models.DateField(
        null=True,
        blank=True,
        help_text="Don't start before this date. Overrides the signup grace period and the between-campaigns "
        "cooldown (an explicit human decision), but never the one-active-campaign-per-org invariant. "
        "Empty = next available slot.",
    )

    started_at = models.DateTimeField(null=True, blank=True)
    # Planned end (started_at + CAMPAIGN_DURATION_DAYS), denormalized so the daily
    # sweep can find expired campaigns with an index scan.
    ends_at = models.DateTimeField(null=True, blank=True)
    # Actual close time (adoption detected, expired, or cancelled).
    ended_at = models.DateTimeField(null=True, blank=True)

    source = models.CharField(max_length=8, choices=Source.choices, default=Source.AUTO)

    reason_text = models.TextField(
        null=True,
        blank=True,
        help_text="Custom copy for the in-app promo card. Empty = default copy.",
    )

    # Outcome details, e.g. {"adoption_signal": "intent_activated", "team_id": 123}.
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Product push campaign"
        verbose_name_plural = "Product push campaigns"
        constraints = [
            models.UniqueConstraint(
                fields=["organization"],
                condition=Q(status="active"),
                name="uniq_active_product_push_per_org",
            ),
            models.UniqueConstraint(
                fields=["organization", "product_key"],
                condition=Q(status__in=["scheduled", "active"]),
                name="uniq_pending_product_push_per_org_product",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status"], name="growth_push_org_status"),
            models.Index(fields=["status", "ends_at"], name="growth_push_status_ends_at"),
            models.Index(fields=["status", "scheduled_for"], name="growth_push_status_sched"),
        ]

    def __str__(self) -> str:
        return f"{self.organization_id} - {self.product_key} ({self.status})"


class OrganizationEnrichment(UUIDModel):
    # db_constraint=False keeps CreateModel off posthog_organization's lock path (hot table)
    organization = models.OneToOneField(
        "posthog.Organization", on_delete=models.CASCADE, db_constraint=False, related_name="enrichment_record"
    )
    # Namespaced deterministic enrichment signals, e.g. company_type_deterministic
    data = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class OrganizationEnrichmentFetch(UUIDModel):
    """Append-only archive of raw provider responses, one row per fetch.

    The signup attempt and any later recheck are separate rows on purpose: provider
    responses are time-varying, so each fetch is a distinct observation kept verbatim —
    including a not-found, which is evidence too.
    """

    # db_constraint=False keeps CreateModel off posthog_organization's lock path (hot table)
    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        db_constraint=False,
        related_name="enrichment_fetches",
    )
    provider = models.CharField(max_length=64)
    fetched_at = models.DateTimeField(auto_now_add=True)
    is_recheck = models.BooleanField(default=False)
    # The provider response verbatim, before any transform into the field registry.
    payload = models.JSONField(default=dict)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "fetched_at"], name="growth_enrich_fetch_org_time"),
        ]


class EnrichmentPromptConfig(UUIDModel):
    """A versioned LLM classifier definition for one enrichment label (the "score lab" brains).

    Rails are code; brains are rows: the label owner iterates prompt/model/input selection by
    creating new rows through Django admin, without a deploy. A version is immutable once any
    EnrichmentLabelResult references it — an in-place edit would silently invalidate every stored
    result stamped with that version, and the idempotent batch runner would never recompute.

    The guard lives in save()/delete(), so queryset update()/bulk_update()/raw SQL bypass it —
    always mutate configs through instances (admin does).
    """

    # Everything that changes the classifier's behavior. An edit to any of these is a new
    # version (new row), never an in-place change — see save().
    FROZEN_FIELDS = ("name", "version", "prompt_text", "model", "temperature", "input_fields")

    # Label this config computes, e.g. "ai_pilled".
    name = models.CharField(max_length=128)
    # Human-readable classifier version, e.g. "ai-pilled-clay-v1".
    version = models.CharField(max_length=128)
    prompt_text = models.TextField()
    model = models.CharField(max_length=128)
    # gpt-5 family models via the gateway only accept temperature=1.
    temperature = models.FloatField(default=1.0)
    # Dotted paths into the archived Harmonic payload fed to the prompt, e.g. ["name", "funding.fundingStage"].
    input_fields = models.JSONField(default=list)
    # The version the batch runner computes; at most one active row per label (enforced below).
    is_active = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["name", "version"], name="growth_prompt_config_name_version"),
            models.UniqueConstraint(
                fields=["name"], condition=Q(is_active=True), name="growth_prompt_config_one_active"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} {self.version}"

    @property
    def content_hash(self) -> str:
        """Hash of the behavior-defining fields, stamped onto every result so results stay
        self-describing even if this row is later deleted."""
        content = json.dumps(
            {
                "prompt_text": self.prompt_text,
                "model": self.model,
                "temperature": self.temperature,
                "input_fields": self.input_fields,
            },
            sort_keys=True,
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def _has_results(self, name: str, version: str) -> bool:
        return EnrichmentLabelResult.objects.filter(label_name=name, prompt_version=version).exists()

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.pk:
            super().save(*args, **kwargs)
            return
        # Row lock pairs with the batch runner, which takes the same lock (and re-checks the
        # content hash) before inserting each result — so edits and result creation serialize
        # and neither side can invalidate the other mid-flight.
        with transaction.atomic():
            persisted = EnrichmentPromptConfig.objects.select_for_update().filter(pk=self.pk).first()
            if persisted is not None and self._has_results(persisted.name, persisted.version):
                changed = [f for f in self.FROZEN_FIELDS if getattr(self, f) != getattr(persisted, f)]
                if changed:
                    raise ValidationError(
                        f"Config {persisted.name} {persisted.version} has stored results; "
                        f"{', '.join(changed)} cannot change. Create a new row with a new version instead."
                    )
            super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        if not self.pk:
            return super().delete(*args, **kwargs)
        with transaction.atomic():
            EnrichmentPromptConfig.objects.select_for_update().filter(pk=self.pk).first()
            if self._has_results(self.name, self.version):
                raise ValidationError(
                    f"Config {self.name} {self.version} has stored results and is part of their provenance; "
                    "deactivate it instead of deleting."
                )
            return super().delete(*args, **kwargs)


class EnrichmentLabelResult(UUIDModel):
    """One classifier verdict for one org under one prompt version, computed from one archived fetch.

    Shadow-only in v0: nothing consumes these rows (no group/person properties, no events);
    they are queryable in Postgres/warehouse only. Keying on the fetch means a re-enriched org
    naturally gets recomputed under the same version instead of being frozen — which matters
    most for `unknown` verdicts from empty payloads, which would otherwise be permanent.
    """

    # db_constraint=False keeps CreateModel off posthog_organization's lock path (hot table)
    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        db_constraint=False,
        related_name="enrichment_label_results",
    )
    # Exactly which archived payload was classified.
    fetch = models.ForeignKey(
        "growth.OrganizationEnrichmentFetch",
        on_delete=models.CASCADE,
        related_name="label_results",
    )
    label_name = models.CharField(max_length=128)
    prompt_version = models.CharField(max_length=128)
    # EnrichmentPromptConfig.content_hash at compute time, so the result is self-describing
    # even if the config row is deleted.
    prompt_hash = models.CharField(max_length=64)
    model = models.CharField(max_length=128)
    # {"ai_pilled": true|false|"unknown", "confidence": float, "reasoning": str}
    output = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "label_name", "prompt_version", "fetch"],
                name="growth_label_result_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["label_name", "prompt_version"], name="growth_label_result_version"),
        ]

    def __str__(self) -> str:
        return f"{self.organization_id} {self.label_name} {self.prompt_version}"


class EnrichmentSignupSnapshot(UUIDModel):
    """Write-once marker that the at-signup enrichment snapshot has been emitted for an org.

    Stores no firmographic values (those live only on the person-scoped snapshot event); this
    row is purely the idempotency guard and provenance timestamp. The OneToOne unique constraint
    lets concurrent runs make at most one row per org.
    """

    # db_constraint=False keeps CreateModel off posthog_organization's lock path (hot table);
    # the OneToOne still gives the write-once uniqueness guarantee.
    organization = models.OneToOneField(
        "posthog.Organization",
        on_delete=models.CASCADE,
        db_constraint=False,
        related_name="enrichment_signup_snapshot",
    )
    created_at = models.DateTimeField(auto_now_add=True)
