from django.db import models
from django.db.models import Case, CharField, Expression, F, FloatField, Func, Value, When
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Cast

from posthog.models.utils import UUIDModel

from products.replay_vision.backend.error_kinds import ERROR_REASON_HELP_TEXT


class ObservationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    # Terminal state for sessions the scanner can't analyze (no recording, too short, too long, etc.).
    # The reason kind is stored in `error_reason` formatted as `kind:human message`.
    INELIGIBLE = "ineligible", "Ineligible"


# Not-yet-terminal statuses: what the quota meter reserves and the concurrency caps count as "in flight".
IN_FLIGHT_STATUSES = (ObservationStatus.PENDING, ObservationStatus.RUNNING)

# Everything else, derived so the two stay exhaustive and disjoint when a status is added. These rows are
# sticky, so the (scanner, session) slot they hold is spent: a new scan for the same pair can't be
# started, only retried (which deletes and re-creates the row).
TERMINAL_STATUSES = tuple(status for status in ObservationStatus if status not in IN_FLIGHT_STATUSES)


class ObservationTrigger(models.TextChoices):
    SCHEDULE = "schedule", "Schedule"
    ON_DEMAND = "on_demand", "On demand"
    RETRY = "retry", "Retry"
    BACKFILL = "backfill", "Backfill"


class ReplayObservation(UUIDModel):
    """One application of a `ReplayScanner` to a session recording (see README)."""

    scanner = models.ForeignKey("replay_vision.ReplayScanner", on_delete=models.CASCADE, related_name="observations")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    session_id = models.CharField(max_length=200, help_text="Session recording id this scanner was applied to.")
    distinct_id = models.CharField(
        max_length=400,
        null=True,
        blank=True,
        help_text="Distinct id of the person in the recorded session (the subject), resolved from session metadata.",
    )
    recording_subject_email = models.TextField(
        null=True,
        blank=True,
        help_text="Email of the recording subject at scan time; denormalized so the list can filter and sort on it.",
    )
    session_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Start time of the recorded session; copied from session metadata so downstream steps don't re-query.",
    )
    session_group_keys = models.JSONField(
        null=True,
        blank=True,
        help_text=(
            "Group keys the recorded session's events carry, keyed by group type index (e.g. {'0': 'acme-inc'}). "
            "Resolved at scan time so the emitted event can be attributed to the group without re-querying."
        ),
    )

    status = models.CharField(max_length=16, choices=ObservationStatus.choices, default=ObservationStatus.PENDING)
    error_reason = models.TextField(blank=True, default="", help_text=ERROR_REASON_HELP_TEXT)
    workflow_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Temporal workflow id; used for progress queries and reaper reconciliation.",
    )

    scanner_snapshot = models.JSONField(
        default=dict,
        help_text="Frozen view of the scanner at observation-create time; see `temporal.types.ScannerSnapshot`.",
    )
    scanner_result = models.JSONField(
        default=dict,
        help_text="Result data persisted on success (model output, signals count); see `temporal.types.ScannerResult`.",
    )
    created_task_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="PostHog Task minted from this observation's finding. Repeat create_task calls return this id instead of creating a duplicate.",
    )

    backfill = models.ForeignKey(
        "replay_vision.ReplayScannerBackfill",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="observations",
        # Indexed via the partial rlo_backfill_idx instead of a full-column default index.
        db_index=False,
        help_text="Backfill run that dispatched this observation; null for live, on-demand, and retry triggers.",
    )
    triggered_by = models.CharField(
        max_length=16,
        choices=ObservationTrigger.choices,
        help_text="What started this observation: a per-scanner schedule fire, an explicit /observe/ call, a retry of a failed or ineligible observation, or a historical backfill.",
    )
    triggered_by_user = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Populated for on-demand and retry triggers; null for schedule-driven observations.",
    )

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # Succeeded rows are sticky; admin deletes to re-trigger. A backfill may retake a failed row.
            models.UniqueConstraint(fields=["scanner", "session_id"], name="replay_observation_unique_scanner_session"),
            models.CheckConstraint(
                condition=(
                    models.Q(status__in=["pending", "running"], completed_at__isnull=True)
                    | models.Q(status__in=["succeeded", "failed", "ineligible"], completed_at__isnull=False)
                ),
                name="replay_observation_completed_at_matches_status",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "created_at"], name="rlo_team_created_idx"),
            models.Index(fields=["scanner", "status"], name="rlo_scanner_status_idx"),
            # Serves the alert-engine observation window: succeeded rows per scanner in a
            # completed_at range. Partial: terminal succeeded rows are the only ones scanned.
            models.Index(
                fields=["scanner", "completed_at"],
                name="rlo_scanner_completed_idx",
                condition=models.Q(status="succeeded"),
            ),
            # Serves the per-scanner list ordering and the prev/next-neighbor lookups (both order by created_at).
            models.Index(fields=["scanner", "created_at"], name="rlo_scanner_created_idx"),
            models.Index(
                fields=["workflow_id"],
                name="rlo_workflow_id_idx",
                condition=~models.Q(workflow_id=""),
            ),
            # Serves the per-team in-flight concurrency count (sweep headroom + on-demand 429). Partial on the
            # in-flight statuses only, since terminal rows dominate and are never counted.
            models.Index(
                fields=["team", "scanner"],
                name="rlo_team_in_flight_idx",
                condition=models.Q(status__in=("pending", "running")),
            ),
            # Serves the per-backfill observation filter and progress counts; partial since live rows never match.
            models.Index(
                fields=["backfill"],
                name="rlo_backfill_idx",
                condition=models.Q(backfill__isnull=False),
            ),
        ]

    @classmethod
    def in_flight_for_team(cls, team_id: int) -> "models.QuerySet[ReplayObservation]":
        """A team's not-yet-terminal observations; the one predicate the quota meter and concurrency caps share."""
        return cls.objects.filter(team_id=team_id, status__in=IN_FLIGHT_STATUSES)

    def save(self, *args, **kwargs) -> None:
        # Tenant invariant: observation.team_id must match scanner.team_id.
        if self._state.adding:
            scanner_team_id = self.scanner.team_id
            if self.team_id and self.team_id != scanner_team_id:
                raise ValueError(
                    f"ReplayObservation.team_id ({self.team_id}) must match scanner.team_id ({scanner_team_id})"
                )
            self.team_id = scanner_team_id
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.scanner_id}:{self.session_id} [{self.status}]"


