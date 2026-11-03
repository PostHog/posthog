import datetime

import pytest

import numpy as np
import pandas as pd
import pyarrow as pa

from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS
from products.signals.dags.inbox_ranking.dataset.dag import EMBEDDINGS_SCHEMA, LABELS_SCHEMA
from products.signals.dags.inbox_ranking.dataset.project_vectors import HISTORY_LIMIT, MIN_HISTORY_REPORTS, VECTOR_KINDS
from products.signals.dags.inbox_ranking.multihead.inputs import NetworkConfig
from products.signals.dags.inbox_ranking.multihead.local import report_vectors
from products.signals.dags.inbox_ranking.multihead.prototype import (
    ABLATIONS,
    CHAMPION_RECIPE,
    FEATURE_SET,
    PROTOTYPE_HEADS,
    example_table,
    project_context,
    run_prototype,
)
from products.signals.dags.inbox_ranking.training.examples import Snapshot, cap_examples, example_moments, holdout_mask
from products.signals.dags.inbox_ranking.training.heads import ACTION_LABEL_COLUMNS

D0 = datetime.date(2026, 8, 1)
DAYS = 49
REPORTS_PER_DAY = 12
HOLDOUT_DAYS = 7
TEAMS = (2, 3)
# One latent outcome per head, each written into its own component of the report vector, so a
# network that reads one head's output for another head ranks at chance.
HEAD_COMPONENTS = {"open": 0, "action": 1, "fixed": 2}
# Cycled by position rather than drawn, so the random vectors stay the same.
PRIORITIES = ("P0", "P1", "P2", "P3", "P4", None)


def _birth(day: int) -> pd.Timestamp:
    birth = pd.Timestamp(datetime.datetime.combine(D0, datetime.time(12), tzinfo=datetime.UTC)) + pd.Timedelta(days=day)
    assert isinstance(birth, pd.Timestamp)
    return birth


class _SyntheticInbox:
    def __init__(self, seed: int = 0) -> None:
        rng = np.random.default_rng(seed)
        self.reports = pd.DataFrame(
            [
                {
                    "report_id": f"r-{day}-{index}",
                    "born": day,
                    "team": TEAMS[index % len(TEAMS)],
                    "priority": PRIORITIES[index % len(PRIORITIES)],
                    **{head: bool(rng.random() < 0.4) for head in HEAD_COMPONENTS},
                }
                for day in range(DAYS)
                for index in range(REPORTS_PER_DAY)
            ]
        ).set_index("report_id")
        vectors = rng.normal(0.0, 0.3, size=(len(self.reports), EMBEDDING_DIMENSIONS))
        for head, component in HEAD_COMPONENTS.items():
            vectors[:, component] += np.where(self.reports[head], 3.0, -3.0)
        self.vectors = (vectors / np.linalg.norm(vectors, axis=1, keepdims=True)).astype(np.float32)

    def snapshots(self) -> dict[datetime.date, Snapshot]:
        snapshots: dict[datetime.date, Snapshot] = {}
        for day in range(DAYS):
            live = self.reports[self.reports["born"] <= day]
            state = pd.DataFrame(
                {
                    "report_created_at": [_birth(born) for born in live["born"]],
                    "report_age_hours": (day - live["born"]) * 24.0 + 12.0,
                    "signal_count": 1,
                    "report_team_id": live["team"],
                    "priority": live["priority"],
                },
                index=live.index,
            )
            # Every outcome lands the day after the report is born, inside every head's horizon.
            visible = live["born"] < day
            labels = pd.DataFrame(
                {
                    "open_count": (live["open"] & visible).astype(int),
                    "fixed_count": (live["fixed"] & visible).astype(int),
                    **dict.fromkeys(ACTION_LABEL_COLUMNS, 0),
                },
                index=live.index,
            )
            labels["claim_count"] = (live["action"] & visible).astype(int)
            date = D0 + datetime.timedelta(days=day)
            snapshots[date] = Snapshot(date=date, state=state, labels=labels)
        return snapshots

    def embeddings(self) -> pa.Table:
        return pa.Table.from_pylist(
            [
                {
                    "snapshot_date": D0 + datetime.timedelta(days=DAYS - 1),
                    "report_id": report_id,
                    "report_team_id": int(row["team"]),
                    "embedding_small": vector.tolist(),
                    "embedding_inserted_at": _birth(int(row["born"])).to_pydatetime(),
                    "embedding_rendering": "title_summary_v1",
                    "is_tombstone": False,
                }
                for (report_id, row), vector in zip(self.reports.iterrows(), self.vectors, strict=True)
            ],
            schema=EMBEDDINGS_SCHEMA,
        )

    def labels(self) -> pa.Table:
        return pa.Table.from_pylist(
            [
                {
                    "snapshot_date": D0 + datetime.timedelta(days=DAYS - 1),
                    "report_id": report_id,
                    "first_opened_at": (_birth(int(row["born"])) + pd.Timedelta(days=1)).to_pydatetime()
                    if row["open"]
                    else None,
                }
                for report_id, row in self.reports.iterrows()
            ],
            schema=LABELS_SCHEMA,
        )


