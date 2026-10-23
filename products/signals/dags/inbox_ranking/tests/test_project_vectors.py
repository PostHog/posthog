import io
import datetime
from typing import Any

import pytest

import numpy as np
import pandas as pd
import dagster
import pyarrow as pa
import pyarrow.parquet as pq
from parameterized import parameterized

from products.signals.backend.ranking import model_store
from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS
from products.signals.backend.ranking.serving_manifest import (
    SERVED_ROLE,
    ServingManifest,
    ServingManifestEntry,
    serving_engagement_key,
    serving_project_vectors_key,
)
from products.signals.dags.inbox_ranking import common
from products.signals.dags.inbox_ranking.dataset import dag
from products.signals.dags.inbox_ranking.dataset.dag import EMBEDDINGS_SCHEMA, LABELS_SCHEMA
from products.signals.dags.inbox_ranking.dataset.project_vectors import (
    HISTORY_LIMIT,
    LABEL_COLUMNS,
    MIN_HISTORY_REPORTS,
    PROJECT_VECTORS_SCHEMA,
    PROJECT_VECTORS_SCHEMA_VERSION,
    project_vectors,
)
from products.signals.dags.inbox_ranking.multihead.prototype import project_context

AS_OF = datetime.datetime(2026, 7, 30, tzinfo=datetime.UTC)
BEFORE = AS_OF - datetime.timedelta(days=3)
AFTER = AS_OF + datetime.timedelta(hours=1)


def _report_id(team_id: int, index: int) -> str:
    return f"report-{team_id}-{index}"


def _embeddings(reports: list[tuple[int, int, float, datetime.datetime]]) -> pa.Table:
    return pa.Table.from_pylist(
        [
            {
                "snapshot_date": AS_OF.date(),
                "report_id": _report_id(team_id, index),
                "report_team_id": team_id,
                "embedding_small": [value] * EMBEDDING_DIMENSIONS,
                "embedding_inserted_at": inserted_at,
                "embedding_rendering": "title_summary_v1",
                "is_tombstone": False,
            }
            for team_id, index, value, inserted_at in reports
        ],
        schema=EMBEDDINGS_SCHEMA,
    )


def _labels(engagements: list[tuple[int, int, str, datetime.datetime]]) -> pa.Table:
    return pa.Table.from_pylist(
        [
            {"snapshot_date": AS_OF.date(), "report_id": _report_id(team_id, index), column: moment}
            for team_id, index, column, moment in engagements
        ],
        schema=LABELS_SCHEMA,
    )


def _rows_by_key(table: pa.Table) -> dict[tuple[int, str], dict[str, Any]]:
    return {(row["team_id"], row["kind"]): row for row in table.to_pylist()}


@parameterized.expand(
    [
        ("open", "first_opened_at"),
        ("action", "first_implement_clicked_at"),
        ("action", "first_reviewer_removed_at"),
        ("dismiss", "first_ui_dismissed_at"),
    ]
)
def test_only_engagement_and_vectors_before_as_of_enter_a_vector(kind: str, column: str) -> None:
    reports = [(2, index, 1.0, BEFORE) for index in range(MIN_HISTORY_REPORTS)]
    reports += [(2, 100, 9.0, BEFORE), (2, 101, 9.0, AFTER)]
    engagements = [(2, index, column, BEFORE) for index in range(MIN_HISTORY_REPORTS)]
    # Engaged after as_of, and engaged in time with a vector re-embedded after as_of.
    engagements += [(2, 100, column, AFTER), (2, 101, column, BEFORE)]

    rows = _rows_by_key(project_vectors(_labels(engagements), _embeddings(reports), AS_OF))

    assert rows[(2, kind)]["n_reports"] == MIN_HISTORY_REPORTS
    assert rows[(2, kind)]["vector"] == pytest.approx([1.0] * EMBEDDING_DIMENSIONS)
    assert rows[(2, "typical")]["n_reports"] == MIN_HISTORY_REPORTS + 1


def test_vectors_never_mix_teams_and_keep_the_latest_history() -> None:
    history = HISTORY_LIMIT + 3
    reports = [(2, index, float(index < 3), BEFORE) for index in range(history)]
    reports += [(7, index, 5.0, BEFORE) for index in range(MIN_HISTORY_REPORTS)]
    # Team 2's three oldest opens hold the 1.0 vectors, so the latest HISTORY_LIMIT opens average to 0.
    engagements = [
        (2, index, "first_opened_at", BEFORE + datetime.timedelta(minutes=index)) for index in range(history)
    ]
    engagements += [(7, index, "first_opened_at", BEFORE) for index in range(MIN_HISTORY_REPORTS)]

    table = project_vectors(_labels(engagements), _embeddings(reports), AS_OF)
    rows = _rows_by_key(table)

    assert table.schema == PROJECT_VECTORS_SCHEMA
    assert rows[(2, "open")]["n_reports"] == HISTORY_LIMIT
    assert rows[(2, "open")]["vector"] == pytest.approx([0.0] * EMBEDDING_DIMENSIONS)
    assert rows[(2, "typical")]["vector"] == pytest.approx([3 / history] * EMBEDDING_DIMENSIONS)
    assert rows[(7, "open")]["vector"] == pytest.approx([5.0] * EMBEDDING_DIMENSIONS)
    assert rows[(7, "typical")]["vector"] == pytest.approx([5.0] * EMBEDDING_DIMENSIONS)