def jsonb_typeof(expr: Expression) -> Func:
    return Func(expr, function="JSONB_TYPEOF", output_field=CharField())


def hydrate_for_serialization(qs: "models.QuerySet[ReplayObservation]") -> "models.QuerySet[ReplayObservation]":
    """Load everything `ReplayObservationSerializer` reads, so no queryset feeding it goes one query per row.

    `scanner_origin` is annotated rather than joined through `select_related("scanner")`: the serializer
    reads one enum, and hydrating the scanner would ship its config and hour-bucket JSON blobs per row.
    """
    return qs.select_related("triggered_by_user", "label").annotate(scanner_origin=F("scanner__origin"))


def annotate_output_number(
    qs: "models.QuerySet[ReplayObservation]", key: str, alias: str
) -> "models.QuerySet[ReplayObservation]":
    """Annotate `alias` with `scanner_result.model_output.<key>` as a float, null when the value isn't numeric.

    CASE-guard the cast so schema drift or a manual fixup (a `score` stored as a string) can't 500 the query.
    """
    type_alias = f"{alias}_type"
    value_jsonb = KeyTransform(key, KeyTransform("model_output", "scanner_result"))
    value_text = KeyTextTransform(key, KeyTextTransform("model_output", "scanner_result"))
    return qs.annotate(
        **{
            type_alias: jsonb_typeof(value_jsonb),
            alias: Case(
                When(**{type_alias: "number"}, then=Cast(value_text, FloatField())),
                default=Value(None),
                output_field=FloatField(),
            ),
        }
    )
