import json
import uuid
import dataclasses
from datetime import UTC, date, datetime, timedelta

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.storage import object_storage

from products.replay.backend.temporal.export_recordings.activities import SESSION_EXPIRY_TIME_SQL, quote_storage_key

# AWS list prices for the replay bucket's storage classes.
STANDARD_GET_USD_PER_1K = 0.0004
GLACIER_IR_GET_USD_PER_1K = 0.01
GLACIER_IR_RETRIEVAL_USD_PER_GB = 0.03
CROSS_REGION_TRANSFER_USD_PER_GB = 0.02
COMPUTE_USD_PER_PROCESS_HOUR = 0.06
# Measured read rate of one shard activity.
SHARD_BYTES_PER_SECOND = 50_000_000

# Replay batch files outside the 30d tier move to Glacier Instant Retrieval at this age.
GLACIER_IR_AFTER_DAYS = 30
QUOTE_VALID_DAYS = 7
# A file that crosses into Glacier IR before the run ends is read at the Glacier IR price.
RUN_ALLOWANCE_DAYS = 2
SESSION_IDS_PER_QUERY = 2000

QUOTE_USAGE_QUERY = f"""
SELECT
    count(),
    sum(length(blocks)),
    sum(arraySum(b -> b.1, blocks)),
    sum(arrayCount(b -> b.2, blocks)),
    sum(arraySum(b -> if(b.2, b.1, 0), blocks)),
    countIf(expiry_time < %(best_effort_before)s)
FROM (
    SELECT
        min(min_first_timestamp) AS start_time,
        arrayMap(
            u -> tuple(
                toUInt64(extract(u, 'bytes=[0-9]+-([0-9]+)')) - toUInt64(extract(u, 'bytes=([0-9]+)-')) + 1,
                extract(u, '/([0-9a-z]+)/[0-9]+-[0-9a-f]+[?]') != '30d'
                    AND toUInt64OrZero(extract(u, '/([0-9]+)-[0-9a-f]+[?]')) < %(glacier_cutoff_ms)s
            ),
            groupArrayArray(block_urls)
        ) AS blocks,
        {SESSION_EXPIRY_TIME_SQL} AS expiry_time
    FROM session_replay_events
    PREWHERE team_id = %(team_id)s
        AND min_first_timestamp >= %(range_start)s - INTERVAL 1 DAY
        AND min_first_timestamp < %(range_end)s + INTERVAL 1 DAY
    {{session_filter}}
    GROUP BY session_id
    HAVING max(is_deleted) = 0
        AND start_time >= %(range_start)s
        AND start_time < %(range_end)s
        AND expiry_time >= now()
)
"""


@frozen
class QuoteUsage:
    sessions: int = 0
    blocks: int = 0
    bytes: int = 0
    glacier_blocks: int = 0
    glacier_bytes: int = 0
    best_effort_sessions: int = 0

    def add(self, other: "QuoteUsage") -> "QuoteUsage":
        return QuoteUsage(
            **{f.name: getattr(self, f.name) + getattr(other, f.name) for f in dataclasses.fields(QuoteUsage)}
        )


@frozen
class QuoteCost:
    standard_gets_usd: float
    glacier_ir_gets_usd: float
    glacier_ir_retrieval_usd: float
    transfer_usd: float
    compute_usd: float
    total_usd: float
    estimated_hours: float


@frozen
class Quote:
    quote_id: str
    team_id: int
    date_from: str
    date_to: str
    session_ids_key: str | None
    region: str
    cross_region: bool
    max_parallel_shards: int
    created_at: str
    valid_until: str
    usage: QuoteUsage
    cost: QuoteCost

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self), indent=2)

    @classmethod
    def from_json(cls, content: str) -> "Quote":
        data = json.loads(content)
        return cls(**{**data, "usage": QuoteUsage(**data["usage"]), "cost": QuoteCost(**data["cost"])})


