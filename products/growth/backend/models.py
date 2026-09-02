import json
import hashlib

from django.db import models
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
            # Matches latest_fetches_qs' DISTINCT ON ordering (enrichment/labels.py) so the batch
            # runner's driving query is an index scan instead of a sort of the whole archive.
            models.Index(fields=["organization", "-fetched_at", "-id"], name="growth_enrich_fetch_org_ts_id"),
        ]


class EnrichmentPromptConfig(UUIDModel):
    """A versioned LLM classifier definition for one AI enrichment label.

    Rails are code; brains are rows: the label owner iterates prompt/model/input selection by
    creating new rows, without a deploy. A behavior change is always a new row (new version),
    never an in-place edit. `name` is a human label for this classifier; the output contract is
    output_fields (see enrichment/labels.py). But `EnrichmentLabelResult.label_name` is a
    denormalized copy of `name`, and both the idempotency check and the unique constraint key on
    it — so renaming a label orphans every existing verdict (they keep the old label_name and are
    invisible under the new one), and the runner reclassifies the org from scratch. Renaming
    requires updating history in the same transaction:
    `EnrichmentLabelResult.objects.filter(label_name=old).update(label_name=new)`.
    """

    # Label this config computes, e.g. "ai_pilled".
    name = models.CharField(max_length=128)
    # Human-readable classifier version, e.g. "ai-pilled-clay-v1".
    version = models.CharField(max_length=128)
    prompt_text = models.TextField()
    model = models.CharField(max_length=128)
    # Dotted paths into the archived Harmonic payload fed to the prompt, e.g. ["name", "funding.fundingStage"].
    input_fields = models.JSONField(default=list)
    # The classifier's entire output contract: list of {"key", "type"
    # ("boolean"|"number"|"string"), "description"}. These are the keys the prompt asks for and
    # the only keys a stored verdict carries — see enrichment/labels.py's build_messages /
    # _parse_custom_output. `name` is never one of them.
    output_fields = models.JSONField(default=list)
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

    # Bumped whenever the set of fields below changes. Stored results keep the prefix they were
    # stamped with, so adding a sixth behavior-defining field stays a readable migration rather
    # than silently making every historical prompt_hash unrecomputable.
    CONTENT_HASH_VERSION = "v1"

    @property
    def content_hash(self) -> str:
        """Hash of the behavior-defining fields, stamped onto every result so results stay
        self-describing even if this row is later deleted."""
        content = json.dumps(
            {
                "prompt_text": self.prompt_text,
                "model": self.model,
                "input_fields": self.input_fields,
                "output_fields": self.output_fields,
            },
            sort_keys=True,
        )
        return f"{self.CONTENT_HASH_VERSION}:{hashlib.sha256(content.encode()).hexdigest()}"


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
    # Exactly which archived payload was classified. SET_NULL (not CASCADE): the fetch archive
    # is the natural target for retention pruning (Organization deletion already cascades to it,
    # see OrganizationEnrichmentFetch.organization), and prompt_hash + inputs make a verdict
    # self-describing enough to survive its source fetch being pruned.
    fetch = models.ForeignKey(
        "growth.OrganizationEnrichmentFetch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="label_results",
    )
    label_name = models.CharField(max_length=128)
    prompt_version = models.CharField(max_length=128)
    # EnrichmentPromptConfig.content_hash at compute time, so the result is self-describing
    # even if the config row is deleted.
    prompt_hash = models.CharField(max_length=72)
    model = models.CharField(max_length=128)
    # The config's output_fields keys and their values, e.g. {"ai_pilled": true|false|"unknown",
    # "confidence": float, "reasoning": str}, plus a "meta" provenance key.
    output = models.JSONField(default=dict)
    # The rendered classifier inputs (extracted payload fields + signup domain) at compute
    # time: the domain derives from current org membership and drifts as members leave, so
    # this is the only durable record of what was actually sent to the LLM.
    inputs = models.JSONField(default=dict)
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


class IcpScoringConfig(UUIDModel):
    """A versioned snapshot of the RevOps-curated lists behind the ICP fit score.

    Rails are code; brains are rows (the EnrichmentPromptConfig precedent): the scoring
    formula and weights live in code (the fit scorer, landing separately), but the curated
    tag buckets and quality-investor names it matches against live here, so RevOps'
    quarterly review lands without a deploy — and the internal sheets never get committed
    to this public repo. A list change is always a new row (new version) activated
    explicitly, never an in-place edit; scores stamp the row's version as
    `icp_fit_lists_version`, so a list update is distinguishable from a formula change
    (`icp_fit_version`) in every stored score.

    Rows are written by the `sync_icp_scoring_lists` management command from the RevOps
    sheet exports; see enrichment/icp_lists.py for the row shapes and the loader.
    """

    # Human-readable list version, e.g. "2026-08-13".
    version = models.CharField(max_length=128, unique=True)
    # Tag curation rows: [{"tag", "type", "recommendation", "reason", "note"}]. recommendation
    # is "+"-joined bucket names (ai_positive, capital_quality, software_positive,
    # software_negative, dq, ignore).
    tags = models.JSONField(default=list)
    # Quality investor rows: [{"investor", "aliases": [...], "notes"}].
    quality_investors = models.JSONField(default=list)
    # The row the scorer loads; at most one active row (enforced below).
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
            models.UniqueConstraint(
                fields=["is_active"], condition=Q(is_active=True), name="growth_icp_lists_one_active"
            ),
        ]

    def __str__(self) -> str:
        return f"icp lists {self.version}{' (active)' if self.is_active else ''}"


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
