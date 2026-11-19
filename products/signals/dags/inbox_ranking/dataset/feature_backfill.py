"""An opt-in reconstruction of the ML-feature columns that older dataset partitions never recorded.

`inbox_report_state` records the content columns (`CONTENT_COLUMNS`) and `already_addressed` only
from the day they landed, and `inbox_report_scored_facts` only from the day the sweep began to
record facts. Neither is ever backfilled, because a rewrite would put today's report into a past
partition. This leaf leaves both alone. It writes a separate object per frozen batch, one row per
report born on the partition day, with the value of each feature group and where that value came
from. A reader picks the provenances it accepts.

The other ML-feature groups need no reconstruction: length, signal count and the priority and
actionability judgments are in every birth-day state snapshot, the sources are in the
`inbox_signal_embeddings` log, and the creation time never changes.

Provenance, best first, per group:
- `scoring_time`: the facts the sweep recorded when it first scored the report.
- `historical`: the birth-day state snapshot of a forward run, or for `already_addressed` the
  actionability artefact under the cutoff rules of `judgment_artefacts_as_of`.
- `later_snapshot`: the earliest later state snapshot that recorded the group, or a birth-day
  snapshot that a backfill wrote long after the day.
- `current_approximation`: the report as it is when the batch is built. It can hold edits made
  after the report's outcome, so it can leak the label.
- `missing`: no source holds the value, for example a deleted report. Every value is null, never 0.

`observed_at` is the moment the value was true in its source, never the birth day.
"""

import enum
import datetime
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any

import dagster
import pyarrow as pa
import pydantic
import pyarrow.compute as pc

from posthog import settings
from posthog.dataclasses import frozen

from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.ranking.features import ALREADY_ADDRESSED_COLUMN, CONTENT_COLUMNS, SCORED_AT_COLUMN
from products.signals.backend.ranking.report_facts import (
    FACTS_SCHEMA_VERSION,
    judgment_facts,
    report_content_annotations,
)
from products.signals.dags.inbox_ranking.common import (
    DATASET_VERSION,
    PARQUET_PART_NAME,
    dataset_bucket,
    ensure_utc,
    object_schema_version,
    owner_tags,
    partition_object_key,
    read_parquet_if_exists,
    s3_client,
    skip_unconfigured,
    snapshot_bounds,
    write_parquet,
)
from products.signals.dags.inbox_ranking.consent import training_consent_team_ids
from products.signals.dags.inbox_ranking.dataset.dag import (
    HEAVY_ASSET_KWARGS,
    SCORED_FACTS_TABLE,
    STATE_SCHEMA,
    STATE_TABLE,
    judgment_artefacts_as_of,
    peak_rss_metadata,
)

FEATURE_BACKFILL_TABLE = "inbox_report_feature_backfill"
# A leaf with its own columns, so its schema moves apart from FEATURE_SCHEMA_VERSION. A batch written
# under another version is never rewritten: a schema change needs a new batch.
FEATURE_BACKFILL_SCHEMA_VERSION = 1
# The same bound as the training side's STATE_LAG_LIMIT: a state row read later than this after its
# snapshot end is a backfill, which holds the report as it was on the run day.
HISTORICAL_LAG_LIMIT = datetime.timedelta(days=2)
# How far past the birth day the asset looks for a state snapshot that recorded the content columns.
# Each day is one read of a state object, and the walk stops once every report has a value.
LATER_SNAPSHOT_MAX_DAYS = 90
# The `<group>_source` of a value read from Postgres when the batch is built.
REPORT_SOURCE = "signal_report"
ARTEFACT_SOURCE = "signal_report_artefact"
# One birth day is a small spine, but its ids still go into one `IN` list per chunk.
_ORM_ID_CHUNK = 2000

CONTENT_GROUP = "content"
ALREADY_ADDRESSED_GROUP = ALREADY_ADDRESSED_COLUMN
FEATURE_GROUPS = (CONTENT_GROUP, ALREADY_ADDRESSED_GROUP)


class Provenance(enum.StrEnum):
    SCORING_TIME = "scoring_time"
    HISTORICAL = "historical"
    LATER_SNAPSHOT = "later_snapshot"
    CURRENT_APPROXIMATION = "current_approximation"
    MISSING = "missing"


_TIMESTAMP = pa.timestamp("us", tz="UTC")


