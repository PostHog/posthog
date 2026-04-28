from datetime import timedelta

from django.db import models
from django.utils import timezone

from dateutil.rrule import rrulestr

from posthog.models.utils import UUIDTModel

from products.workflows.backend.utils.rrule_utils import compute_next_occurrences, validate_rrule


class EvaluationReport(UUIDTModel):
    class Frequency(models.TextChoices):
        # Time-based, driven by the `rrule` string (e.g. "FREQ=WEEKLY;BYDAY=MO,FR").
        SCHEDULED = "scheduled"
        # Count-based: fire every N new eval results, subject to cooldown + daily cap.
        EVERY_N = "every_n"

    TRIGGER_THRESHOLD_MIN = 10
    TRIGGER_THRESHOLD_MAX = 10_000
    TRIGGER_THRESHOLD_DEFAULT = 100
    COOLDOWN_MINUTES_MIN = 60
    COOLDOWN_MINUTES_MAX = 60 * 24
    COOLDOWN_MINUTES_DEFAULT = 60
    DAILY_RUN_CAP_DEFAULT = 10

    class Meta:
        ordering = ["-created_at", "id"]
        indexes = [
            models.Index(fields=["team", "-created_at", "id"]),
            models.Index(fields=["next_delivery_date", "enabled", "deleted"]),
        ]

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    evaluation = models.ForeignKey(
        "llm_analytics.Evaluation",
        on_delete=models.CASCADE,
        related_name="reports",
    )

    frequency = models.CharField(max_length=16, choices=Frequency, default=Frequency.EVERY_N)
    # RRULE string (RFC 5545). Empty for count-triggered reports. Must not contain DTSTART
    # (anchor is stored separately in starts_at); enforced by validate_rrule.
    rrule = models.TextField(blank=True, default="")
    starts_at = models.DateTimeField(null=True, blank=True)
    # IANA tz name used to expand the rrule in local time so e.g. "9am" stays
    # at 9am local across DST transitions.
    timezone_name = models.CharField(max_length=64, default="UTC")
    next_delivery_date = models.DateTimeField(null=True, blank=True)

    delivery_targets = models.JSONField(default=list)
    max_sample_size = models.IntegerField(default=200)
    enabled = models.BooleanField(default=True)
    deleted = models.BooleanField(default=False)
    last_delivered_at = models.DateTimeField(null=True, blank=True)

    # Count-based trigger settings (only used when frequency='every_n')
    trigger_threshold = models.IntegerField(
        null=True,
        blank=True,
        default=100,
        help_text="Number of new eval results that triggers a report",
    )
    cooldown_minutes = models.IntegerField(
        default=60,
        help_text="Minimum minutes between count-triggered reports",
    )
    daily_run_cap = models.IntegerField(
        default=10,
        help_text="Maximum count-triggered report runs per calendar day (UTC)",
    )

    # Optional per-report custom guidance appended to the agent's system prompt.
    # Lets users steer focus/scope/section choices without touching the base prompt.
    report_prompt_guidance = models.TextField(blank=True, default="")

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_count_triggered(self) -> bool:
        return self.frequency == self.Frequency.EVERY_N

    @property
    def rrule_object(self):
        if self.is_count_triggered:
            raise ValueError("rrule is not available for count-triggered reports (frequency='every_n').")
        if not self.rrule or not self.starts_at:
            raise ValueError("rrule and starts_at must be set for scheduled reports.")
        # Validated on save via the serializer; rrulestr raises ValueError on malformed input.
        return rrulestr(self.rrule, dtstart=self.starts_at)

    SCHEDULE_FIELDS = ("frequency", "rrule", "starts_at", "timezone_name")

    def set_next_delivery_date(self, from_dt=None):
        if self.is_count_triggered:
            # Count-based reports don't have a time-based schedule.
            # next_delivery_date is unused — the 5-minute poll checks eval counts.
            self.next_delivery_date = None
            return
        if not self.rrule or not self.starts_at:
            raise ValueError("rrule and starts_at must be set for scheduled reports.")
        # Expand in naive local time so "9am Europe/Prague" stays at 9am across DST,
        # then convert back to UTC. `rrulestr(..., dtstart=starts_at).after(...)` on
        # its own ignores timezone_name and would drift after a DST transition.
        now = timezone.now() + timedelta(minutes=15)
        occurrences = compute_next_occurrences(
            self.rrule,
            self.starts_at,
            timezone_str=self.timezone_name or "UTC",
            after=max(from_dt or now, now),
            count=1,
        )
        self.next_delivery_date = occurrences[0] if occurrences else None

    def save(self, *args, **kwargs):
        recalc = not self.id or not self.next_delivery_date
        old = None
        if not recalc and self.id:
            # If any schedule field changed, recompute next_delivery_date so the
            # new cadence takes effect immediately rather than after the stale timestamp.
            try:
                old = type(self).objects.only(*self.SCHEDULE_FIELDS).get(pk=self.pk)
                if any(getattr(old, f) != getattr(self, f) for f in self.SCHEDULE_FIELDS):
                    recalc = True
            except type(self).DoesNotExist:
                recalc = True
        if recalc:
            self.set_next_delivery_date()
            if "update_fields" in kwargs and kwargs["update_fields"] is not None:
                kwargs["update_fields"] = list(kwargs["update_fields"])
                # Persist every schedule field we changed, not just next_delivery_date.
                # Otherwise a caller-supplied update_fields can drop the field whose
                # change triggered the recalc, leaving next_delivery_date inconsistent
                # with the persisted schedule.
                if old is not None:
                    for field in self.SCHEDULE_FIELDS:
                        if getattr(old, field) != getattr(self, field) and field not in kwargs["update_fields"]:
                            kwargs["update_fields"].append(field)
                if "next_delivery_date" not in kwargs["update_fields"]:
                    kwargs["update_fields"].append("next_delivery_date")
        super().save(*args, **kwargs)


def validate_report_rrule(rrule_string: str) -> None:
    """Thin wrapper that re-exports workflows' validator so the API layer can import from this module."""
    validate_rrule(rrule_string)


class EvaluationReportRun(UUIDTModel):
    class DeliveryStatus(models.TextChoices):
        PENDING = "pending"
        DELIVERED = "delivered"
        PARTIAL_FAILURE = "partial_failure"
        FAILED = "failed"

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["report", "-created_at"]),
        ]

    report = models.ForeignKey(
        EvaluationReport,
        on_delete=models.CASCADE,
        related_name="runs",
    )
    content = models.JSONField(default=dict)
    metadata = models.JSONField(default=dict)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    delivery_status = models.CharField(
        max_length=20,
        choices=DeliveryStatus,
        default=DeliveryStatus.PENDING,
    )
    delivery_errors = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
