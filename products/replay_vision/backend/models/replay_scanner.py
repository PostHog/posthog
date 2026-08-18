import datetime as dt
from typing import TYPE_CHECKING, Any

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import F, Func, JSONField, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from posthog.dataclasses import frozen
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


@frozen
class DeepSweepState:
    """Where the deep catch-up pass has got to.

    `swept_through` plus `seen_session_id` are one keyset: a watermark moved without its tiebreaker
    skips every session tied at that timestamp. `attempted_at` is deliberately not part of it, because
    when the pass last ran and how far it got diverge whenever a pass ends early.
    """

    swept_through: dt.datetime | None = None
    seen_session_id: str = ""
    attempted_at: dt.datetime | None = None

    @classmethod
    def from_json(cls, raw: dict[str, Any] | None) -> "DeepSweepState":
        """Tolerant: this is read on the sweep path, where raising would stop the scanner outright."""
        if not isinstance(raw, dict):
            return cls()
        return cls(
            swept_through=_parse_dt(raw.get("swept_through")),
            seen_session_id=str(raw.get("seen_session_id") or ""),
            attempted_at=_parse_dt(raw.get("attempted_at")),
        )

    @staticmethod
    def patch(**fields: Any) -> Func:
        """Merge just these keys into the stored object, leaving the rest alone.

        The attempt stamp and the progress are written at different points in one tick, so whichever
        goes second must not replace the object and drop what the first wrote. Built as a jsonb `||`
        so the merge happens in the one statement, with no read-modify-write to lose a race in.
        """
        return Func(
            Coalesce(F("deep_sweep_state"), Value({}, JSONField())),
            Value(fields, JSONField()),
            function="",
            arg_joiner=" || ",
            output_field=JSONField(),
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "swept_through": self.swept_through.isoformat() if self.swept_through else None,
            "seen_session_id": self.seen_session_id,
            "attempted_at": self.attempted_at.isoformat() if self.attempted_at else None,
        }


def _parse_dt(value: Any) -> dt.datetime | None:
    """Local rather than shared with the meter's parser: models must not import from `temporal`."""
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


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
    model = models.CharField(max_length=64, choices=ScannerModel.choices)

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
    deep_sweep_state = models.JSONField(
        null=True,
        blank=True,
        help_text="Where the deep catch-up pass has got to: how far it swept, the keyset row it stopped on, and when it last ran. One object because a watermark moved without its keyset skips every session tied at that timestamp.",
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
        "sampling_rate",
        "sampling_mode",
        "provider",
        "model",
        "emits_signals",
    )
    # Fields the persisted volume estimate is computed from; changing them marks the estimate stale.
    _ESTIMATE_FIELDS = frozenset({"query", "sampling_rate", "sampling_mode"})

    @property
    def deep_sweep(self) -> DeepSweepState:
        return DeepSweepState.from_json(self.deep_sweep_state)

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
                    .only(
                        "scanner_version",
                        "enabled",
                        "last_swept_at",
                        "last_seen_session_id",
                        "deep_sweep_state",
                        "sweep_read_bytes_by_hour",
                        "fast_read_bytes_by_hour",
                        "deep_read_bytes_by_hour",
                        "limit_notified_period_start",
                        *relevant,
                    )
                    .first()
                )
                if old is not None:
                    if update_fields is None:
                        # The sweep writes these via targeted updates; a stale full save must not
                        # clobber a concurrent sweep's watermark or notification stamp.
                        self.last_swept_at = old.last_swept_at
                        self.last_seen_session_id = old.last_seen_session_id
                        # Carried too, or a full save from the API drops the deep pass's keyset and
                        # attempt stamp, which is the lost update the jsonb patching exists to avoid.
                        self.deep_sweep_state = old.deep_sweep_state
                        # Same for the metered spend: a PATCH landing mid-metering would restore stale
                        # buckets, and a scanner would run its expensive queries at a lower throttle.
                        self.sweep_read_bytes_by_hour = old.sweep_read_bytes_by_hour
                        self.fast_read_bytes_by_hour = old.fast_read_bytes_by_hour
                        self.deep_read_bytes_by_hour = old.deep_read_bytes_by_hour
                        self.limit_notified_period_start = old.limit_notified_period_start
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
                        self.deep_sweep_state = DeepSweepState(swept_through=self.last_swept_at).as_json()
                        extra_fields.extend(["last_swept_at", "last_seen_session_id", "deep_sweep_state"])
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