def _provenance_fields(group: str) -> list[tuple[str, pa.DataType]]:
    return [
        (f"{group}_provenance", pa.string()),
        (f"{group}_observed_at", _TIMESTAMP),
        (f"{group}_source", pa.string()),
    ]


_FEATURE_BACKFILL_FIELDS: list[tuple[str, pa.DataType]] = [
    ("snapshot_date", pa.date32()),
    ("report_id", pa.string()),
    ("report_team_id", pa.int64()),
    ("region", pa.string()),
    ("report_created_at", _TIMESTAMP),
    ("batch_id", pa.string()),
    ("backfill_schema_version", pa.int32()),
    ("facts_schema_version", pa.int32()),
    ("reconstructed_at", _TIMESTAMP),
    *((name, STATE_SCHEMA.field(name).type) for name in CONTENT_COLUMNS),
    *_provenance_fields(CONTENT_GROUP),
    (ALREADY_ADDRESSED_COLUMN, STATE_SCHEMA.field(ALREADY_ADDRESSED_COLUMN).type),
    *_provenance_fields(ALREADY_ADDRESSED_GROUP),
]
FEATURE_BACKFILL_SCHEMA = pa.schema(_FEATURE_BACKFILL_FIELDS)

# The batch id is a path segment and the name a training reader selects, so it stays a plain slug.
BATCH_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,62}$"


class FeatureBackfillConfig(dagster.Config):
    batch_id: str = pydantic.Field(
        pattern=BATCH_ID_PATTERN,
        description="The frozen batch to write, such as `ml-features-2026-11-13`. A day already in the batch is never rewritten.",
    )
    dry_run: bool = pydantic.Field(
        default=True,
        description="Build the rows and report coverage without writing. Set to false to write the batch.",
    )


def feature_backfill_object_key(prefix: str, batch_id: str, partition_key: str) -> str:
    return (
        f"{prefix}/{FEATURE_BACKFILL_TABLE}/{DATASET_VERSION}/batch={batch_id}/dt={partition_key}/{PARQUET_PART_NAME}"
    )


def deployment_region() -> str:
    return (settings.CLOUD_DEPLOYMENT or "local").lower()


@frozen
class SpineReport:
    report_id: str
    team_id: int
    region: str
    created_at: datetime.datetime


@frozen
class BirthSpine:
    reports: list[SpineReport]
    # The birth-day state row of each report in `reports`.
    rows: dict[str, dict[str, Any]]
    excluded_no_training_consent_reports: int
    excluded_other_region_reports: int


def birth_spine(
    state_rows: Iterable[Mapping[str, Any]],
    snapshot_date: datetime.date,
    consent_team_ids: Collection[int],
    region: str,
) -> BirthSpine:
    """The reports of the dt=D state snapshot that were created on D, belong to a team that allows AI
    training now, and were snapshotted in this region. Sorted by report id, so a batch is stable."""
    start, end = snapshot_bounds(snapshot_date.isoformat())
    reports: list[SpineReport] = []
    rows: dict[str, dict[str, Any]] = {}
    no_consent = other_region = 0
    for row in state_rows:
        created_at = ensure_utc(row["report_created_at"])
        if created_at is None or not start <= created_at < end:
            continue
        if row["report_team_id"] not in consent_team_ids:
            no_consent += 1
            continue
        if row["region"] != region:
            other_region += 1
            continue
        report_id = row["report_id"]
        reports.append(
            SpineReport(report_id=report_id, team_id=row["report_team_id"], region=row["region"], created_at=created_at)
        )
        rows[report_id] = dict(row)
    return BirthSpine(
        reports=sorted(reports, key=lambda report: report.report_id),
        rows=rows,
        excluded_no_training_consent_reports=no_consent,
        excluded_other_region_reports=other_region,
    )


@frozen
class LaterSnapshot:
    partition_key: str
    row: Mapping[str, Any]


@frozen
class Judgment:
    already_addressed: bool
    written_at: datetime.datetime


@frozen
class SourceRows:
    """Every source a batch reads, keyed by report id. A loader keeps a row only when its team is the
    spine's team for that report."""

    scored: Mapping[str, Mapping[str, Any]]
    birth: Mapping[str, Mapping[str, Any]]
    later: Mapping[str, LaterSnapshot]
    current_content: Mapping[str, Mapping[str, Any]]
    historical_judgments: Mapping[str, Judgment]
    current_judgments: Mapping[str, Judgment]