def price(usage: QuoteUsage, *, max_parallel_shards: int, cross_region: bool) -> QuoteCost:
    standard_gets = (usage.blocks - usage.glacier_blocks) / 1000 * STANDARD_GET_USD_PER_1K
    glacier_gets = usage.glacier_blocks / 1000 * GLACIER_IR_GET_USD_PER_1K
    retrieval = usage.glacier_bytes / 1e9 * GLACIER_IR_RETRIEVAL_USD_PER_GB
    transfer = usage.bytes / 1e9 * CROSS_REGION_TRANSFER_USD_PER_GB if cross_region else 0.0
    process_hours = usage.bytes / SHARD_BYTES_PER_SECOND / 3600
    compute = process_hours * COMPUTE_USD_PER_PROCESS_HOUR
    return QuoteCost(
        standard_gets_usd=round(standard_gets, 2),
        glacier_ir_gets_usd=round(glacier_gets, 2),
        glacier_ir_retrieval_usd=round(retrieval, 2),
        transfer_usd=round(transfer, 2),
        compute_usd=round(compute, 2),
        total_usd=round(standard_gets + glacier_gets + retrieval + transfer + compute, 2),
        estimated_hours=round(process_hours / max_parallel_shards, 1),
    )


def measure_usage(
    team_id: int, date_from: str, date_to: str, session_ids: list[str] | None, now: datetime
) -> QuoteUsage:
    tag_queries(product=Product.REPLAY, feature=Feature.MANAGEMENT_COMMAND, team_id=team_id)
    glacier_cutoff = now + timedelta(days=QUOTE_VALID_DAYS + RUN_ALLOWANCE_DAYS - GLACIER_IR_AFTER_DAYS)
    params = {
        "team_id": team_id,
        "glacier_cutoff_ms": int(glacier_cutoff.timestamp() * 1000),
        "best_effort_before": now + timedelta(days=QUOTE_VALID_DAYS + RUN_ALLOWANCE_DAYS),
    }
    first, last = date.fromisoformat(date_from), date.fromisoformat(date_to)
    # A whole range in one query times out on large teams, so a full export reads one day at a time.
    # A session list reads its IDs in chunks over the whole range instead.
    windows: list[tuple[date, date, list[str] | None]]
    if session_ids is None:
        windows = [
            (first + timedelta(days=offset), first + timedelta(days=offset + 1), None)
            for offset in range((last - first).days + 1)
        ]
    else:
        windows = [
            (first, last + timedelta(days=1), session_ids[start : start + SESSION_IDS_PER_QUERY])
            for start in range(0, len(session_ids), SESSION_IDS_PER_QUERY)
        ]

    usage = QuoteUsage()
    for range_start, range_end, chunk in windows:
        query = QUOTE_USAGE_QUERY.replace(
            "{session_filter}", "WHERE session_id IN %(session_ids)s" if chunk is not None else ""
        )
        [row] = sync_execute(
            query,
            {
                **params,
                "range_start": datetime.combine(range_start, datetime.min.time(), UTC),
                "range_end": datetime.combine(range_end, datetime.min.time(), UTC),
                "session_ids": chunk,
            },
        )
        names = [field.name for field in dataclasses.fields(QuoteUsage)]
        usage = usage.add(QuoteUsage(**{name: int(value or 0) for name, value in zip(names, row)}))
    return usage


def create_quote(
    *,
    team_id: int,
    date_from: str,
    date_to: str,
    session_ids: list[str] | None,
    region: str,
    cross_region: bool,
    max_parallel_shards: int,
) -> Quote:
    now = datetime.now(UTC)
    quote_id = uuid.uuid4().hex
    session_ids_key = None
    if session_ids is not None:
        session_ids_key = f"session_recording_exports/session_ids/{quote_id}.txt"
        object_storage.write(session_ids_key, "\n".join(session_ids))
    usage = measure_usage(team_id, date_from, date_to, session_ids, now)
    quote = Quote(
        quote_id=quote_id,
        team_id=team_id,
        date_from=date_from,
        date_to=date_to,
        session_ids_key=session_ids_key,
        region=region,
        cross_region=cross_region,
        max_parallel_shards=max_parallel_shards,
        created_at=now.isoformat(),
        valid_until=(now + timedelta(days=QUOTE_VALID_DAYS)).isoformat(),
        usage=usage,
        cost=price(usage, max_parallel_shards=max_parallel_shards, cross_region=cross_region),
    )
    object_storage.write(quote_storage_key(quote_id), quote.to_json())
    return quote


def load_quote(quote_id: str) -> Quote | None:
    content = object_storage.read(quote_storage_key(quote_id), missing_ok=True)
    return Quote.from_json(content) if content else None
