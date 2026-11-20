import io
import json
import datetime
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

import dagster
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.exceptions import ClientError
from parameterized import parameterized

from posthog import settings
from posthog.models import Organization, Team

from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.ranking.features import CONTENT_COLUMNS
from products.signals.dags.inbox_ranking.common import SCHEMA_VERSION_METADATA_KEY, partition_object_key
from products.signals.dags.inbox_ranking.dataset import dag, feature_backfill
from products.signals.dags.inbox_ranking.dataset.dag import STATE_SCHEMA, STATE_TABLE
from products.signals.dags.inbox_ranking.dataset.feature_backfill import (
    FEATURE_BACKFILL_SCHEMA,
    FEATURE_BACKFILL_TABLE,
    BackfillBatch,
    FeatureBackfillConfig,
    Judgment,
    LaterSnapshot,
    SourceRows,
    SpineReport,
    backfill_coverage,
    birth_spine,
    feature_backfill_object_key,
    feature_backfill_rows,
)

BIRTH_DAY = datetime.date(2026, 7, 29)
BORN_AT = datetime.datetime(2026, 7, 29, 10, 0, tzinfo=datetime.UTC)
BEFORE_CUTOFF = datetime.datetime(2026, 7, 29, 12, 0, tzinfo=datetime.UTC)
AFTER_CUTOFF = datetime.datetime(2026, 7, 30, 1, 0, tzinfo=datetime.UTC)
FORWARD_RUN_AT = datetime.datetime(2026, 7, 30, 2, 40, tzinfo=datetime.UTC)
BACKFILL_RUN_AT = datetime.datetime(2026, 8, 20, 9, 0, tzinfo=datetime.UTC)
LATER_DAY = "2026-08-01"
LATER_RUN_AT = datetime.datetime(2026, 8, 2, 2, 40, tzinfo=datetime.UTC)
SCORED_AT = datetime.datetime(2026, 7, 29, 10, 4, tzinfo=datetime.UTC)
RECONSTRUCTED_AT = datetime.datetime(2026, 11, 13, 9, 0, tzinfo=datetime.UTC)
BATCH = BackfillBatch(batch_id="b1", snapshot_date=BIRTH_DAY, reconstructed_at=RECONSTRUCTED_AT)
REPORT = SpineReport(report_id="r1", team_id=7, region="local", created_at=BORN_AT)

SCORED_CONTENT = {
    "chart_count": 1,
    "metric_count": 0,
    "suggested_prompt_count": 2,
    "tag_count": 0,
    "user_authored": False,
}
BIRTH_CONTENT = {
    "chart_count": 2,
    "metric_count": 1,
    "suggested_prompt_count": 2,
    "tag_count": 1,
    "user_authored": False,
}
LATER_CONTENT = {
    "chart_count": 3,
    "metric_count": 1,
    "suggested_prompt_count": 2,
    "tag_count": 1,
    "user_authored": False,
}
CURRENT_CONTENT = {
    "chart_count": 4,
    "metric_count": 2,
    "suggested_prompt_count": 2,
    "tag_count": 1,
    "user_authored": True,
}
# The columns a state snapshot written before the content columns landed does not have.
_LATE_STATE_COLUMNS = {*CONTENT_COLUMNS, "content_revision_count", "corroboration_count", "already_addressed"}
OLD_STATE_SCHEMA = pa.schema([field for field in STATE_SCHEMA if field.name not in _LATE_STATE_COLUMNS])


def _sources(**overrides: Any) -> SourceRows:
    return SourceRows(
        **{
            "scored": {},
            "birth": {},
            "later": {},
            "current_content": {},
            "historical_judgments": {},
            "current_judgments": {},
            **overrides,
        }
    )


def _only_row(sources: SourceRows) -> dict[str, Any]:
    (row,) = feature_backfill_rows([REPORT], sources, BATCH)
    return row


