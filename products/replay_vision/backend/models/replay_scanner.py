from typing import TYPE_CHECKING

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone

from posthog.models.utils import UUIDModel

# This model loads at django.setup() in every process; posthog.schema (the pydantic
# models) is runtime-imported in the accessor that materializes the typed query.
if TYPE_CHECKING:
    from datetime import datetime

    from posthog.schema import RecordingsQuery


class ScannerType(models.TextChoices):
    MONITOR = "monitor", "Monitor"
    CLASSIFIER = "classifier", "Classifier"
    SCORER = "scorer", "Scorer"
    SUMMARIZER = "summarizer", "Summarizer"


class SamplingMode(models.TextChoices):
    FOCUSED = "focused", "Focused"
    BALANCED = "balanced", "Balanced"
    COMPREHENSIVE = "comprehensive", "Comprehensive"


class ScannerProvider(models.TextChoices):
    GOOGLE = "google", "Google"


class ScannerModel(models.TextChoices):
    """Priced per observation in `billing.OBSERVATION_CREDITS_BY_MODEL`; new members need a price there."""

    GEMINI_2_5_FLASH = "gemini-2.5-flash", "Gemini 2.5 Flash"
    GEMINI_3_FLASH = "gemini-3-flash-preview", "Gemini 3 Flash"
    GEMINI_3_5_FLASH = "gemini-3.5-flash", "Gemini 3.5 Flash"


def initial_watermark() -> "datetime":
    """A new scanner's sweep watermark, started one settle-interval back so its first sweep immediately picks up
    recordings that have just cleared the settle window instead of a ~settle-interval cold start; it advances
    forward normally from there, so there's no re-scan."""
    from products.replay_vision.backend.queries.scanner_candidate_query import (  # noqa: PLC0415 — keep the heavy hogql query module off the model import path
        SETTLE_INTERVAL,
    )

    return timezone.now() - SETTLE_INTERVAL


class ReplayScanner(UUIDModel):
    """A configured probe that gets applied to completed session recordings (see README)."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=255, help_text="Human-readable name. Unique within the team.")
    description = models.TextField(
        blank=True,
        default="",
        help_text="Free-form description for the scanner management UI. Not used by the model.",
    )

    scanner_type = models.CharField(max_length=32, choices=ScannerType.choices)
    scanner_config = models.JSONField(default=dict, help_text="Type-specific configuration; always includes `prompt`.")
    query = models.JSONField(
        default=dict,
        help_text="Persisted `posthog.schema.RecordingsQuery` shape; date_from/date_to stripped on save.",
    )
    sampling_rate = models.FloatField(
        default=1.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="0..1 random downsample applied after the query matches.",
    )
    sampling_mode = models.CharField(
        max_length=20,
        choices=SamplingMode.choices,
        default=SamplingMode.COMPREHENSIVE,
        help_text="Quality pre-filter applied before random sampling. focused = top sessions by surfacing score, balanced = drops the lowest-quality sessions, comprehensive = no filter.",
    )

    provider = models.CharField(max_length=32, choices=ScannerProvider.choices, default=ScannerProvider.GOOGLE)
    model = models.CharField(max_length=64, choices=ScannerModel.choices)

    enabled = models.BooleanField(
        default=True,
        help_text="When false, the reconciler removes the scanner's Temporal schedule. On-demand triggers still work.",
    )
    emits_signals = models.BooleanField(default=False)

    scanner_version = models.PositiveIntegerField(
        default=1,
        help_text="Increments on every config-changing save. Observations snapshot the version that produced them.",
    )
    last_swept_at = models.DateTimeField(
        default=initial_watermark,
        help_text="Watermark for the scanner schedule's last fire; mirrors Temporal schedule state for recovery.",
    )
    last_seen_session_id = models.CharField(
        max_length=200,
        blank=True,
        default="",
        db_default="",
        help_text="Keyset tiebreaker; set when the last batch saturated so the next sweep resumes past session_end ties.",
    )

    # Shape: feedback_themes.build_feedback_themes. Not version-tracked: themes describe the
    # ratings, not the scanner's behavior.
    feedback_themes = models.JSONField(
        null=True,
        blank=True,
        help_text="AI summary of the team's written thumbs-down feedback into recurring failure modes.",
    )

    estimated_monthly_observations = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Latest projected observations/month for this scanner; enabled scanners are summed org-wide for the quota prognosis.",
    )
    estimated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the estimate was last computed. Refreshed on config saves and by the sweep when stale.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "name"], name="replay_scanner_unique_team_name"),
            models.CheckConstraint(
                condition=models.Q(sampling_rate__gte=0.0) & models.Q(sampling_rate__lte=1.0),
                name="replay_scanner_sampling_rate_range",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "enabled"], name="rl_team_enabled_idx"),
        ]

    _VERSION_TRACKED_FIELDS = (
        "scanner_type",
        "scanner_config",
        "query",
        "sampling_rate",
        "sampling_mode",
        "provider",
        "model",
        "emits_signals",
    )
    # Fields the persisted volume estimate is computed from; changing them marks the estimate stale.
    _ESTIMATE_FIELDS = frozenset({"query", "sampling_rate", "sampling_mode"})

    def save(self, *args, **kwargs) -> None:
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            relevant = [f for f in self._VERSION_TRACKED_FIELDS if f in update_fields]
            track_enabled = "enabled" in update_fields
        else:
            relevant = list(self._VERSION_TRACKED_FIELDS)
            track_enabled = True
        # `_state.adding`, not `self.pk` — UUIDModel assigns the pk in __init__, so pk is truthy even on creates.
        if not self._state.adding and (relevant or track_enabled):
            # SELECT FOR UPDATE so concurrent saves can't both bump scanner_version from the same baseline.
            with transaction.atomic():
                old = (
                    type(self)
                    .objects.select_for_update()
                    .filter(pk=self.pk)
                    .only("scanner_version", "enabled", *relevant)
                    .first()
                )
                if old is not None:
                    changed = {f for f in relevant if getattr(old, f) != getattr(self, f)}
                    extra_fields = []
                    if changed:
                        self.scanner_version = old.scanner_version + 1
                        extra_fields.append("scanner_version")
                    if changed & self._ESTIMATE_FIELDS:
                        self.estimated_at = None
                        extra_fields.append("estimated_at")
                    if track_enabled and not old.enabled and self.enabled:
                        # Re-enabling restarts the sweep from now — don't backfill (and bill) the disabled gap.
                        self.last_swept_at = initial_watermark()
                        self.last_seen_session_id = ""
                        extra_fields.extend(["last_swept_at", "last_seen_session_id"])
                    if update_fields is not None and extra_fields:
                        kwargs["update_fields"] = [*update_fields, *extra_fields]
                super().save(*args, **kwargs)
            return
        super().save(*args, **kwargs)

    def recordings_query(self) -> "RecordingsQuery":
        """The persisted candidate filter; an empty `query` parses as a bare RecordingsQuery."""
        from posthog.schema import RecordingsQuery  # noqa: PLC0415

        return RecordingsQuery.model_validate(self.query or {"kind": "RecordingsQuery"})

    def __str__(self) -> str:
        return f"{self.name} ({self.scanner_type})"
