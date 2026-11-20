import json
import uuid
import dataclasses
from datetime import UTC, date, datetime, timedelta

from posthog.schema import RecordingOrder, RecordingOrderDirection

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.playlist_filters import convert_playlist_to_recordings_query
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery
from posthog.storage import object_storage

from products.replay.backend.temporal.export_recordings.activities import (
    MAX_SELECTED_SESSION_BYTES,
    MAX_SELECTED_SESSIONS,
    SESSION_EXPIRY_TIME_SQL,
    quote_storage_key,
    session_ids_shard_key,
)

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
PLAYLIST_PAGE_SIZE = 1000
PLAYLIST_QUERY_SECONDS = 600

# Per-URL expressions, applied to each row's block_urls so a session aggregates counters, not URL lists.
BLOCK_BYTES_SQL = "toUInt64(extract(u, 'bytes=[0-9]+-([0-9]+)')) - toUInt64(extract(u, 'bytes=([0-9]+)-')) + 1"
BLOCK_IN_GLACIER_SQL = (
    "extract(u, '/([0-9a-z]+)/[0-9]+-[0-9a-f]+[?]') != '30d' "
    "AND toUInt64OrZero(extract(u, '/([0-9]+)-[0-9a-f]+[?]')) < %(glacier_cutoff_ms)s"
)