def test_example_table_keeps_each_champion_holdout_and_trains_the_network_on_none_of_them() -> None:
    inbox = _SyntheticInbox()
    snapshots = inbox.snapshots()
    extras = report_vectors(inbox.embeddings())

    table = example_table(snapshots, extras, holdout_days=HOLDOUT_DAYS)

    train_reports = set(table.rows["report_id"].iloc[table.network_train_rows()])
    any_holdout: set[str] = set()
    for index, head in enumerate(PROTOTYPE_HEADS):
        moments = cap_examples(example_moments(snapshots, head, FEATURE_SET, extras), FEATURE_SET.max_examples_per_head)
        champion_holdout = set(moments["report_id"][holdout_mask(moments, HOLDOUT_DAYS).to_numpy()])
        assert set(table.rows["report_id"].iloc[table.head_rows(index, holdout=True)]) == champion_holdout
        any_holdout |= champion_holdout
    # A fixed-head holdout report is a train row for open, which has the shorter horizon.
    assert any_holdout - set(table.rows["report_id"].iloc[table.head_rows(0, holdout=True)])
    assert train_reports
    assert not train_reports & any_holdout


def test_project_context_reads_the_team_history_from_before_the_birth_day() -> None:
    inbox = _SyntheticInbox()
    birth_day = 20
    rows = pd.DataFrame(
        {
            "report_id": ["new-2", "new-3"],
            "snapshot_date": [D0 + datetime.timedelta(days=birth_day)] * 2,
            "report_team_id": [2, 3],
        }
    )

    context = project_context(rows, inbox.labels(), inbox.embeddings())

    open_kind = VECTOR_KINDS.index("open")
    for row, team in enumerate((2, 3)):
        # Opens land a day after birth, so a report born the day before `birth_day` is opened on
        # `birth_day` itself, after the 00:00 cut, and stays out of the mean.
        opened_before = inbox.reports[
            (inbox.reports["team"] == team) & inbox.reports["open"] & (inbox.reports["born"] < birth_day - 1)
        ]
        assert MIN_HISTORY_REPORTS <= len(opened_before) <= HISTORY_LIMIT
        positions = [inbox.reports.index.get_loc(report_id) for report_id in opened_before.index]
        expected = inbox.vectors[positions].mean(axis=0)
        pair = context.index[row]
        np.testing.assert_allclose(context.vectors[pair, open_kind], expected, atol=1e-6)
        assert context.has_history[pair, open_kind] == 1.0


def test_every_model_is_graded_on_the_champion_holdout_rows_and_each_head_reads_its_own_output() -> None:
    pytest.importorskip("torch")
    inbox = _SyntheticInbox()
    embeddings = inbox.embeddings()

    result = run_prototype(
        inbox.snapshots(),
        report_vectors(embeddings),
        labels=inbox.labels(),
        embeddings=embeddings,
        holdout_days=HOLDOUT_DAYS,
        config=NetworkConfig(projection_dim=8, trunk_dim=8, dropout=0.1, epochs=40, batch_size=32),
    )

    for head in PROTOTYPE_HEADS:
        scores = {score.model: score for score in result.scores if score.head == head.name}
        assert set(scores) == {CHAMPION_RECIPE, *ABLATIONS}
        assert len({(score.holdout_rows, score.holdout_positives) for score in scores.values()}) == 1
        for ablation in ABLATIONS:
            auc = scores[ablation].auc
            assert auc is not None and auc > 0.75
