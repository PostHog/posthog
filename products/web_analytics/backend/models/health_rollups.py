from django.db import models

from posthog.models.scoping.manager import EnvironmentScopedManager


class SessionIdState(models.IntegerChoices):
    NOT_APPLICABLE = 0, "Not applicable"
    VALID = 1, "Valid"
    NOT_UUIDV7 = 2, "Not UUIDv7"
    ABSENT_OR_NOT_UUID = 3, "Absent or not a UUID"


class EventsHealthDaily(models.Model):
    """Web event counts for one environment and one UTC day, split by the flags the web checks read.

    The daily rollup workflow replaces a whole day at a time. `team_id` is the environment id from
    events, and has no foreign key because team deletion removes the rows explicitly.
    """

    pk = models.CompositePrimaryKey(
        "team_id", "day", "event", "has_custom_api_host", "has_scroll_depth", "session_id_state"
    )
    team_id = models.BigIntegerField()
    day = models.DateField()
    event = models.CharField(max_length=32)
    has_custom_api_host = models.BooleanField()
    has_scroll_depth = models.BooleanField()
    session_id_state = models.SmallIntegerField(choices=SessionIdState.choices)
    event_count = models.BigIntegerField()

    objects = EnvironmentScopedManager()

    class Meta:
        db_table = "web_analytics_events_health_daily"
        indexes = [models.Index(fields=["day"], name="wa_events_health_daily_day_idx")]


class HostProxyDaily(models.Model):
    """$pageview and $screen counts per $host and proxy state for one environment and one UTC day."""

    pk = models.CompositePrimaryKey("team_id", "day", "host", "has_custom_api_host")
    team_id = models.BigIntegerField()
    day = models.DateField()
    host = models.CharField(max_length=253)
    has_custom_api_host = models.BooleanField()
    event_count = models.BigIntegerField()

    objects = EnvironmentScopedManager()

    class Meta:
        db_table = "web_analytics_host_proxy_daily"
        indexes = [models.Index(fields=["day"], name="wa_host_proxy_daily_day_idx")]