@parameterized.expand(
    [
        (
            "scoring_time_facts_win",
            _sources(
                scored={"r1": {**SCORED_CONTENT, "scored_at": SCORED_AT}},
                birth={"r1": {**BIRTH_CONTENT, "features_observed_at": FORWARD_RUN_AT}},
            ),
            ("scoring_time", SCORED_CONTENT, SCORED_AT, "inbox_report_scored_facts/dt=2026-07-29"),
        ),
        (
            "a_forward_run_birth_snapshot_is_historical",
            _sources(
                scored={"r1": {**SCORED_CONTENT, "chart_count": None, "scored_at": SCORED_AT}},
                birth={"r1": {**BIRTH_CONTENT, "features_observed_at": FORWARD_RUN_AT}},
                current_content={"r1": CURRENT_CONTENT},
            ),
            ("historical", BIRTH_CONTENT, FORWARD_RUN_AT, "inbox_report_state/dt=2026-07-29"),
        ),
        (
            "a_birth_snapshot_written_by_a_backfill_is_a_later_observation",
            _sources(birth={"r1": {**BIRTH_CONTENT, "features_observed_at": BACKFILL_RUN_AT}}),
            ("later_snapshot", BIRTH_CONTENT, BACKFILL_RUN_AT, "inbox_report_state/dt=2026-07-29"),
        ),
        (
            "the_earliest_later_snapshot_beats_the_current_report",
            _sources(
                birth={"r1": {"features_observed_at": FORWARD_RUN_AT}},
                later={
                    "r1": LaterSnapshot(
                        partition_key=LATER_DAY, row={**LATER_CONTENT, "features_observed_at": LATER_RUN_AT}
                    )
                },
                current_content={"r1": CURRENT_CONTENT},
            ),
            ("later_snapshot", LATER_CONTENT, LATER_RUN_AT, f"inbox_report_state/dt={LATER_DAY}"),
        ),
        (
            "the_current_report_is_an_approximation_observed_when_the_batch_is_built",
            _sources(current_content={"r1": CURRENT_CONTENT}),
            ("current_approximation", CURRENT_CONTENT, RECONSTRUCTED_AT, "signal_report"),
        ),
        ("no_source_is_missing_and_null", _sources(), ("missing", dict.fromkeys(CONTENT_COLUMNS), None, None)),
    ]
)
def test_content_comes_from_its_best_source(_name, sources, expected):
    row = _only_row(sources)

    provenance, values, observed_at, source = expected
    assert (row["content_provenance"], row["content_observed_at"], row["content_source"]) == (
        provenance,
        observed_at,
        source,
    )
    assert {name: row[name] for name in CONTENT_COLUMNS} == values


@parameterized.expand(
    [
        (
            "scoring_time_wins",
            _sources(
                scored={"r1": {"already_addressed": True, "scored_at": SCORED_AT}},
                historical_judgments={"r1": Judgment(already_addressed=False, written_at=BEFORE_CUTOFF)},
            ),
            (True, "scoring_time", SCORED_AT),
        ),
        (
            "an_unjudged_score_falls_to_the_judgment_at_the_cutoff",
            _sources(
                scored={"r1": {"already_addressed": None, "scored_at": SCORED_AT}},
                historical_judgments={"r1": Judgment(already_addressed=False, written_at=BEFORE_CUTOFF)},
                current_judgments={"r1": Judgment(already_addressed=True, written_at=AFTER_CUTOFF)},
            ),
            (False, "historical", BEFORE_CUTOFF),
        ),
        (
            "only_a_current_judgment_is_an_approximation",
            _sources(current_judgments={"r1": Judgment(already_addressed=True, written_at=AFTER_CUTOFF)}),
            (True, "current_approximation", AFTER_CUTOFF),
        ),
        ("no_judgment_is_missing", _sources(), (None, "missing", None)),
    ]
)
def test_already_addressed_comes_from_its_best_source(_name, sources, expected):
    row = _only_row(sources)

    assert (row["already_addressed"], row["already_addressed_provenance"], row["already_addressed_observed_at"]) == (
        expected
    )


def test_a_parquet_round_trip_keeps_a_real_zero_apart_from_a_missing_value():
    zero = {"chart_count": 0, "metric_count": 0, "suggested_prompt_count": 0, "tag_count": 0, "user_authored": False}
    gone = SpineReport(report_id="r2", team_id=7, region="local", created_at=BORN_AT)
    rows = feature_backfill_rows([REPORT, gone], _sources(current_content={"r1": zero}), BATCH)
    assert [set(row) for row in rows] == [set(FEATURE_BACKFILL_SCHEMA.names)] * 2

    buffer = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows, schema=FEATURE_BACKFILL_SCHEMA), buffer)
    read = pq.read_table(pa.BufferReader(buffer.getvalue())).to_pylist()

    assert [{name: row[name] for name in (*CONTENT_COLUMNS, "content_provenance")} for row in read] == [
        {**zero, "content_provenance": "current_approximation"},
        {**dict.fromkeys(CONTENT_COLUMNS), "content_provenance": "missing"},
    ]
    assert read[1]["already_addressed"] is None
    coverage = backfill_coverage(read)
    assert (coverage["content_current_approximation"], coverage["content_missing"], coverage["content_historical"]) == (
        1,
        1,
        0,
    )
    assert coverage["already_addressed_missing"] == 2


