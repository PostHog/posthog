from datetime import UTC, datetime, timedelta

from prometheus_client import Counter

from posthog import redis

_REDIS_KEY_PREFIX = "web_analytics_shape_reads"
HISTORY_DAYS = 7
_TTL = timedelta(days=HISTORY_DAYS + 1)
_RECORD_TIMEOUT_SECONDS = 0.25
MAX_SHAPE_HOURS_PER_TEAM_DAY = 10_000

_ADD_UNDER_CAP = """
if redis.call('SISMEMBER', KEYS[1], ARGV[1]) == 1 or redis.call('SCARD', KEYS[1]) < tonumber(ARGV[2]) then
    redis.call('SADD', KEYS[1], ARGV[1])
    redis.call('EXPIRE', KEYS[1], ARGV[3])
    return 1
end
return 0
"""

SHAPE_READS_OVER_CAP_COUNTER = Counter(
    "posthog_web_analytics_shape_reads_over_cap_total",
    "Shape reads not recorded because the team's history for that day reached its size cap",
)


def _hour_start(at: datetime) -> datetime:
    return at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _redis_key(team_id: int, day: datetime) -> str:
    return f"{_REDIS_KEY_PREFIX}:{team_id}:{day.astimezone(UTC):%Y%m%d}"


def record_shape_read(*, team_id: int, shape_key: str, at: datetime) -> None:
    hour = _hour_start(at)
    client = redis.get_client(socket_timeout=_RECORD_TIMEOUT_SECONDS, socket_connect_timeout=_RECORD_TIMEOUT_SECONDS)
    added = client.eval(
        _ADD_UNDER_CAP,
        1,
        _redis_key(team_id, hour),
        f"{shape_key}:{hour.hour:02d}",
        MAX_SHAPE_HOURS_PER_TEAM_DAY,
        int(_TTL.total_seconds()),
    )
    if not added:
        SHAPE_READS_OVER_CAP_COUNTER.inc()


def shape_read_hours(*, team_id: int, now: datetime, hours: int = HISTORY_DAYS * 24) -> dict[str, list[datetime]]:
    newest_hour = _hour_start(now)
    oldest_hour = newest_hour - timedelta(hours=hours - 1)
    days = [
        oldest_hour.replace(hour=0) + timedelta(days=offset)
        for offset in range((newest_hour - oldest_hour.replace(hour=0)).days + 1)
    ]
    pipeline = redis.get_client().pipeline(transaction=False)
    for day in days:
        pipeline.smembers(_redis_key(team_id, day))
    read_hours: dict[str, list[datetime]] = {}
    for day, members in zip(days, pipeline.execute()):
        for member in members:
            shape_key, _, hour_of_day = (
                member.decode("utf-8") if isinstance(member, bytes) else str(member)
            ).rpartition(":")
            hour = day.replace(hour=int(hour_of_day))
            if oldest_hour <= hour <= newest_hour:
                read_hours.setdefault(shape_key, []).append(hour)
    for shape_hours in read_hours.values():
        shape_hours.sort(reverse=True)
    return read_hours
