import json
import uuid
import dataclasses
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
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
    SESSION_EXPIRY_TIME_SQL,
    quote_storage_key,
    session_ids_shard_key,
)
from products.replay.backend.temporal.export_recordings.types import day_range

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
# A listed ID adds about 40 bytes to the query, so a chunk stays well under the query size limit.
SESSION_IDS_PER_QUERY = 20_000
SHARD_FILE_WRITERS = 16
MAX_SESSIONS_PER_SHARD = 100_000
# Bounds the ID scans a list quote runs: one scan of the range per chunk.
MAX_LISTED_SESSIONS = 1_000_000
PLAYLIST_PAGE_SIZE = 10_000
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
LIMIT %(row_limit)s
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


def _day_start(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), UTC)


ShardLists = dict[tuple[date, int], list[str]]


def select_sessions(
    team_id: int,
    date_from: str,
    date_to: str,
    session_ids: list[str] | None,
    shards_per_day: int,
    now: datetime,
    on_days: Callable[[list[date], ShardLists], None],
) -> QuoteUsage:
    """Measure the sessions the quote exports and hand their lists to `on_days`, a day at a time for a range."""
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

    totals = [0] * len(dataclasses.fields(QuoteUsage))
    pending: ShardLists = {}
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
                # One row more than the day's shards can hold is enough to refuse the day.
                "row_limit": shards_per_day * MAX_SESSIONS_PER_SHARD + 1,
            },
            workload=Workload.OFFLINE,
        )
        if chunk is None and len(rows) > shards_per_day * MAX_SESSIONS_PER_SHARD:
            raise SelectionError(
                f"{first} has more sessions than {shards_per_day} shards hold. Raise --shards-per-day."
            )
        for session_id, day, shard, *counters in rows:
            pending.setdefault((day, int(shard)), []).append(session_id)
            totals[0] += 1
            for index, value in enumerate(counters, start=1):
                totals[index] += int(value)
        if session_ids is None:
            on_days([first], {key: sorted(ids) for key, ids in pending.items()})
            pending.clear()
    if session_ids is not None:
        on_days(days, {key: sorted(ids) for key, ids in pending.items()})
    return QuoteUsage(**dict(zip((f.name for f in dataclasses.fields(QuoteUsage)), totals)))


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
    if session_ids is not None and len(session_ids) > MAX_LISTED_SESSIONS:
        raise SelectionError(f"The list has {len(session_ids):,} sessions. Quote at most {MAX_LISTED_SESSIONS:,}.")
    now = datetime.now(UTC)
    quote_id = uuid.uuid4().hex
    session_ids_prefix = f"session_recording_exports/session_ids/{quote_id}"

    def write_lists(days: list[date], lists: ShardLists) -> None:
        for (day, shard), ids in lists.items():
            check_shard_selection(day, shard, ids)
        # Every shard gets a file, so a shard that finds none knows the list was lost rather than empty.
        files = [
            (session_ids_shard_key(session_ids_prefix, day.isoformat(), shard), "\n".join(lists.get((day, shard), [])))
            for day in days
            for shard in range(shards_per_day)
        ]
        with ThreadPoolExecutor(max_workers=SHARD_FILE_WRITERS) as pool:
            list(pool.map(lambda item: object_storage.write(*item), files))

    usage = select_sessions(team_id, date_from, date_to, session_ids, shards_per_day, now, write_lists)
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
    """Refuse a shard too big for one export activity to load and checkpoint through."""
    if len(session_ids) > MAX_SESSIONS_PER_SHARD:
        raise SelectionError(
            f"Shard {day}:{shard} has {len(session_ids):,} sessions, more than {MAX_SESSIONS_PER_SHARD:,}. "
            "Quote again with a higher --shards-per-day."
        )


def playlist_session_ids(team: Team, short_id: str, date_from: str, date_to: str) -> list[str]:
    """List every session a saved recordings filter matches in the range, as the recordings list would show it."""
    tag_queries(product=Product.REPLAY, feature=Feature.MANAGEMENT_COMMAND, team_id=team.pk)
    playlist = SessionRecordingPlaylist.objects.filter(team=team, short_id=short_id, deleted=False).first()
    if playlist is None:
        raise SelectionError(f"Saved filter {short_id} does not exist in team {team.pk}")
    if playlist.type == SessionRecordingPlaylist.PlaylistType.COLLECTION:
        raise SelectionError(f"{short_id} is a collection. Export its sessions with --session-ids-file instead.")
    query = convert_playlist_to_recordings_query(playlist, persist_legacy_conversion=False)
    # The recordings API resolves these outside the listing query, with a viewer to check access against.
    if any(getattr(predicate, "key", None) == "comment_text" for predicate in query.having_predicates or []):
        raise SelectionError(f"{short_id} filters on comment text, which exports cannot apply. Remove that filter.")
    if query.experiment_exposure is not None:
        raise SelectionError(f"{short_id} filters on experiment exposure, which exports cannot apply. Remove it.")
    query.order = RecordingOrder.START_TIME
    query.order_direction = RecordingOrderDirection.ASC
    query.limit = PLAYLIST_PAGE_SIZE
    query.offset = None
    session_ids: set[str] = set()
    # One day per listing bounds the event scan behind each page to that day.
    for day in day_range(date_from, date_to):
        query.date_from = _day_start(day).isoformat()
        query.date_to = (_day_start(day + timedelta(days=1)) - timedelta(microseconds=1)).isoformat()
        query.after = None
        while True:
            # A timeout must fail the quote, not return a shorter list that the customer then pays for.
            result = SessionRecordingListFromQuery(
                team=team, query=query, max_execution_time=PLAYLIST_QUERY_SECONDS, throw_on_timeout=True
            ).run()
            session_ids.update(row["session_id"] for row in result.results)
            if len(session_ids) > MAX_LISTED_SESSIONS:
                raise SelectionError(
                    f"{short_id} matches more than {MAX_LISTED_SESSIONS:,} sessions. Quote a shorter range."
                )
            if not result.has_more_recording or not result.next_cursor:
                break
            query.after = result.next_cursor
    return sorted(session_ids)