def test_the_birth_spine_keeps_reports_born_on_the_day_of_consenting_teams_in_this_region():
    def state_row(report_id: str, team_id: int, created_at: datetime.datetime, region: str = "local") -> dict:
        return {"report_id": report_id, "report_team_id": team_id, "region": region, "report_created_at": created_at}

    spine = birth_spine(
        [
            state_row("born", 1, BORN_AT),
            state_row("older", 1, BORN_AT - datetime.timedelta(days=1)),
            state_row("no_consent", 2, BORN_AT),
            state_row("other_region", 1, BORN_AT, region="eu"),
        ],
        BIRTH_DAY,
        frozenset({1}),
        "local",
    )

    assert [report.report_id for report in spine.reports] == ["born"]
    assert (spine.excluded_no_training_consent_reports, spine.excluded_other_region_reports) == (1, 1)


class _Store:
    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = dict(objects or {})
        self.metadata: dict[str, dict[str, str]] = {}

    def head_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"Metadata": self.metadata.get(Key, {})}

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key])}

    def upload_fileobj(self, fileobj, bucket, key, ExtraArgs):
        self.objects[key] = fileobj.read()
        self.metadata[key] = ExtraArgs["Metadata"]


def _parquet(rows: list[dict[str, Any]], schema: pa.Schema) -> bytes:
    buffer = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), buffer)
    return buffer.getvalue()


