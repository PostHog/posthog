import datetime
from typing import Any

import pytest

import dagster
import pyarrow as pa
from parameterized import parameterized

from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS
from products.signals.dags.inbox_ranking import common
from products.signals.dags.inbox_ranking.dataset import dag
from products.signals.dags.inbox_ranking.dataset.dag import EMBEDDINGS_SCHEMA, LABELS_SCHEMA
from products.signals.dags.inbox_ranking.dataset.project_vectors import (
    HISTORY_LIMIT,
    MIN_HISTORY_REPORTS,
    PROJECT_VECTORS_SCHEMA,
    PROJECT_VECTORS_SCHEMA_VERSION,
    project_vectors,
)

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
