import datetime as dt
from typing import TYPE_CHECKING

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone
from django.utils.functional import Promise

from posthog.models.utils import UUIDModel

# This model loads at django.setup() in every process; posthog.schema (the pydantic
# models) is runtime-imported in the accessor that materializes the typed query.
if TYPE_CHECKING:
    from datetime import datetime

    from posthog.schema import RecordingsQuery

# Lives here, not in queries/scanner_candidate_query (which imports SamplingMode from this
# module), so `initial_watermark`'s default callable never needs to import back up into the
# query layer — models must stay a dependency leaf for the query layer, never the reverse.
# 30-min inactivity timeout + 5-min merge-lag buffer.
SETTLE_INTERVAL = dt.timedelta(minutes=35)


def apply_experiment_targeting(query: "RecordingsQuery", targeting: dict | None) -> "RecordingsQuery":
    """Set a recordings query's exposure filter from an `experiment_targeting` blob.

    Shared by the scanner (live query) and the backfill snapshot (frozen copy of the blob), so the
    two derive the exposure filter identically. No targeting *clears* the filter rather than leaving
    it in place: a `query` blob saved before the write-guard (or with targeting later removed) can
    still carry an `experiment_exposure` that nothing access-checks, and the sweep now runs the query
    as the creator — so an untouched blob would run an exposure filter no one authorized.
    """
    from posthog.schema import RecordingsQueryExperimentExposureFilter  # noqa: PLC0415

    exposure = None
    if targeting and targeting.get("experiment_id") is not None:
        exposure = RecordingsQueryExperimentExposureFilter(
            experiment_id=targeting["experiment_id"],
            variant=targeting.get("variant") or None,
        )
    # Shallow copy replacing only the one field: the caller's query is left untouched, and the
    # unrelated nested filters are shared by reference rather than deep-copied since nothing mutates them.
    return query.model_copy(update={"experiment_exposure": exposure})


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
    """Selectable models, cheapest first. Members must mirror `billing.GEMINI_MODELS`; when
    Google supersedes a model, swap the member and remap existing scanners in a migration (see 0052)."""

    GEMINI_3_5_FLASH_LITE = "gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite"
    GEMINI_3_FLASH_PREVIEW = "gemini-3-flash-preview", "Gemini 3 Flash"
    GEMINI_3_7_FLASH = "gemini-3.7-flash", "Gemini 3.7 Flash"


def scanner_model_choices() -> list[tuple[str, str | Promise]]:
    # Callable so growing the enum doesn't generate a no-op migration.
    return list(ScannerModel.choices)


class ScannerOrigin(models.TextChoices):
    """Where a scanner's config came from, and therefore what the row is allowed to do."""

    # Saved by a user: named, editable, listed, and swept on a schedule.
    CONFIGURED = "configured", "Configured"
    # Minted from a config passed inline to a one-off scan (see `inline_scan.py`). Never swept,
    # never listed, not editable, and reaped once it has nothing to show.
    INLINE = "inline", "Inline"


def initial_watermark() -> "datetime":
    """A new scanner's sweep watermark, started one settle-interval back so its first sweep immediately picks up
    recordings that have just cleared the settle window instead of a ~settle-interval cold start; it advances
    forward normally from there, so there's no re-scan."""
    return timezone.now() - SETTLE_INTERVAL


class ReplayScannerManager(models.Manager["ReplayScanner"]):
    """Fail-closed: `objects` is configured-only, so a new call site can't leak inline scanners.

    Anything that presents, counts, edits, or sweeps a team's scanners wants exactly this. Reading
    observations back is the one thing that doesn't; go through `scanner_access` for that rather than
    naming `all_origins` yourself.
    """

    def get_queryset(self) -> "models.QuerySet[ReplayScanner]":
        return super().get_queryset().filter(origin=ScannerOrigin.CONFIGURED)


