import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypedDict, cast
from uuid import uuid4

from django.conf import settings
from django.db.models import Q

from posthoganalytics.request import batch_post

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.redis import get_client, redis

from products.feature_flags.backend.flag_analytics import (
    CACHE_BUCKET_SIZE,
    REDIS_LOCK_TOKEN,
    SDK_LIBRARIES,
    USAGE_EVENT_NAMES,
    get_team_request_key,
    get_team_request_library_key,
)

if TYPE_CHECKING:
    from posthoganalytics import Posthog


# The pending event and bucket removal must commit together while producers keep incrementing.
STAGE_USAGE = """
if redis.call('EXISTS', KEYS[1]) == 1 then return redis.call('HGETALL', KEYS[1]) end
local cutoff = tonumber(ARGV[1])
local buckets = redis.call('HGETALL', KEYS[2])
local count = 0
local min_bucket = cutoff
local max_bucket = 0
local deletions = {}
for i = 1, #buckets, 2 do
    local bucket = tonumber(buckets[i])
    if bucket < cutoff then
        count = count + tonumber(buckets[i + 1])
        min_bucket = math.min(min_bucket, bucket)
        max_bucket = math.max(max_bucket, bucket)
        table.insert(deletions, {KEYS[2], buckets[i]})
    end
end
if count == 0 then return nil end
local pending = {'event', ARGV[2], 'uuid', ARGV[3], 'count', tostring(count),
                 'min_time', tostring(min_bucket * tonumber(ARGV[4])),
                 'max_time', tostring(max_bucket * tonumber(ARGV[4]))}
for k = 3, #KEYS do
    local sdk_buckets = redis.call('HGETALL', KEYS[k])
    local sdk_count = 0
    for i = 1, #sdk_buckets, 2 do
        if tonumber(sdk_buckets[i]) <= max_bucket then
            sdk_count = sdk_count + tonumber(sdk_buckets[i + 1])
            table.insert(deletions, {KEYS[k], sdk_buckets[i]})
        end
    end
    if sdk_count > 0 then
        table.insert(pending, 'sdk:' .. ARGV[k + 2])
        table.insert(pending, tostring(sdk_count))
    end
end
redis.call('HSET', KEYS[1], unpack(pending))
for _, deletion in ipairs(deletions) do redis.call('HDEL', deletion[1], deletion[2]) end
return pending
"""

# An overlapping exporter must not acknowledge a newer batch for the same team.
ACKNOWLEDGE_USAGE = """
if redis.call('HGET', KEYS[1], 'uuid') == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""


class UsageExportEvent(TypedDict):
    uuid: str
    timestamp: str
    distinct_id: str
    event: str
    properties: dict[str, object]


@frozen(repr=False)
class PendingUsageExport:
    key: str
    event: UsageExportEvent

    @classmethod
    def from_redis(cls, key: str, values: list[bytes]) -> "PendingUsageExport":
        fields = dict(zip(values[::2], values[1::2]))
        event = cast(UsageExportEvent, json.loads(fields[b"event"]))
        for name in ("count", "min_time", "max_time"):
            event["properties"][name] = int(fields[name.encode()])
        sdk_breakdown = {k.decode().removeprefix("sdk:"): int(v) for k, v in fields.items() if k.startswith(b"sdk:")}
        if sdk_breakdown:
            event["properties"]["sdk_breakdown"] = sdk_breakdown
        return cls(key=key, event=event)


class FlagUsageExporter:
    def __init__(self, ph_client: "Posthog", client: redis.Redis, *, batch_size: int = 200) -> None:
        self.ph_client = ph_client
        self.client = client
        self.batch_size = batch_size
        self.stage_usage = client.register_script(STAGE_USAGE)
        self.acknowledge_usage = client.register_script(ACKNOWLEDGE_USAGE)
        self.pending: dict[str, PendingUsageExport] = {}

    def capture_team(self, team_id: int, team_uuid: str) -> None:
        billing_token = settings.DECIDE_BILLING_ANALYTICS_TOKEN
        if not billing_token or self.ph_client.disabled or not self.ph_client.send:
            return
        try:
            with self.client.lock(f"{REDIS_LOCK_TOKEN}:{team_id}", timeout=60, blocking=False):
                for request_type in USAGE_EVENT_NAMES:
                    key = get_team_request_key(team_id, request_type)
                    pending_key = f"{key}:pending_export"
                    if pending_key in self.pending:
                        continue
                    timestamp = datetime.now(UTC)
                    event = {
                        "uuid": str(uuid4()),
                        "timestamp": timestamp.isoformat(),
                        "distinct_id": str(team_id),
                        "event": USAGE_EVENT_NAMES[request_type],
                        "properties": {
                            **({"$geoip_disable": True} if self.ph_client.disable_geoip else {}),
                            **self.ph_client.super_properties,
                            "team_id": team_id,
                            "team_uuid": str(team_uuid),
                            "token": billing_token,
                        },
                    }
                    keys = [pending_key, key] + [
                        get_team_request_library_key(team_id, request_type, library) for library in SDK_LIBRARIES
                    ]
                    payload = self.stage_usage(
                        keys=keys,
                        args=[
                            int(timestamp.timestamp()) // CACHE_BUCKET_SIZE,
                            json.dumps(event),
                            event["uuid"],
                            CACHE_BUCKET_SIZE,
                            *SDK_LIBRARIES,
                        ],
                    )
                    if payload:
                        self.pending[pending_key] = PendingUsageExport.from_redis(pending_key, payload)
        except redis.exceptions.LockError:
            pass
        except Exception as error:
            capture_exception(error)
        if len(self.pending) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        if not self.pending:
            return
        try:
            self._deliver_pending()
        except Exception as error:
            capture_exception(error)
        finally:
            # Redis retains unacknowledged exports for the next run. Release this batch so a
            # failed delivery cannot stop later teams or grow the in-memory batch indefinitely.
            self.pending.clear()

    def _deliver_pending(self) -> None:
        deliverable = []
        events = []
        for item in self.pending.values():
            event = deepcopy(item.event)
            if self.ph_client.before_send:
                filtered = self.ph_client.before_send(event)
                if filtered is None:
                    continue
                event = cast(UsageExportEvent, filtered)
                event["uuid"] = item.event["uuid"]
                event["timestamp"] = item.event["timestamp"]
            event["properties"]["$ignore_sent_at"] = True
            events.append(event)
            deliverable.append(item)
        if not events:
            return
        # SDK queue draining does not acknowledge delivery; this request raises on delivery failure.
        batch_post(
            self.ph_client.api_key,
            self.ph_client.host,
            batch=events,
            gzip=True,
            timeout=10,
        )
        pipe = self.client.pipeline(transaction=False)
        for item in deliverable:
            self.acknowledge_usage(keys=[item.key], args=[item.event["uuid"]], client=pipe)
        pipe.execute()


def capture_usage_for_all_teams(ph_client: "Posthog") -> None:
    if not settings.DECIDE_BILLING_ANALYTICS_TOKEN or ph_client.disabled or not ph_client.send:
        return
    exporter = FlagUsageExporter(ph_client, get_client())
    teams = Team.objects.exclude(Q(organization__for_internal_metrics=True) | Q(is_demo=True)).only("id", "uuid")
    for team in teams.iterator(chunk_size=2000):
        exporter.capture_team(team.id, str(team.uuid))
    exporter.flush()
