import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, Optional, cast

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from dateutil.rrule import DAILY, FR, MO, MONTHLY, SA, SU, TH, TU, WE, WEEKLY, YEARLY, rrule

from posthog.constants import AvailableFeature
from posthog.exceptions_capture import capture_exception
from posthog.jwt import PosthogJwtAudience, decode_jwt, encode_jwt
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.utils import UUIDModel
from posthog.utils import absolute_uri

if TYPE_CHECKING:
    from posthog.event_usage import AnalyticsProps
    from posthog.models.organization import Organization

    # Resolved lazily via __getattr__ below; declared here so consumers type-check as int.
    SUBSCRIPTION_COUNT_ALLOWED_ON_FREE_TIER: int

UNSUBSCRIBE_TOKEN_EXP_DAYS = 30

# Carries request-derived analytics props (source, referer, ...) into the post_save signal,
# which has no request context. Set by the API layer around request-originated saves so the
# canonical "<kind> subscription created/updated" events get source attribution; stays None
# for system saves (Temporal, management commands), which then report without a source.
subscription_request_analytics_props: ContextVar[Optional["AnalyticsProps"]] = ContextVar(
    "subscription_request_analytics_props", default=None
)


@contextmanager
def attribute_subscription_saves(analytics_props: "AnalyticsProps") -> Iterator[None]:
    token = subscription_request_analytics_props.set(analytics_props)
    try:
        yield
    finally:
        subscription_request_analytics_props.reset(token)


# Single source of truth shared with the frontend create gate via generated schema
# (SubscriptionFreeTierLimit.COUNT). Resolved lazily via PEP 562 so posthog.schema (the
# pydantic models) stays off django.setup(), where this model loads in every process.
def __getattr__(name: str) -> int:
    if name == "SUBSCRIPTION_COUNT_ALLOWED_ON_FREE_TIER":
        from posthog.schema import SubscriptionFreeTierLimit  # noqa: PLC0415

        value = SubscriptionFreeTierLimit.model_fields["root"].default
        # Cache as a real module attribute: later reads skip __getattr__, and tests
        # patching the attribute keep working since mock restores what getattr returns.
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _free_tier_subscription_limit() -> int:
    # Module-attribute lookup (not a direct global read) so tests patching
    # SUBSCRIPTION_COUNT_ALLOWED_ON_FREE_TIER on this module still take effect.
    return sys.modules[__name__].SUBSCRIPTION_COUNT_ALLOWED_ON_FREE_TIER


# Max length of the prompt snippet used as an AI subscription's display name when it has no title.
AI_PROMPT_DISPLAY_MAX_LEN = 60

RRULE_WEEKDAY_MAP = {
    "monday": MO,
    "tuesday": TU,
    "wednesday": WE,
    "thursday": TH,
    "friday": FR,
    "saturday": SA,
    "sunday": SU,
}

WEEKDAY_SET = {"monday", "tuesday", "wednesday", "thursday", "friday"}


@dataclass
class SubscriptionResourceInfo:
    kind: str
    name: str
    url: str