@frozen
class BackfillBatch:
    batch_id: str
    snapshot_date: datetime.date
    reconstructed_at: datetime.datetime


@frozen
class Observation:
    values: Mapping[str, Any]
    provenance: Provenance
    observed_at: datetime.datetime | None
    source: str | None


def recorded_content(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The content columns of a row, or None when the row did not record every one of them. A
    snapshot written before the columns landed has none of them, which is unknown and not 0."""
    if row is None or any(row.get(name) is None for name in CONTENT_COLUMNS):
        return None
    return {name: row[name] for name in CONTENT_COLUMNS}


def _content_observation(report: SpineReport, sources: SourceRows, batch: BackfillBatch) -> Observation:
    _, snapshot_end = snapshot_bounds(batch.snapshot_date.isoformat())
    day = batch.snapshot_date.isoformat()
    scored = sources.scored.get(report.report_id)
    if (values := recorded_content(scored)) is not None and scored is not None:
        return Observation(
            values=values,
            provenance=Provenance.SCORING_TIME,
            observed_at=ensure_utc(scored[SCORED_AT_COLUMN]),
            source=f"{SCORED_FACTS_TABLE}/dt={day}",
        )
    birth = sources.birth.get(report.report_id)
    if (values := recorded_content(birth)) is not None and birth is not None:
        observed_at = ensure_utc(birth["features_observed_at"])
        forward_run = observed_at is not None and observed_at <= snapshot_end + HISTORICAL_LAG_LIMIT
        return Observation(
            values=values,
            provenance=Provenance.HISTORICAL if forward_run else Provenance.LATER_SNAPSHOT,
            observed_at=observed_at,
            source=f"{STATE_TABLE}/dt={day}",
        )
    later = sources.later.get(report.report_id)
    if later is not None and (values := recorded_content(later.row)) is not None:
        return Observation(
            values=values,
            provenance=Provenance.LATER_SNAPSHOT,
            observed_at=ensure_utc(later.row["features_observed_at"]),
            source=f"{STATE_TABLE}/dt={later.partition_key}",
        )
    if (values := recorded_content(sources.current_content.get(report.report_id))) is not None:
        return Observation(
            values=values,
            provenance=Provenance.CURRENT_APPROXIMATION,
            observed_at=batch.reconstructed_at,
            source=REPORT_SOURCE,
        )
    return Observation(
        values=dict.fromkeys(CONTENT_COLUMNS), provenance=Provenance.MISSING, observed_at=None, source=None
    )


def _already_addressed_observation(report: SpineReport, sources: SourceRows, batch: BackfillBatch) -> Observation:
    scored = sources.scored.get(report.report_id)
    if scored is not None and isinstance(scored.get(ALREADY_ADDRESSED_COLUMN), bool):
        return Observation(
            values={ALREADY_ADDRESSED_COLUMN: scored[ALREADY_ADDRESSED_COLUMN]},
            provenance=Provenance.SCORING_TIME,
            observed_at=ensure_utc(scored[SCORED_AT_COLUMN]),
            source=f"{SCORED_FACTS_TABLE}/dt={batch.snapshot_date.isoformat()}",
        )
    for judgments, provenance in (
        (sources.historical_judgments, Provenance.HISTORICAL),
        (sources.current_judgments, Provenance.CURRENT_APPROXIMATION),
    ):
        judgment = judgments.get(report.report_id)
        if judgment is not None:
            return Observation(
                values={ALREADY_ADDRESSED_COLUMN: judgment.already_addressed},
                provenance=provenance,
                observed_at=judgment.written_at,
                source=ARTEFACT_SOURCE,
            )
    return Observation(
        values={ALREADY_ADDRESSED_COLUMN: None}, provenance=Provenance.MISSING, observed_at=None, source=None
    )


def _group_columns(group: str, observation: Observation) -> dict[str, Any]:
    return {
        **observation.values,
        f"{group}_provenance": observation.provenance.value,
        f"{group}_observed_at": observation.observed_at,
        f"{group}_source": observation.source,
    }


def feature_backfill_rows(
    spine: Sequence[SpineReport], sources: SourceRows, batch: BackfillBatch
) -> list[dict[str, Any]]:
    """One row per spine report, each group taken from its best source."""
    return [
        {
            "snapshot_date": batch.snapshot_date,
            "report_id": report.report_id,
            "report_team_id": report.team_id,
            "region": report.region,
            "report_created_at": report.created_at,
            "batch_id": batch.batch_id,
            "backfill_schema_version": FEATURE_BACKFILL_SCHEMA_VERSION,
            "facts_schema_version": FACTS_SCHEMA_VERSION,
            "reconstructed_at": batch.reconstructed_at,
            **_group_columns(CONTENT_GROUP, _content_observation(report, sources, batch)),
            **_group_columns(ALREADY_ADDRESSED_GROUP, _already_addressed_observation(report, sources, batch)),
        }
        for report in spine
    ]


def backfill_coverage(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """The number of rows per feature group and provenance, every pair present, so a dry run shows
    what a batch would recover before it writes."""
    counts = Counter(f"{group}_{row[f'{group}_provenance']}" for row in rows for group in FEATURE_GROUPS)
    return {
        f"{group}_{provenance.value}": counts[f"{group}_{provenance.value}"]
        for group in FEATURE_GROUPS
        for provenance in Provenance
    }


def _team_rows(table: pa.Table | None, teams: Mapping[str, int]) -> dict[str, dict[str, Any]]:
    """The rows of a dataset object whose report is in `teams` and names the same team."""
    if table is None or table.num_rows == 0:
        return {}
    table = table.filter(pc.is_in(table.column("report_id"), value_set=pa.array(sorted(teams), type=pa.string())))
    return {row["report_id"]: row for row in table.to_pylist() if row["report_team_id"] == teams[row["report_id"]]}


def earliest_later_snapshots(
    client, bucket: str, prefix: str, partition_key: str, teams: Mapping[str, int], today: datetime.date
) -> tuple[dict[str, LaterSnapshot], int]:
    """For each report in `teams`, the earliest state snapshot after D, up to `LATER_SNAPSHOT_MAX_DAYS`
    and before today, that recorded its content columns. Also the number of state objects read."""
    found: dict[str, LaterSnapshot] = {}
    pending = dict(teams)
    days_read = 0
    birth_day = datetime.date.fromisoformat(partition_key)
    for offset in range(1, LATER_SNAPSHOT_MAX_DAYS + 1):
        day = birth_day + datetime.timedelta(days=offset)
        if not pending or day >= today:
            break
        table = read_parquet_if_exists(client, bucket, partition_object_key(prefix, STATE_TABLE, day.isoformat()))
        days_read += 1
        if table is None or not set(CONTENT_COLUMNS) <= set(table.column_names):
            continue
        for report_id, row in _team_rows(table, pending).items():
            if recorded_content(row) is not None:
                found[report_id] = LaterSnapshot(partition_key=day.isoformat(), row=row)
                del pending[report_id]
    return found, days_read


def current_content_rows(teams: Mapping[str, int]) -> dict[str, dict[str, Any]]:
    """The content columns of each report as it is now, counted in Postgres so a report body is
    never loaded. A report that is gone, or that now names another team, has no row."""
    content = report_content_annotations()
    rows: dict[str, dict[str, Any]] = {}
    report_ids = sorted(teams)
    for offset in range(0, len(report_ids), _ORM_ID_CHUNK):
        for row in (
            SignalReport.objects.filter(id__in=report_ids[offset : offset + _ORM_ID_CHUNK])
            .annotate(**content)
            .values("id", "team_id", "user_authored", *content)
        ):
            report_id = str(row["id"])
            if row["team_id"] == teams[report_id]:
                rows[report_id] = row
    return rows


def already_addressed_judgments(teams: Mapping[str, int], cutoff: datetime.datetime) -> dict[str, Judgment]:
    """The `already_addressed` flag of each report's latest actionability artefact as of the cutoff,
    under the cutoff rules of `judgment_artefacts_as_of`. An artefact of another team, or one that
    holds no boolean, gives no judgment."""
    judgments: dict[str, Judgment] = {}
    for artefact in judgment_artefacts_as_of(sorted(teams), cutoff):
        if artefact.artefact_type != SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT:
            continue
        if artefact.team_id != teams.get(artefact.report_id):
            continue
        flag = (judgment_facts(artefact.artefact_type, artefact.content) or {}).get(ALREADY_ADDRESSED_COLUMN)
        if isinstance(flag, bool):
            judgments[artefact.report_id] = Judgment(already_addressed=flag, written_at=artefact.written_at)
    return judgments


@dagster.asset(name=FEATURE_BACKFILL_TABLE, deps=[STATE_TABLE, SCORED_FACTS_TABLE], **HEAVY_ASSET_KWARGS)
def inbox_report_feature_backfill(context: dagster.AssetExecutionContext, config: FeatureBackfillConfig) -> None:
    """The ML-feature groups of each report born on D, with their provenance, in one frozen batch.

    No schedule runs it and nothing reads it yet. A day already written in the batch is left as it
    is, so a repeat cannot read the mutable current state again; a refresh is a new batch id.
    """
    if skip_unconfigured(context):
        return
    partition_key = context.partition_key
    bucket, prefix, client = dataset_bucket(), settings.INBOX_RANKING_DATASET_S3_PREFIX, s3_client()
    key = feature_backfill_object_key(prefix, config.batch_id, partition_key)
    written_version = object_schema_version(client, bucket, key)
    if written_version is not None:
        if written_version != FEATURE_BACKFILL_SCHEMA_VERSION:
            raise dagster.Failure(
                f"batch {config.batch_id} holds dt={partition_key} under schema v{written_version}; start a new batch"
            )
        context.log.info(f"batch {config.batch_id} already holds dt={partition_key}; left as it is")
        context.add_output_metadata(
            {"frozen": dagster.MetadataValue.bool(True), "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}")}
        )
        return

    reconstructed_at = datetime.datetime.now(datetime.UTC)
    snapshot_date = datetime.date.fromisoformat(partition_key)
    start, snapshot_end = snapshot_bounds(partition_key)
    state = read_parquet_if_exists(client, bucket, partition_object_key(prefix, STATE_TABLE, partition_key))
    if state is None:
        raise dagster.Failure(f"{STATE_TABLE} dt={partition_key} is missing; it is the spine of the backfill")
    created_at = state.column("report_created_at")
    born = state.filter(
        pc.and_(
            pc.greater_equal(created_at, pa.scalar(start, type=_TIMESTAMP)),
            pc.less(created_at, pa.scalar(snapshot_end, type=_TIMESTAMP)),
        )
    )
    spine = birth_spine(born.to_pylist(), snapshot_date, training_consent_team_ids(), deployment_region())
    teams = {report.report_id: report.team_id for report in spine.reports}

    scored = _team_rows(
        read_parquet_if_exists(client, bucket, partition_object_key(prefix, SCORED_FACTS_TABLE, partition_key)), teams
    )
    unresolved = {
        report_id: team_id
        for report_id, team_id in teams.items()
        if recorded_content(scored.get(report_id)) is None and recorded_content(spine.rows.get(report_id)) is None
    }
    later, later_days_read = earliest_later_snapshots(
        client, bucket, prefix, partition_key, unresolved, reconstructed_at.date()
    )
    sources = SourceRows(
        scored=scored,
        birth=spine.rows,
        later=later,
        current_content=current_content_rows(teams),
        historical_judgments=already_addressed_judgments(teams, snapshot_end),
        current_judgments=already_addressed_judgments(teams, reconstructed_at),
    )
    batch = BackfillBatch(batch_id=config.batch_id, snapshot_date=snapshot_date, reconstructed_at=reconstructed_at)
    rows = feature_backfill_rows(spine.reports, sources, batch)

    if not config.dry_run:
        write_parquet(
            client,
            bucket,
            key,
            pa.Table.from_pylist(rows, schema=FEATURE_BACKFILL_SCHEMA),
            schema_version=FEATURE_BACKFILL_SCHEMA_VERSION,
        )
    context.add_output_metadata(
        {
            **peak_rss_metadata(),
            "dry_run": dagster.MetadataValue.bool(config.dry_run),
            "rows": dagster.MetadataValue.int(len(rows)),
            **{name: dagster.MetadataValue.int(count) for name, count in backfill_coverage(rows).items()},
            "later_snapshot_days_read": dagster.MetadataValue.int(later_days_read),
            "excluded_no_training_consent_reports": dagster.MetadataValue.int(
                spine.excluded_no_training_consent_reports
            ),
            "excluded_other_region_reports": dagster.MetadataValue.int(spine.excluded_other_region_reports),
            "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}"),
        }
    )


inbox_ranking_feature_backfill_job = dagster.define_asset_job(
    name="inbox_ranking_feature_backfill_job",
    selection=[FEATURE_BACKFILL_TABLE],
    tags={**owner_tags, "dagster/max_runtime": str(60 * 60)},
)