def test_a_team_below_the_history_threshold_keeps_a_zero_vector_row() -> None:
    thin = MIN_HISTORY_REPORTS - 1
    reports = [(2, index, 1.0, BEFORE) for index in range(thin)]
    engagements = [(2, index, "first_create_pr_clicked_at", BEFORE) for index in range(thin)]

    rows = _rows_by_key(project_vectors(_labels(engagements), _embeddings(reports), AS_OF))

    assert {kind: row["n_reports"] for (_, kind), row in rows.items()} == {
        "typical": thin,
        "open": 0,
        "action": thin,
        "dismiss": 0,
    }
    for row in rows.values():
        assert row["vector"] == [0.0] * EMBEDDING_DIMENSIONS


def test_the_asset_writes_only_teams_opted_in_to_ai_training(monkeypatch) -> None:
    partition_key = (AS_OF.date() - datetime.timedelta(days=1)).isoformat()
    reports = [(team_id, index, 1.0, BEFORE) for team_id in (2, 7) for index in range(MIN_HISTORY_REPORTS)]
    snapshots = {
        common.partition_object_key("inbox_ranking", dag.EMBEDDINGS_TABLE, partition_key): _embeddings(reports),
        common.partition_object_key("inbox_ranking", dag.LABELS_TABLE, partition_key): _labels([]),
    }
    captured: dict[str, Any] = {}

    def fake_write_parquet(client, bucket, key, table, snapshot_date=None, schema_version=None):
        captured.update(key=key, table=table, schema_version=schema_version)

    monkeypatch.setattr(dag, "skip_unconfigured", lambda context: False)
    monkeypatch.setattr(dag, "dataset_bucket", lambda: "test-bucket")
    monkeypatch.setattr(dag, "s3_client", lambda: None)
    monkeypatch.setattr(dag, "read_parquet", lambda client, bucket, key, columns=None: snapshots[key].select(columns))
    monkeypatch.setattr(dag, "write_parquet", fake_write_parquet)
    monkeypatch.setattr(dag, "training_consent_team_ids", lambda: frozenset({7}))
    monkeypatch.setattr(dag.settings, "INBOX_RANKING_DATASET_S3_PREFIX", "inbox_ranking")

    dag.inbox_project_vectors(dagster.build_asset_context(partition_key=partition_key))

    assert captured["key"] == common.partition_object_key("inbox_ranking", dag.PROJECT_VECTORS_TABLE, partition_key)
    assert captured["schema_version"] == PROJECT_VECTORS_SCHEMA_VERSION
    assert set(captured["table"].column("team_id").to_pylist()) == {7}
    assert set(captured["table"].column("as_of").to_pylist()) == {AS_OF}