class Subscription(ModelActivityMixin, models.Model):
    """
    Rather than re-invent the wheel, we are roughly following the iCalender format for recurring schedules
    https://dateutil.readthedocs.io/en/stable/rrule.html

    Also see https://jakubroztocil.github.io/rrule/ for a helpful visual demonstration
    """

    class SubscriptionTarget(models.TextChoices):
        EMAIL = "email"
        SLACK = "slack"

    class SubscriptionFrequency(models.TextChoices):
        DAILY = "daily"
        WEEKLY = "weekly"
        MONTHLY = "monthly"
        YEARLY = "yearly"

    class SubscriptionByWeekDay(models.TextChoices):
        MONDAY = "monday"
        TUESDAY = "tuesday"
        WEDNESDAY = "wednesday"
        THURSDAY = "thursday"
        FRIDAY = "friday"
        SATURDAY = "saturday"
        SUNDAY = "sunday"

    class ResourceType(models.TextChoices):
        INSIGHT = "insight"
        DASHBOARD = "dashboard"
        AI_PROMPT = "ai_prompt", "AI prompt"
        PULSE_BRIEF = "pulse_brief", "Pulse brief"

    RRULE_FIELDS = {"frequency", "count", "interval", "start_date", "until_date", "bysetpos", "byweekday"}

    _FREQ_MAP: dict[str, int] = {
        SubscriptionFrequency.DAILY: DAILY,
        SubscriptionFrequency.WEEKLY: WEEKLY,
        SubscriptionFrequency.MONTHLY: MONTHLY,
        SubscriptionFrequency.YEARLY: YEARLY,
    }

    # Look-back window (in days) a generated report (AI report, Pulse brief) should cover
    # for each cadence. Unknown frequencies fall back to the weekly window.
    _REPORT_WINDOW_DAYS: dict[str, int] = {
        SubscriptionFrequency.DAILY: 1,
        SubscriptionFrequency.WEEKLY: 7,
        SubscriptionFrequency.MONTHLY: 30,
        SubscriptionFrequency.YEARLY: 365,
    }
    DEFAULT_REPORT_WINDOW_DAYS = 7

    # Relations - i.e. WHAT are we exporting?
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    dashboard = models.ForeignKey("dashboards.Dashboard", on_delete=models.CASCADE, null=True)
    insight = models.ForeignKey("product_analytics.Insight", on_delete=models.CASCADE, null=True)
    dashboard_export_insights = models.ManyToManyField(
        "product_analytics.Insight",
        blank=True,
        related_name="subscriptions_dashboard_export",
    )
    integration = models.ForeignKey(
        "posthog.Integration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=False,
    )

    prompt = models.TextField(null=True, blank=True)

    # Plain UUID (not an FK) referencing products.pulse.BriefConfig: decouples exports from
    # pulse at the schema/migration level (no cross-app FK or migration dependency). Code-level
    # coupling is deliberate and collected in the pulse_subscription/ delivery adapter and the
    # ee subscription serializer, which enforce existence/ownership and re-check at delivery.
    pulse_brief_config_id = models.UUIDField(null=True, blank=True)

    # Subscription type (email, slack etc.)
    title = models.CharField(max_length=100, null=True, blank=True)
    target_type = models.CharField(max_length=10, choices=SubscriptionTarget)
    target_value = models.TextField()

    # Subscription delivery (related to rrule)
    frequency = models.CharField(max_length=10, choices=SubscriptionFrequency)
    interval = models.IntegerField(default=1)
    count = models.IntegerField(null=True)
    byweekday: ArrayField = ArrayField(
        models.CharField(max_length=10, choices=SubscriptionByWeekDay),
        null=True,
        blank=True,
        default=None,
    )
    bysetpos = models.IntegerField(null=True)
    start_date = models.DateTimeField()
    until_date = models.DateTimeField(null=True, blank=True)

    # Controlled field - next schedule as helper for
    next_delivery_date = models.DateTimeField(null=True, blank=True)

    # Meta
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted = models.BooleanField(default=False)

    # False when paused or auto-disabled because the delivery prerequisite is
    # permanently invalid (e.g. Slack integration disconnected).
    enabled = models.BooleanField(default=True)

    summary_enabled = models.BooleanField(default=False)
    summary_prompt_guide = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["integration"], name="posthog_sub_integration_idx"),
        ]
        db_table = "posthog_subscription"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only cache rrule if all required fields are loaded (not deferred).
        # The rrule property accesses multiple fields (frequency, count, interval, etc).
        # If ANY field is deferred, accessing it triggers refresh_from_db which creates
        # a new instance with OTHER fields deferred, causing infinite recursion.
        if not (self.get_deferred_fields() & self.RRULE_FIELDS):
            self._rrule = self.rrule

    def save(self, *args, **kwargs) -> None:
        # Only if the schedule has changed do we update the next delivery date
        # _rrule may not be set if object was loaded with deferred fields
        if not self.id or str(getattr(self, "_rrule", None)) != str(self.rrule):
            self.set_next_delivery_date()
            if "update_fields" in kwargs:
                kwargs["update_fields"].append("next_delivery_date")
        super().save(*args, **kwargs)

    @classmethod
    def derive_resource_type(
        cls,
        insight_id: int | None,
        dashboard_id: int | None,
        prompt: str | None,
        pulse_brief_config_id: "uuid.UUID | str | None" = None,
    ) -> str:
        # Shared by the `resource_type` property and the scheduler's `.values()` fan-out
        # (which has field dicts, not model instances) so the derivation stays single-source.
        if insight_id:
            return cls.ResourceType.INSIGHT
        if dashboard_id:
            return cls.ResourceType.DASHBOARD
        if prompt:
            return cls.ResourceType.AI_PROMPT
        if pulse_brief_config_id:
            return cls.ResourceType.PULSE_BRIEF
        raise ValueError(
            "Subscription has no insight, dashboard, prompt, or brief config to derive a resource type from"
        )

    @property
    def resource_type(self) -> str:
        return self.derive_resource_type(self.insight_id, self.dashboard_id, self.prompt, self.pulse_brief_config_id)

    @property
    def _has_resource(self) -> bool:
        # Guards url/resource_info from resource_type's raise on a relationless sub.
        return bool(self.insight_id or self.dashboard_id or self.prompt or self.pulse_brief_config_id)

    @staticmethod
    def _build_rrule(
        *,
        frequency: str,
        start_date: Any,
        count: Any = None,
        interval: Any = None,
        until_date: Any = None,
        bysetpos: Any = None,
        byweekday: Any = None,
    ) -> rrule:
        freq = cast(Literal[0, 1, 2, 3, 4, 5, 6], Subscription._FREQ_MAP[frequency])
        return rrule(
            freq=freq,
            count=count,
            interval=interval,
            dtstart=start_date,
            until=until_date,
            bysetpos=bysetpos if byweekday else None,
            byweekday=to_rrule_weekdays(byweekday) if byweekday else None,
        )

    @staticmethod
    def _compute_next_delivery_date(*, from_dt: Optional[datetime] = None, **rrule_fields: Any) -> Optional[datetime]:
        # Buffer of 15 minutes since we might run a bit early — never schedule into the past.
        now = timezone.now() + timedelta(minutes=15)
        return Subscription._build_rrule(**rrule_fields).after(dt=max(from_dt or now, now), inc=False)

    @property
    def rrule(self) -> rrule:
        return self._build_rrule(**{f: getattr(self, f) for f in self.RRULE_FIELDS})

    def set_next_delivery_date(self, from_dt: Optional[datetime] = None) -> None:
        # Authoritative schedule — a client-side preview mirror lives in
        # frontend/src/lib/components/Subscriptions/utils.tsx (getNextDeliveryDate).
        self.next_delivery_date = self._compute_next_delivery_date(
            from_dt=from_dt, **{f: getattr(self, f) for f in self.RRULE_FIELDS}
        )

    @classmethod
    def project_next_delivery_date(
        cls, instance: Optional["Subscription"] = None, **overrides: Any
    ) -> Optional[datetime]:
        """What `next_delivery_date` would be for the rrule defined by `instance` fields
        (when given) layered with `overrides`, without persisting. Returns None on an
        exhausted rrule. Pass `instance` for PATCH validation, omit it for creates."""
        base = {f: getattr(instance, f) for f in cls.RRULE_FIELDS} if instance is not None else {}
        merged = {**base, **{k: v for k, v in overrides.items() if k in cls.RRULE_FIELDS}}
        if "frequency" not in merged or "start_date" not in merged:
            return None  # DRF field validation should reject before we get here.
        return cls._compute_next_delivery_date(**merged)

    @classmethod
    def check_subscription_limit(cls, team_id: int, organization: "Organization") -> str | None:
        """Return an error message if the team has reached its subscription limit, else None."""
        feature = organization.get_available_feature(AvailableFeature.SUBSCRIPTIONS)
        # Soft-deleted subscriptions free their slot.
        existing_count = cls.objects.filter(team_id=team_id, deleted=False).count()

        if feature:
            allowed = feature.get("limit")
            # A None limit means unlimited (paid plans without a numeric cap).
            if allowed is not None and existing_count >= allowed:
                return f"Your team has reached the limit of {allowed} subscriptions on your plan."
        else:
            limit = _free_tier_subscription_limit()
            if existing_count >= limit:
                return f"Your plan is limited to {limit} subscriptions."

        return None

    @property
    def report_window_days(self) -> int:
        """Days of history a generated report for this subscription should cover, derived from its cadence."""
        return self._REPORT_WINDOW_DAYS.get(self.frequency, self.DEFAULT_REPORT_WINDOW_DAYS)

    @property
    def url(self) -> str | None:
        if not self._has_resource:
            return None
        match self.resource_type:
            case self.ResourceType.INSIGHT if self.insight:
                return absolute_uri(f"/insights/{self.insight.short_id}/subscriptions/{self.id}")
            case self.ResourceType.DASHBOARD if self.dashboard:
                return absolute_uri(f"/dashboard/{self.dashboard_id}/subscriptions/{self.id}")
            case self.ResourceType.AI_PROMPT:
                return absolute_uri(f"/project/{self.team_id}/subscriptions/{self.id}")
            case self.ResourceType.PULSE_BRIEF:
                return absolute_uri(f"/project/{self.team_id}/pulse")
        return None

    @property
    def resource_info(self) -> Optional[SubscriptionResourceInfo]:
        if not self._has_resource:
            return None
        match self.resource_type:
            case self.ResourceType.INSIGHT if self.insight:
                return SubscriptionResourceInfo(
                    "Insight",
                    f"{self.insight.name or self.insight.derived_name}",
                    self.insight.url,
                )
            case self.ResourceType.DASHBOARD if self.dashboard:
                return SubscriptionResourceInfo("Dashboard", self.dashboard.name or "Dashboard", self.dashboard.url)
            case self.ResourceType.AI_PROMPT:
                ai_name = self.title or (self.prompt or "").strip()[:AI_PROMPT_DISPLAY_MAX_LEN] or "AI report"
                return SubscriptionResourceInfo("AI", ai_name, self.url or "")
            case self.ResourceType.PULSE_BRIEF:
                return SubscriptionResourceInfo("Pulse", self.title or "Pulse brief", self.url or "")
        return None

    @property
    def display_name(self) -> str:
        info = self.resource_info
        if info is not None:
            return info.name
        return self.title or "Subscription"

    @property
    def summary(self):
        try:
            human_frequency = {
                "daily": "day",
                "weekly": "week",
                "monthly": "month",
                "yearly": "year",
            }[self.frequency]
            if self.interval > 1:
                human_frequency = f"{human_frequency}s"

            summary = f"sent every {str(self.interval) + ' ' if self.interval > 1 else ''}{human_frequency}"

            if self.byweekday and self.bysetpos:
                human_bysetpos = {
                    1: "first",
                    2: "second",
                    3: "third",
                    4: "fourth",
                    -1: "last",
                }[self.bysetpos]
                if len(self.byweekday) == 1:
                    day_label = self.byweekday[0].capitalize()
                elif set(self.byweekday) == WEEKDAY_SET:
                    day_label = "weekday"
                else:
                    day_label = "day"
                summary += f" on the {human_bysetpos} {day_label}"
            return summary
        except KeyError as e:
            capture_exception(e)
            return "sent on a schedule"

    def get_analytics_metadata(self) -> dict[str, Any]:
        """
        Returns serialized information about the object for analytics reporting.
        """
        return {
            "id": self.id,
            "resource_type": self.resource_type,
            "target_type": self.target_type,
            "num_emails_invited": len(self.target_value.split(",")) if self.target_type == "email" else None,
            "frequency": self.frequency,
            "interval": self.interval,
            "byweekday": self.byweekday,
            "bysetpos": self.bysetpos,
            "prompt_length": len(self.prompt or ""),
        }