class ReplayScanner(UUIDModel):
    """A configured probe that gets applied to completed session recordings (see README)."""

    objects = ReplayScannerManager()
    all_origins = models.Manager()

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Human-readable name, unique within the team. Empty for inline scanners, which aren't named.",
    )
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
    model = models.CharField(max_length=64, choices=scanner_model_choices)

    enabled = models.BooleanField(
        default=True,
        help_text="When false, the reconciler removes the scanner's Temporal schedule. On-demand triggers still work.",
    )
    emits_signals = models.BooleanField(default=False)

    origin = models.CharField(
        max_length=16,
        choices=ScannerOrigin.choices,
        default=ScannerOrigin.CONFIGURED,
        db_default=ScannerOrigin.CONFIGURED,
        help_text="Whether a user saved this scanner or an inline scan minted it. See `ScannerOrigin`.",
    )
    inline_key = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_default="",
        help_text="Config fingerprint an inline scan resolves by. Empty for configured scanners.",
    )

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
    deep_swept_through = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Watermark for the full-events-lookback catch-up pass; null until the first regular sweep seeds it.",
    )
    deep_seen_session_id = models.CharField(
        max_length=200,
        blank=True,
        default="",
        db_default="",
        help_text="Keyset tiebreaker paired with deep_swept_through, because a watermark moved without its tiebreaker skips every session tied at that timestamp.",
    )
    deep_attempted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the deep pass last started; its cadence gates on this rather than on progress, so a cut-short pass still waits out its interval.",
    )
    primed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the one-off priming pass over recent recordings ran; null until the first sweep primes the scanner.",
    )
    sweep_read_bytes_by_hour = models.JSONField(
        null=True,
        blank=True,
        help_text="Total ClickHouse read bytes per hour bucket (ISO hour -> bytes) across every pass, maintained by the read-metering workflow. Reporting only: each pass throttles on its own bucket.",
    )
    fast_read_bytes_by_hour = models.JSONField(
        null=True,
        blank=True,
        help_text="ClickHouse read bytes per hour bucket for the frequent sweep's own queries; drives its throttle, so backfill and catch-up reads do not stretch the cadence users see.",
    )
    deep_read_bytes_by_hour = models.JSONField(
        null=True,
        blank=True,
        help_text="ClickHouse read bytes per hour bucket for the deep catch-up pass only; drives its own cadence stretch independently of the frequent sweep.",
    )
    sweep_throttle_factor_override = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Manual cadence-stretch multiplier for the frequent sweep; overrides its computed read-budget throttle. 1 disables throttling; null means automatic. Does not affect the deep catch-up pass, which stretches on its own spend.",
    )

    # Shape: ScannerExperimentTargetingSerializer. Stored because the compiled `query` speaks flag
    # keys, so the experiment association isn't recoverable from it. Not version-tracked; scanning
    # never reads it.
    experiment_targeting = models.JSONField(
        null=True,
        blank=True,
        help_text="The experiment this scanner's targeting watches, if any.",
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

    # Not "monthly": this resets with the org's billing period, which is only a calendar month
    # until billing syncs a real one. See quota.current_period_bounds.
    credit_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Optional cap on this scanner's own credit spend per billing period. Null means no scanner-level cap.",
    )
    limit_notified_period_start = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Billing period start this scanner was last reported as having reached its credit limit. Keeps the notification to one per period.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # FK traversal and cascades must still see inline scanners; only `objects` is fail-closed.
        base_manager_name = "all_origins"
        constraints = [
            # Names are a configured-scanner concept; inline rows have none, and several unnamed
            # rows per team must be allowed to coexist.
            models.UniqueConstraint(
                fields=["team", "name"],
                condition=models.Q(origin=ScannerOrigin.CONFIGURED),
                name="replay_scanner_unique_configured_team_name",
            ),
            # One inline scanner per team per config, so asking the same question twice reuses the
            # observations it already has instead of minting a scanner per request.
            models.UniqueConstraint(
                fields=["team", "inline_key"],
                condition=models.Q(origin=ScannerOrigin.INLINE),
                name="replay_scanner_unique_team_inline_key",
            ),
            # The discriminator and the fingerprint have to agree, or `configured()` and the inline
            # lookup would disagree about the same row.
            models.CheckConstraint(
                condition=(
                    models.Q(origin=ScannerOrigin.CONFIGURED, inline_key="")
                    | (models.Q(origin=ScannerOrigin.INLINE) & ~models.Q(inline_key=""))
                ),
                name="replay_scanner_inline_key_matches_origin",
            ),
            models.CheckConstraint(
                condition=models.Q(sampling_rate__gte=0.0) & models.Q(sampling_rate__lte=1.0),
                name="replay_scanner_sampling_rate_range",
            ),
            # A stray 0 would read as "block every observation" to the quota check, and be
            # indistinguishable from an unset cap. NULL stays valid: it means no scanner-level cap.
            models.CheckConstraint(
                condition=models.Q(credit_limit__isnull=True) | models.Q(credit_limit__gte=1),
                name="replay_scanner_credit_limit_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "enabled"], name="rl_team_enabled_idx"),
            # Serves the reaper's scan for inline scanners that never produced an observation.
            models.Index(
                fields=["created_at"],
                name="rl_inline_created_idx",
                condition=models.Q(origin=ScannerOrigin.INLINE),
            ),
        ]

    _VERSION_TRACKED_FIELDS = (
        "scanner_type",
        "scanner_config",
        "query",
        "experiment_targeting",
        "sampling_rate",
        "sampling_mode",
        "provider",
        "model",
        "emits_signals",
    )
    # Fields the persisted volume estimate is computed from; changing them marks the estimate stale.
    _ESTIMATE_FIELDS = frozenset({"query", "experiment_targeting", "sampling_rate", "sampling_mode"})

    # Written by sweeps and the read meter through queryset updates; a stale full save must not clobber them.
    _MACHINE_OWNED_FIELDS = (
        "last_swept_at",
        "last_seen_session_id",
        "deep_swept_through",
        "deep_seen_session_id",
        "deep_attempted_at",
        "sweep_read_bytes_by_hour",
        "fast_read_bytes_by_hour",
        "deep_read_bytes_by_hour",
        "limit_notified_period_start",
    )

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
                    # By-pk, so it must resolve whatever origin the row is; `objects` would miss inline rows.
                    type(self)
                    .all_origins.select_for_update()
                    .filter(pk=self.pk)
                    .only("scanner_version", "enabled", *self._MACHINE_OWNED_FIELDS, *relevant)
                    .first()
                )
                if old is not None:
                    if update_fields is None:
                        for field in self._MACHINE_OWNED_FIELDS:
                            setattr(self, field, getattr(old, field))
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
                        # The deep pass sweeps from this watermark up to the fast one, so leaving it
                        # behind would make its first window span the whole disabled gap.
                        self.deep_swept_through = self.last_swept_at
                        self.deep_seen_session_id = ""
                        extra_fields.extend(
                            ["last_swept_at", "last_seen_session_id", "deep_swept_through", "deep_seen_session_id"]
                        )
                    if update_fields is not None and extra_fields:
                        kwargs["update_fields"] = [*update_fields, *extra_fields]
                super().save(*args, **kwargs)
            return
        super().save(*args, **kwargs)

    def recordings_query(self) -> "RecordingsQuery":
        """The persisted candidate filter; an empty `query` parses as a bare RecordingsQuery."""
        from posthog.schema import RecordingsQuery  # noqa: PLC0415

        return RecordingsQuery.model_validate(self.query or {"kind": "RecordingsQuery"})

    def targeted_recordings_query(self) -> "RecordingsQuery":
        """The query every scan and estimate must run: the persisted filter plus the exposure
        filter derived from `experiment_targeting`.

        Derived here rather than persisted into `query` so the experiment can only ever enter
        through `experiment_targeting`, the field the API access-checks on write and redacts on
        read. The serializer rejects `experiment_exposure` inside `query` for the same reason.
        """
        return apply_experiment_targeting(self.recordings_query(), self.experiment_targeting)

    def __str__(self) -> str:
        return f"{self.name} ({self.scanner_type})"
