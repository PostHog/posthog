from datetime import timedelta
from typing import Literal, cast

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

from dateutil.rrule import DAILY, FR, HOURLY, MO, SA, SU, TH, TU, WE, WEEKLY, rrule

from posthog.models.utils import UUIDTModel

RRULE_WEEKDAY_MAP = {
    "monday": MO,
    "tuesday": TU,
    "wednesday": WE,
    "thursday": TH,
    "friday": FR,
    "saturday": SA,
    "sunday": SU,
}


class EvaluationReport(UUIDTModel):
    class Frequency(models.TextChoices):
        HOURLY = "hourly"
        DAILY = "daily"
        WEEKLY = "weekly"

    class ByWeekDay(models.TextChoices):
        MONDAY = "monday"
        TUESDAY = "tuesday"
        WEDNESDAY = "wednesday"
        THURSDAY = "thursday"
        FRIDAY = "friday"
        SATURDAY = "saturday"
        SUNDAY = "sunday"

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

    frequency = models.CharField(max_length=10, choices=Frequency.choices)
    byweekday: ArrayField = ArrayField(
        models.CharField(max_length=10, choices=ByWeekDay.choices),
        null=True,
        blank=True,
        default=None,
    )
    start_date = models.DateTimeField()
    next_delivery_date = models.DateTimeField(null=True, blank=True)

    delivery_targets = models.JSONField(default=list)
    max_sample_size = models.IntegerField(default=200)
    enabled = models.BooleanField(default=True)
    deleted = models.BooleanField(default=False)
    last_delivered_at = models.DateTimeField(null=True, blank=True)

    # Optional per-report custom guidance appended to the agent's system prompt.
    # Lets users steer focus/scope/section choices without touching the base prompt.
    report_prompt_guidance = models.TextField(blank=True, default="")

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def rrule(self):
        freq_map: dict[str, int] = {
            self.Frequency.HOURLY: HOURLY,
            self.Frequency.DAILY: DAILY,
            self.Frequency.WEEKLY: WEEKLY,
        }
        freq = cast(Literal[0, 1, 2, 3, 4, 5, 6], freq_map[self.frequency])
        return rrule(
            freq=freq,
            dtstart=self.start_date,
            byweekday=_to_rrule_weekdays(self.byweekday) if self.byweekday else None,
        )

    SCHEDULE_FIELDS = ("frequency", "byweekday", "start_date")

    def set_next_delivery_date(self, from_dt=None):
        now = timezone.now() + timedelta(minutes=15)
        self.next_delivery_date = self.rrule.after(dt=max(from_dt or now, now), inc=False)

    def save(self, *args, **kwargs):
        recalc = not self.id or not self.next_delivery_date
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
                kwargs["update_fields"].append("next_delivery_date")
        super().save(*args, **kwargs)


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
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
    )
    delivery_errors = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)


def _to_rrule_weekdays(weekdays: list[str]):
    return {RRULE_WEEKDAY_MAP[x] for x in weekdays if x in RRULE_WEEKDAY_MAP}