@receiver(post_save, sender=Subscription, dispatch_uid="hook-subscription-saved")
def subscription_saved(sender, instance, created, raw, using, **kwargs):
    from posthog.event_usage import report_user_action

    # Partial-field saves are internal bookkeeping (e.g. next_delivery_date rescheduling), not a
    # user create/update — a real API save writes the whole row. Skip them so re-enabling or the
    # scheduler doesn't emit a second "<kind> subscription updated" event.
    if kwargs.get("update_fields"):
        return

    if instance.created_by and instance.resource_info:
        event_name: str = f"{instance.resource_info.kind.lower()} subscription {'created' if created else 'updated'}"
        report_user_action(
            instance.created_by,
            event_name,
            instance.get_analytics_metadata(),
            team=instance.team,
            analytics_props=subscription_request_analytics_props.get(),
        )


@mutable_receiver(model_activity_signal, sender=Subscription)
def log_subscription_activity(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    instance = after_update or before_update
    if instance is None:
        return

    changes = changes_between("Subscription", previous=before_update, current=after_update)
    try:
        log_activity(
            organization_id=instance.team.organization_id,
            team_id=instance.team_id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=instance.id,
            scope="Subscription",
            activity=activity,
            detail=Detail(
                name=instance.display_name,
                changes=changes,
            ),
        )
    except Exception as exc:  # never let activity logging break a save
        capture_exception(exc)


def to_rrule_weekdays(weekday: Subscription.SubscriptionByWeekDay):
    return {RRULE_WEEKDAY_MAP.get(x) for x in weekday}


def get_unsubscribe_token(subscription: Subscription, email: str) -> str:
    return encode_jwt(
        {"id": subscription.id, "email": email},
        expiry_delta=timedelta(days=UNSUBSCRIBE_TOKEN_EXP_DAYS),
        audience=PosthogJwtAudience.UNSUBSCRIBE,
    )


class SubscriptionDelivery(UUIDModel):
    class Status(models.TextChoices):
        STARTING = "starting"
        COMPLETED = "completed"
        FAILED = "failed"
        SKIPPED = "skipped"

    subscription = models.ForeignKey("Subscription", on_delete=models.CASCADE, related_name="deliveries")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    # Temporal correlation — workflow_id for debugging, idempotency_key for dedup.
    # idempotency_key is generated via temporalio.workflow.uuid4() which is deterministic
    # across activity retries (replay) but different across workflow retries.
    temporal_workflow_id = models.CharField(max_length=255)
    idempotency_key = models.CharField(max_length=255, unique=True)

    # Trigger context
    trigger_type = models.CharField(max_length=20)
    scheduled_at = models.DateTimeField(null=True)

    # Target snapshot (frozen at delivery time)
    target_type = models.CharField(max_length=10)
    target_value = models.TextField()

    # Content snapshot
    exported_asset_ids: ArrayField = ArrayField(models.IntegerField(), default=list)
    content_snapshot = models.JSONField(default=dict)

    # AI-generated summary sent in the delivery, when summary_enabled is on for the subscription.
    # None when no summary is attached.
    change_summary = models.TextField(null=True, blank=True)

    # Per-recipient delivery results
    recipient_results = models.JSONField(default=list)

    # Overall status and error (null when no error)
    # Shape: {"message": str, "type": str, ...} — extensible for stack traces, codes, etc.
    status = models.CharField(max_length=24, choices=Status, default=Status.STARTING)
    error = models.JSONField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posthog_subscription_delivery"
        indexes = [
            models.Index(fields=["subscription", "-created_at"], name="posthog_subdel_sub_crtd"),
            models.Index(fields=["team", "-created_at"], name="posthog_subdel_team_crtd"),
        ]
        ordering = ["-created_at"]


def unsubscribe_using_token(token: str) -> Subscription:
    info = decode_jwt(token, audience=PosthogJwtAudience.UNSUBSCRIBE)
    subscription = Subscription.objects.get(pk=info["id"])

    emails = subscription.target_value.split(",")

    if info["email"] in emails:
        emails = [email for email in emails if email != info["email"]]

        subscription.target_value = ",".join(emails)

        if not emails:
            subscription.deleted = True

        subscription.save()

    return subscription