def test_serving_reads_the_published_day_as_training_builds_it(monkeypatch: pytest.MonkeyPatch) -> None:
    reports = [(2, index, float(index + 1), BEFORE) for index in range(MIN_HISTORY_REPORTS)]
    reports += [(3, 0, 7.0, BEFORE)]
    engagements = [(2, index, "first_opened_at", BEFORE) for index in range(MIN_HISTORY_REPORTS)]
    labels, embeddings = _labels(engagements), _embeddings(reports)
    # Team 4 has no report vector, so the day has no row for it.
    teams = [2, 3, 4]
    rows = pd.DataFrame({"report_team_id": teams, "snapshot_date": [AS_OF.date()] * len(teams)})
    training = project_context(rows, labels, embeddings)

    # A report born on AS_OF's day reads the day before it, whose as_of is AS_OF.
    key = serving_project_vectors_key("inbox_ranking", (AS_OF.date() - datetime.timedelta(days=1)).isoformat())
    buffer = io.BytesIO()
    pq.write_table(project_vectors(labels, embeddings, AS_OF), buffer)
    monkeypatch.setattr(
        model_store.object_storage,
        "read_bytes",
        lambda name, bucket=None, *, missing_ok=False: buffer.getvalue() if name == key else None,
    )
    entry = ServingManifestEntry(
        key="nn@2026-07-29",
        model_name="nn",
        model_version="2026-07-29",
        model_kind="onnx",
        roles=[SERVED_ROLE],
        prefix="inbox_ranking/serving/models/nn@2026-07-29",
        heads=["open"],
        model_file="model.onnx",
        reads_project_vectors=True,
    )
    serving = model_store.load_project_vectors(
        ServingManifest(manifest_version=AS_OF.isoformat(), models=[entry], project_vectors=key), teams
    )

    for position, team_id in enumerate(teams):
        served = serving.for_team(team_id)
        assert served is not None
        pair = training.index[position]
        np.testing.assert_array_equal(served.vectors[0], training.vectors[pair])
        np.testing.assert_array_equal(served.has_history[0], training.has_history[pair])
    assert training.has_history[training.index].tolist() == [[1, 1, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    assert not training.vectors[training.index[2]].any()


LOCAL_REPORT_ID = "00000000-0000-4000-8000-000000000001"
REMOTE_REPORT_ID = "00000000-0000-4000-8000-000000000002"


class _MirrorStorage:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.writes: list[dict[str, Any]] = []

    def write(self, bucket: str, key: str, content: bytes, extras: dict | None) -> None:
        if self.fail:
            raise RuntimeError("mirror unreachable")
        self.writes.append({"bucket": bucket, "key": key, "content": content, "extras": extras})


@pytest.mark.parametrize(
    "mirror_bucket,mirror_fails",
    [("mirror-bucket", False), ("mirror-bucket", True), ("", False)],
    ids=["mirror_set", "mirror_down", "no_mirror"],
)
def test_the_engagement_export_sends_only_remote_reports_to_the_mirror(
    monkeypatch: pytest.MonkeyPatch, mirror_bucket: str, mirror_fails: bool
) -> None:
    partition_key = BEFORE.date().isoformat()
    labels = pa.Table.from_pylist(
        [
            {"snapshot_date": AS_OF.date(), "report_id": report_id, "first_opened_at": BEFORE, "open_count": 1}
            for report_id in (LOCAL_REPORT_ID, REMOTE_REPORT_ID, "not-a-uuid")
        ],
        schema=LABELS_SCHEMA,
    )
    labels_key = common.partition_object_key("inbox_ranking", dag.LABELS_TABLE, partition_key)
    mirror = _MirrorStorage(fail=mirror_fails)
    looked_up: list[list[str]] = []

    def fake_report_teams(report_ids: list[str], snapshot_end: datetime.datetime) -> dict[str, int]:
        looked_up.append(report_ids)
        return {LOCAL_REPORT_ID: 2}

    def mirror_storage() -> _MirrorStorage:
        assert mirror_bucket, "no mirror is set, so nothing may reach a second store"
        return mirror

    monkeypatch.setattr(dag, "skip_unconfigured", lambda context: False)
    monkeypatch.setattr(dag, "dataset_bucket", lambda: "test-bucket")
    monkeypatch.setattr(dag, "s3_client", lambda: None)
    monkeypatch.setattr(
        dag, "read_parquet", lambda client, bucket, key, columns=None: {labels_key: labels}[key].select(columns)
    )
    monkeypatch.setattr(dag, "_report_teams", fake_report_teams)
    monkeypatch.setattr(dag, "serving_mirror_storage", mirror_storage)
    monkeypatch.setattr(dag.settings, "INBOX_RANKING_DATASET_S3_PREFIX", "inbox_ranking")
    monkeypatch.setattr(dag.settings, "INBOX_RANKING_SERVING_MIRROR_BUCKET", mirror_bucket)

    dag.inbox_engagement_export(dagster.build_asset_context(partition_key=partition_key))

    if not mirror_bucket or mirror_fails:
        assert mirror.writes == []
        return
    assert looked_up == [[LOCAL_REPORT_ID, REMOTE_REPORT_ID]]
    (write,) = mirror.writes
    assert write["bucket"] == mirror_bucket
    assert write["key"] == serving_engagement_key("inbox_ranking", partition_key)
    # The mirror bucket is in another account, and its policy refuses a write without this ACL.
    assert write["extras"]["ACL"] == "bucket-owner-full-control"
    assert write["extras"]["Metadata"][common.SCHEMA_VERSION_METADATA_KEY] == str(dag.ENGAGEMENT_EXPORT_SCHEMA_VERSION)
    exported = pq.read_table(io.BytesIO(write["content"]))
    assert exported.column_names == list(LABEL_COLUMNS)
    assert exported.to_pylist() == [
        dict.fromkeys(LABEL_COLUMNS) | {"report_id": REMOTE_REPORT_ID, "first_opened_at": BEFORE}
    ]