def _run(store: _Store, batch_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    with (
        patch.object(feature_backfill, "skip_unconfigured", lambda context: False),
        patch.object(feature_backfill, "s3_client", lambda: store),
        dagster.build_asset_context(partition_key=BIRTH_DAY.isoformat()) as context,
    ):
        feature_backfill.inbox_report_feature_backfill(
            context, FeatureBackfillConfig(batch_id=batch_id, dry_run=dry_run)
        )
        return {name: value.value for name, value in context.get_output_metadata("result").items()}


def _batch_rows(store: _Store, batch_id: str) -> dict[str, dict[str, Any]]:
    key = feature_backfill_object_key(settings.INBOX_RANKING_DATASET_S3_PREFIX, batch_id, BIRTH_DAY.isoformat())
    return {row["report_id"]: row for row in pq.read_table(pa.BufferReader(store.objects[key])).to_pylist()}


def test_a_batch_written_under_another_schema_is_refused():
    store = _Store()
    key = feature_backfill_object_key(settings.INBOX_RANKING_DATASET_S3_PREFIX, "b1", BIRTH_DAY.isoformat())
    store.objects[key] = b""
    store.metadata[key] = {SCHEMA_VERSION_METADATA_KEY: "0"}

    with pytest.raises(dagster.Failure, match="start a new batch"):
        _run(store, "b1")


def test_the_backfill_runs_only_in_its_own_job():
    model_data_deps = {key.path[-1] for key in dag.inbox_report_model_data.keys_by_input_name.values()}
    assets = [
        *(value for value in vars(dag).values() if isinstance(value, dagster.AssetsDefinition)),
        feature_backfill.inbox_report_feature_backfill,
    ]
    dataset_selection = dag.inbox_ranking_dataset_job.selection.resolve(assets)
    backfill_selection = feature_backfill.inbox_ranking_feature_backfill_job.selection.resolve(assets)

    assert FEATURE_BACKFILL_TABLE not in model_data_deps
    assert dagster.AssetKey(FEATURE_BACKFILL_TABLE) not in dataset_selection
    assert backfill_selection == {dagster.AssetKey(FEATURE_BACKFILL_TABLE)}


class TestFeatureBackfillAsset(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_training_opted_in = True
        self.organization.save()
        self.other_team = Team.objects.create(organization=self.organization)
        opted_out = Organization.objects.create(name="opted out", is_ai_training_opted_in=False)
        self.opted_out_team = Team.objects.create(organization=opted_out)

        self.later = self._report(self.team, charts=[{"id": 1}] * 5)
        self.current = self._report(self.team, charts=[], metrics=[], suggested_prompts=[], tags=[])
        self.edited = self._report(self.team)
        self.historical = self._report(self.team)
        deleted = self._report(self.team)
        self.deleted = deleted
        SignalReport.objects.filter(id=deleted).delete()
        # The snapshot names this report as one of `self.team`'s, but its row now names another team.
        self.moved = self._report(self.other_team, charts=[{"id": 1}])
        self.no_consent = self._report(self.opted_out_team)
        self.other_region = self._report(self.team)

        self._judge(self.edited, self.team, False, created_at=BEFORE_CUTOFF, updated_at=AFTER_CUTOFF)
        self._judge(self.historical, self.team, True, created_at=BEFORE_CUTOFF)
        self._judge(self.historical, self.team, False, created_at=AFTER_CUTOFF)
        self._judge(self.moved, self.other_team, True, created_at=BEFORE_CUTOFF)

        prefix = settings.INBOX_RANKING_DATASET_S3_PREFIX
        birth_rows = [
            self._state_row(report_id, team.id)
            for report_id, team in (
                (self.later, self.team),
                (self.current, self.team),
                (self.edited, self.team),
                (self.historical, self.team),
                (self.deleted, self.team),
                (self.moved, self.team),
                (self.no_consent, self.opted_out_team),
            )
        ] + [self._state_row(self.other_region, self.team.id, region="eu")]
        later_rows = [
            {
                **self._state_row(self.later, self.team.id),
                "snapshot_date": datetime.date.fromisoformat(LATER_DAY),
                "features_observed_at": LATER_RUN_AT,
                **LATER_CONTENT,
            }
        ]
        self.store = _Store(
            {
                partition_object_key(prefix, STATE_TABLE, BIRTH_DAY.isoformat()): _parquet(
                    birth_rows, OLD_STATE_SCHEMA
                ),
                partition_object_key(prefix, STATE_TABLE, LATER_DAY): _parquet(later_rows, STATE_SCHEMA),
            }
        )

    def _report(self, team: Team, **fields: Any) -> str:
        report = SignalReport.objects.create(team=team, status=SignalReport.Status.READY, title="t", summary="s")
        if fields:
            SignalReport.objects.filter(id=report.id).update(**fields)
        return str(report.id)

    def _judge(
        self,
        report_id: str,
        team: Team,
        already_addressed: bool,
        *,
        created_at: datetime.datetime,
        updated_at: datetime.datetime | None = None,
    ) -> None:
        artefact = SignalReportArtefact.objects.create(
            team=team,
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            content=json.dumps({"actionability": "immediately_actionable", "already_addressed": already_addressed}),
        )
        SignalReportArtefact.objects.filter(id=artefact.id).update(
            created_at=created_at, updated_at=updated_at or created_at
        )

    def _state_row(self, report_id: str, team_id: int, *, region: str = "local") -> dict[str, Any]:
        return {
            "snapshot_date": BIRTH_DAY,
            "report_id": report_id,
            "report_team_id": team_id,
            "region": region,
            "status": "ready",
            "report_created_at": BORN_AT,
            "features_observed_at": FORWARD_RUN_AT,
        }

    def test_a_dry_run_writes_nothing_and_a_run_records_each_groups_provenance(self):
        state_objects = dict(self.store.objects)

        dry = _run(self.store, "b1", dry_run=True)
        assert self.store.objects == state_objects
        metadata = _run(self.store, "b1")

        rows = _batch_rows(self.store, "b1")
        assert set(self.store.objects) - set(state_objects) == {
            feature_backfill_object_key(settings.INBOX_RANKING_DATASET_S3_PREFIX, "b1", BIRTH_DAY.isoformat())
        }
        assert {key: dry[key] for key in dry if key.startswith("content_")} == {
            key: metadata[key] for key in metadata if key.startswith("content_")
        }
        assert set(rows) == {self.later, self.current, self.edited, self.historical, self.deleted, self.moved}
        assert (metadata["excluded_no_training_consent_reports"], metadata["excluded_other_region_reports"]) == (1, 1)

        content = {
            report_id: (row["content_provenance"], row["chart_count"], row["content_observed_at"])
            for report_id, row in rows.items()
        }
        assert content[self.later] == ("later_snapshot", 3, LATER_RUN_AT)
        # Empty lists are known zeros; a deleted report, or one now in another team, is unknown.
        assert content[self.current] == ("current_approximation", 0, rows[self.current]["reconstructed_at"])
        assert content[self.deleted] == ("missing", None, None)
        assert content[self.moved] == ("missing", None, None)

        judgments = {
            report_id: (
                row["already_addressed_provenance"],
                row["already_addressed"],
                row["already_addressed_observed_at"],
            )
            for report_id, row in rows.items()
        }
        assert judgments[self.historical] == ("historical", True, BEFORE_CUTOFF)
        # Edited after the cutoff, so its pre-cutoff value is unknown and only its edit is left.
        assert judgments[self.edited] == ("current_approximation", False, AFTER_CUTOFF)
        assert judgments[self.moved] == ("missing", None, None)
        assert judgments[self.deleted] == ("missing", None, None)

    def test_a_frozen_batch_never_changes_and_a_new_batch_keeps_its_own_observation_times(self):
        _run(self.store, "b1")
        first = _batch_rows(self.store, "b1")
        SignalReport.objects.filter(id=self.current).update(charts=[{"id": 1}, {"id": 2}])

        repeat = _run(self.store, "b1")
        _run(self.store, "b2")

        assert repeat["frozen"] is True
        assert _batch_rows(self.store, "b1") == first
        second = _batch_rows(self.store, "b2")
        assert second[self.current]["chart_count"] == 2
        assert second[self.current]["content_observed_at"] > first[self.current]["content_observed_at"]
        for report_id, column in (
            (self.later, "content_observed_at"),
            (self.historical, "already_addressed_observed_at"),
        ):
            assert second[report_id][column] == first[report_id][column]