SESSION_USAGE_QUERY = f"""
SELECT
    session_id,
    toDate(start_time),
    cityHash64(session_id) %% %(shards_per_day)s,
    blocks,
    bytes,
    glacier_blocks,
    glacier_bytes,
    expiry_time < %(best_effort_before)s
FROM (
    SELECT
        session_id,
        min(min_first_timestamp) AS start_time,
        sum(length(block_urls)) AS blocks,
        sum(arraySum(u -> {BLOCK_BYTES_SQL}, block_urls)) AS bytes,
        sum(arrayCount(u -> {BLOCK_IN_GLACIER_SQL}, block_urls)) AS glacier_blocks,
        sum(arraySum(u -> if({BLOCK_IN_GLACIER_SQL}, {BLOCK_BYTES_SQL}, 0), block_urls)) AS glacier_bytes,
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


class SelectionError(Exception):
    pass


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
    session_ids_prefix: str
    shards_per_day: int
    region: str
    cross_region: bool
    max_parallel_shards: int
    created_at: str
    valid_until: str
    usage: QuoteUsage
    cost: QuoteCost
    # How the sessions were chosen, for the customer's copy of the quote.
    selection: str

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


def day_range(date_from: str, date_to: str) -> list[date]:
    first, last = date.fromisoformat(date_from), date.fromisoformat(date_to)
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def _day_start(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), UTC)


@frozen
class Selection:
    usage: QuoteUsage
    shards: dict[tuple[date, int], list[str]]


def select_sessions(
    team_id: int, date_from: str, date_to: str, session_ids: list[str] | None, shards_per_day: int, now: datetime
) -> Selection:
    """Find the sessions the quote exports, with their usage. A list narrows the range to the sessions it names."""
    tag_queries(product=Product.REPLAY, feature=Feature.MANAGEMENT_COMMAND, team_id=team_id)
    glacier_cutoff = now + timedelta(days=QUOTE_VALID_DAYS + RUN_ALLOWANCE_DAYS - GLACIER_IR_AFTER_DAYS)
    params = {
        "team_id": team_id,
        "shards_per_day": shards_per_day,
        "glacier_cutoff_ms": int(glacier_cutoff.timestamp() * 1000),
        "best_effort_before": now + timedelta(days=QUOTE_VALID_DAYS + RUN_ALLOWANCE_DAYS),
    }
    days = day_range(date_from, date_to)
    # A whole range in one query times out on large teams, so a range reads one day at a time.
    windows: list[tuple[date, date, list[str] | None]]
    if session_ids is None:
        windows = [(day, day, None) for day in days]
    else:
        windows = [
            (days[0], days[-1], session_ids[start : start + SESSION_IDS_PER_QUERY])
            for start in range(0, len(session_ids), SESSION_IDS_PER_QUERY)
        ]

    usage = QuoteUsage()
    shards: dict[tuple[date, int], list[str]] = {}
    for first, last, chunk in windows:
        rows = sync_execute(
            SESSION_USAGE_QUERY.replace(
                "{session_filter}", "WHERE session_id IN %(session_ids)s" if chunk is not None else ""
            ),
            {
                **params,
                "range_start": _day_start(first),
                "range_end": _day_start(last + timedelta(days=1)),
                "session_ids": chunk,
            },
            workload=Workload.OFFLINE,
        )
        for session_id, day, shard, blocks, bytes, glacier_blocks, glacier_bytes, best_effort in rows:
            shards.setdefault((day, int(shard)), []).append(session_id)
            usage = usage.add(
                QuoteUsage(
                    sessions=1,
                    blocks=int(blocks),
                    bytes=int(bytes),
                    glacier_blocks=int(glacier_blocks),
                    glacier_bytes=int(glacier_bytes),
                    best_effort_sessions=int(best_effort),
                )
            )
    return Selection(usage=usage, shards={key: sorted(ids) for key, ids in shards.items()})


def create_quote(
    *,
    team_id: int,
    date_from: str,
    date_to: str,
    session_ids: list[str] | None,
    region: str,
    cross_region: bool,
    shards_per_day: int,
    max_parallel_shards: int,
    selection: str,
) -> Quote:
    now = datetime.now(UTC)
    quote_id = uuid.uuid4().hex
    selected = select_sessions(team_id, date_from, date_to, session_ids, shards_per_day, now)
    for (day, shard), ids in selected.shards.items():
        check_shard_selection(day, shard, ids)
    session_ids_prefix = f"session_recording_exports/session_ids/{quote_id}"
    # Every shard gets a file, so a shard that finds none knows the list was lost rather than empty.
    for day in day_range(date_from, date_to):
        for shard in range(shards_per_day):
            ids = selected.shards.get((day, shard), [])
            object_storage.write(session_ids_shard_key(session_ids_prefix, day.isoformat(), shard), "\n".join(ids))
    usage = selected.usage
    quote = Quote(
        quote_id=quote_id,
        team_id=team_id,
        date_from=date_from,
        date_to=date_to,
        session_ids_prefix=session_ids_prefix,
        shards_per_day=shards_per_day,
        region=region,
        cross_region=cross_region,
        max_parallel_shards=max_parallel_shards,
        created_at=now.isoformat(),
        valid_until=(now + timedelta(days=QUOTE_VALID_DAYS)).isoformat(),
        usage=usage,
        cost=price(usage, max_parallel_shards=max_parallel_shards, cross_region=cross_region),
        selection=selection,
    )
    object_storage.write(quote_storage_key(quote_id), quote.to_json())
    return quote


def load_quote(quote_id: str) -> Quote | None:
    content = object_storage.read(quote_storage_key(quote_id), missing_ok=True)
    return Quote.from_json(content) if content else None


def check_shard_selection(day: date, shard: int, session_ids: list[str]) -> None:
    """Refuse a shard whose session list does not fit in the shard query that filters by it."""
    if len(session_ids) > MAX_SELECTED_SESSIONS:
        raise SelectionError(
            f"Shard {day}:{shard} has {len(session_ids):,} sessions, more than {MAX_SELECTED_SESSIONS:,}. "
            "Quote again with a higher --shards-per-day."
        )
    # Each ID goes into the query quoted and comma-separated.
    if sum(len(session_id.encode()) + 4 for session_id in session_ids) > MAX_SELECTED_SESSION_BYTES:
        raise SelectionError(
            f"The session IDs in shard {day}:{shard} are too long to send in one query. "
            "Quote again with a higher --shards-per-day."
        )


def playlist_session_ids(team: Team, short_id: str, date_from: str, date_to: str) -> list[str]:
    """List every session a saved recordings filter matches in the range, as the recordings list would show it."""
    playlist = SessionRecordingPlaylist.objects.filter(team=team, short_id=short_id, deleted=False).first()
    if playlist is None:
        raise SelectionError(f"Saved filter {short_id} does not exist in team {team.pk}")
    if playlist.type == SessionRecordingPlaylist.PlaylistType.COLLECTION:
        raise SelectionError(f"{short_id} is a collection. Export its sessions with --session-ids-file instead.")
    query = convert_playlist_to_recordings_query(playlist, persist_legacy_conversion=False)
    query.date_from = _day_start(date.fromisoformat(date_from)).isoformat()
    query.date_to = (
        _day_start(date.fromisoformat(date_to) + timedelta(days=1)) - timedelta(microseconds=1)
    ).isoformat()
    query.order = RecordingOrder.START_TIME
    query.order_direction = RecordingOrderDirection.ASC
    query.limit = PLAYLIST_PAGE_SIZE
    query.offset = None
    query.after = None
    session_ids: list[str] = []
    while True:
        # A timeout must fail the quote, not return a shorter list that the customer then pays for.
        result = SessionRecordingListFromQuery(
            team=team, query=query, max_execution_time=PLAYLIST_QUERY_SECONDS, throw_on_timeout=True
        ).run()
        session_ids.extend(row["session_id"] for row in result.results)
        if not result.has_more_recording or not result.next_cursor:
            return sorted(set(session_ids))
        query.after = result.next_cursor
