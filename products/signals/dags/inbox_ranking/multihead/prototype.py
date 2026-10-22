"""Offline test of one multi-head network against the per-head XGBoost champion recipe.

Dev only: nothing here is a dag, writes an object, or reaches serving. It answers one question
before anyone builds a new model family: does a shared network over the report vector, with or
without the team's project vectors, beat the `report_embeddings` boosters on the same rows?

The rows are the training dag's own. Each head's moments come from `example_moments` over the
`report_embeddings` set, capped by `cap_examples` and split by `holdout_mask`, so every head's
cohort, horizon, row budget and holdout are the ones its champion is graded on. The champion
recipe (`XGB_PARAMS`, one booster per head, fit on that head's train rows) is refit on the same
split rather than loaded, because a saved champion was fit on a window that can overlap this
holdout.

The network trains on one row per report with a label per head, NaN where the head has no example.
A report in any head's holdout is left out of the network's training rows for every head. Without
that rule a report in the `fixed` holdout (born three weeks ago) would train the shared trunk
through its `open` label, which is an outcome that serving cannot see at birth. The champion recipe
keeps those rows, so the comparison is conservative for the network.

Project vectors come from `project_vectors()` over the newest labels and embeddings snapshots. A
report born on day D reads the vectors as of D 00:00 UTC, the dt=D−1 vectors serving would read.
"""

import datetime
from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd
import pyarrow as pa
import xgboost as xgb
from sklearn.metrics import average_precision_score, roc_auc_score

from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import (
    EMBEDDING_DIMENSIONS,
    PRIORITY_COLUMN,
    REPORT_EMBEDDINGS_FEATURE_SET,
    Extras,
    FeatureSet,
    project_inputs,
)
from products.signals.dags.inbox_ranking.common import snapshot_bounds
from products.signals.dags.inbox_ranking.dataset.project_vectors import VECTOR_KINDS, project_vectors
from products.signals.dags.inbox_ranking.multihead.inputs import NetworkConfig, NetworkInputs, ProjectContext
from products.signals.dags.inbox_ranking.training.calibration import calibration_buckets, expected_calibration_error
from products.signals.dags.inbox_ranking.training.examples import Snapshot, cap_examples, example_moments, holdout_mask
from products.signals.dags.inbox_ranking.training.heads import HEADS_BY_NAME, Head
from products.signals.dags.inbox_ranking.training.within_team import within_team_auc

# The per-head booster settings the retired `report_embeddings_v2` family trained with.
XGB_PARAMS: dict[str, object] = {
    "n_estimators": 200,
    "max_depth": 4,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 5,
    "eval_metric": "auc",
    "n_jobs": 2,
}
PROTOTYPE_HEADS: tuple[Head, ...] = tuple(HEADS_BY_NAME[name] for name in ("open", "action", "fixed"))
FEATURE_SET = REPORT_EMBEDDINGS_FEATURE_SET

CHAMPION_RECIPE = "champion_recipe"
REPORT_ONLY = "nn_report"
WITH_PROJECT_VECTORS = "nn_report_project"
ABLATIONS = (REPORT_ONLY, WITH_PROJECT_VECTORS)


@frozen
class ExampleTable:
    """One row per report moment, with a label and a holdout flag per head in `PROTOTYPE_HEADS` order."""

    # report_id, snapshot_date, report_team_id, and priority when the snapshots carry it.
    rows: pd.DataFrame
    # (rows, heads) float32, NaN where the head has no example for the row.
    labels: np.ndarray
    # (rows, heads) bool, the head's own `holdout_mask`.
    holdout: np.ndarray

    def network_train_rows(self) -> np.ndarray:
        """Rows with a label for some head and in no head's holdout."""
        observed = ~np.isnan(self.labels)
        return np.flatnonzero(observed.any(axis=1) & ~self.holdout.any(axis=1))

    def head_rows(self, head_index: int, *, holdout: bool) -> np.ndarray:
        observed = ~np.isnan(self.labels[:, head_index])
        in_holdout = self.holdout[:, head_index]
        return np.flatnonzero(observed & (in_holdout if holdout else ~in_holdout))

    def team_ids(self, rows: np.ndarray) -> np.ndarray:
        return self.rows["report_team_id"].to_numpy(dtype=object)[rows]


def example_table(
    snapshots: Mapping[datetime.date, Snapshot],
    extras: Extras,
    *,
    holdout_days: int,
    head_moments: Mapping[str, pd.DataFrame] | None = None,
) -> ExampleTable:
    """The moments of every prototype head, joined on the report moment. `head_moments` holds each
    head's capped moments by name, when the caller already built them."""
    frames = []
    for head in PROTOTYPE_HEADS:
        if head_moments is not None:
            moments = head_moments[head.name]
        else:
            moments = cap_examples(
                example_moments(snapshots, head, FEATURE_SET, extras), FEATURE_SET.max_examples_per_head
            )
        frames.append(
            moments.assign(holdout=holdout_mask(moments, holdout_days).to_numpy())
            .set_index(["report_id", "snapshot_date"])[["label", "holdout"]]
            .add_prefix(f"{head.name}:")
        )
    joined = pd.concat(frames, axis=1, join="outer").sort_index()
    rows = joined.index.to_frame(index=False)
    rows["report_team_id"] = [snapshots[date].state.at[report_id, "report_team_id"] for report_id, date in joined.index]
    if all(PRIORITY_COLUMN in snapshot.state for snapshot in snapshots.values()):
        # Read per row from its own snapshot, so a moment carries the priority it had then.
        rows[PRIORITY_COLUMN] = [
            _priority_or_none(snapshots[date].state.at[report_id, PRIORITY_COLUMN]) for report_id, date in joined.index
        ]
    labels = np.column_stack([joined[f"{head.name}:label"].to_numpy(dtype=np.float32) for head in PROTOTYPE_HEADS])
    holdout = np.column_stack([joined[f"{head.name}:holdout"].eq(True).to_numpy() for head in PROTOTYPE_HEADS])
    return ExampleTable(rows=rows, labels=labels, holdout=holdout)


def _priority_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def report_matrix(rows: pd.DataFrame, extras: Extras, feature_set: FeatureSet = FEATURE_SET) -> np.ndarray:
    """(rows, features) float32 report inputs, built by the set's own `build_matrix` at each row's
    moment, so a row carries the vector its champion example carries. The set's state columns come
    from `rows`, and a set raises when one is missing."""
    matrix = np.empty((len(rows), len(feature_set.feature_names)), dtype=np.float32)
    state_columns = [column for column in feature_set.state_columns if column in rows]
    for date, group in rows.groupby("snapshot_date", sort=True):
        _, snapshot_end = snapshot_bounds(date.isoformat())
        frame = pd.DataFrame(
            {column: group[column].to_numpy() for column in state_columns},
            index=pd.Index(group["report_id"], name="report_id"),
        )
        matrix[group.index.to_numpy()] = feature_set.build_matrix(frame, extras, as_of=snapshot_end).to_numpy(
            dtype=np.float32
        )
    return matrix


def project_context(rows: pd.DataFrame, labels: pa.Table, embeddings: pa.Table) -> ProjectContext:
    """The project vectors each row reads: its team's, as of the start of its snapshot day.

    One `project_vectors()` call per snapshot day, and only the needed teams' rows are kept from it,
    so the context holds a vector per (team, day) rather than one per example row. `project_inputs`
    turns a day into vectors, the same function the scoring sweep reads the published day with.
    """
    kinds = len(VECTOR_KINDS)
    pair_keys = rows[["report_team_id", "snapshot_date"]].drop_duplicates().reset_index(drop=True)
    vectors = np.zeros((len(pair_keys), kinds, EMBEDDING_DIMENSIONS), dtype=np.float32)
    has_history = np.zeros((len(pair_keys), kinds), dtype=np.float32)
    pair_of: dict[tuple[int, datetime.date], int] = {}
    for date, group in pair_keys.groupby("snapshot_date", sort=True):
        as_of, _ = snapshot_bounds(date.isoformat())
        pairs = group.index.to_numpy()
        team_ids = [int(team_id) for team_id in group["report_team_id"]]
        pair_of.update({(team_id, date): int(pair) for team_id, pair in zip(team_ids, pairs, strict=True)})
        day = project_inputs(project_vectors(labels, embeddings, as_of).to_pandas(), team_ids)
        vectors[pairs] = day.vectors
        has_history[pairs] = day.has_history
    index = np.array(
        [pair_of[(int(team_id), date)] for team_id, date in zip(rows["report_team_id"], rows["snapshot_date"])],
        dtype=np.int64,
    )
    return ProjectContext(vectors=vectors, has_history=has_history, index=index)


@frozen
class HeadScore:
    model: str
    head: str
    holdout_rows: int
    holdout_positives: int
    auc: float | None
    # The AUC over pairs inside one team. A model that only learns which teams engage a lot
    # gains pooled `auc` and none of this.
    within_team_auc: float | None
    average_precision: float | None
    expected_calibration_error: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "head": self.head,
            "holdout_rows": self.holdout_rows,
            "holdout_positives": self.holdout_positives,
            "auc": self.auc,
            "within_team_auc": self.within_team_auc,
            "average_precision": self.average_precision,
            "expected_calibration_error": self.expected_calibration_error,
        }


def grade(model: str, head: str, outcomes: np.ndarray, scores: np.ndarray, team_ids: np.ndarray) -> HeadScore:
    """Pooled and within-team AUC, average precision and ECE, with the same decile cut the training
    dag grades on."""
    positives = int(outcomes.sum())
    two_classes = 0 < positives < len(outcomes)
    return HeadScore(
        model=model,
        head=head,
        holdout_rows=len(outcomes),
        holdout_positives=positives,
        auc=float(roc_auc_score(outcomes, scores)) if two_classes else None,
        within_team_auc=within_team_auc(outcomes, scores, team_ids).auc,
        average_precision=float(average_precision_score(outcomes, scores)) if two_classes else None,
        expected_calibration_error=expected_calibration_error(calibration_buckets(outcomes.astype(bool), scores)),
    )


def champion_recipe_scores(table: ExampleTable, reports: np.ndarray, *, seed: int) -> list[HeadScore]:
    """One `XGB_PARAMS` booster per head, fit on the head's train rows and graded on its holdout."""
    scores: list[HeadScore] = []
    for head_index, head in enumerate(PROTOTYPE_HEADS):
        train = table.head_rows(head_index, holdout=False)
        test = table.head_rows(head_index, holdout=True)
        y_train = table.labels[train, head_index].astype(int)
        y_test = table.labels[test, head_index].astype(int)
        if len(test) == 0 or y_train.sum() in (0, len(y_train)):
            continue
        model = xgb.XGBClassifier(**XGB_PARAMS, random_state=seed)
        model.fit(reports[train], y_train, verbose=False)
        scores.append(
            grade(
                CHAMPION_RECIPE,
                head.name,
                y_test,
                model.predict_proba(reports[test])[:, 1],
                table.team_ids(test),
            )
        )
    return scores


def network_scores(
    name: str, table: ExampleTable, inputs: NetworkInputs, config: NetworkConfig
) -> tuple[list[HeadScore], list[float]]:
    """Fit one network on the shared train rows and grade each head on its own holdout."""
    from products.signals.dags.inbox_ranking.multihead.network import (  # noqa: PLC0415 — keeps torch off the import path
        MultiHeadNetwork,
    )

    network = MultiHeadNetwork(
        heads=[head.name for head in PROTOTYPE_HEADS],
        with_context=inputs.context is not None,
        kinds=len(VECTOR_KINDS),
        config=config,
    )
    losses = network.fit(inputs, table.labels, table.network_train_rows())
    scores: list[HeadScore] = []
    for head_index, head in enumerate(PROTOTYPE_HEADS):
        test = table.head_rows(head_index, holdout=True)
        if len(test) == 0:
            continue
        predicted = network.predict(inputs, test)[:, head_index]
        scores.append(
            grade(name, head.name, table.labels[test, head_index].astype(int), predicted, table.team_ids(test))
        )
    return scores, losses


@frozen
class PrototypeResult:
    scores: tuple[HeadScore, ...]
    network_train_rows: int
    # Mean training loss per epoch, per network.
    losses: Mapping[str, Sequence[float]]

    def as_dict(self) -> dict[str, object]:
        return {
            "scores": [score.as_dict() for score in self.scores],
            "network_train_rows": self.network_train_rows,
            "losses": {name: list(values) for name, values in self.losses.items()},
        }


def run_prototype(
    snapshots: Mapping[datetime.date, Snapshot],
    extras: Extras,
    *,
    labels: pa.Table | None,
    embeddings: pa.Table | None,
    holdout_days: int,
    config: NetworkConfig,
    ablations: Sequence[str] = ABLATIONS,
    champion: bool = True,
) -> PrototypeResult:
    """Every requested model graded per head on the champion's holdout rows.

    `labels` and `embeddings` are the newest labels and embeddings snapshots, needed only by the
    project-vector ablation. `extras` must be built from the same embeddings snapshot, so the run
    holds one set of vectors.
    """
    table = example_table(snapshots, extras, holdout_days=holdout_days)
    reports = report_matrix(table.rows, extras)
    scores: list[HeadScore] = []
    losses: dict[str, list[float]] = {}
    if champion:
        scores += champion_recipe_scores(table, reports, seed=config.seed)
    for ablation in ablations:
        context = None
        if ablation == WITH_PROJECT_VECTORS:
            if labels is None or embeddings is None:
                raise ValueError("the project-vector ablation needs the labels and embeddings snapshots")
            context = project_context(table.rows, labels, embeddings)
        head_scores, losses[ablation] = network_scores(
            ablation, table, NetworkInputs(reports=reports, context=context), config
        )
        scores += head_scores
    return PrototypeResult(scores=tuple(scores), network_train_rows=len(table.network_train_rows()), losses=losses)


def format_scores(scores: Sequence[HeadScore]) -> str:
    """One line per (head, model), the champion recipe first within each head."""

    def number(value: float | None) -> str:
        return "-" if value is None else f"{value:.3f}"

    header = f"{'head':<8}{'model':<20}{'rows':>8}{'pos':>7}{'auc':>8}{'team_auc':>10}{'ap':>8}{'ece':>8}"
    lines = [header, "-" * len(header)]
    order = {name: index for index, name in enumerate((CHAMPION_RECIPE, *ABLATIONS))}
    for head in PROTOTYPE_HEADS:
        for score in sorted((s for s in scores if s.head == head.name), key=lambda s: order.get(s.model, 99)):
            lines.append(
                f"{score.head:<8}{score.model:<20}{score.holdout_rows:>8}{score.holdout_positives:>7}"
                f"{number(score.auc):>8}{number(score.within_team_auc):>10}{number(score.average_precision):>8}"
                f"{number(score.expected_calibration_error):>8}"
            )
    return "\n".join(lines)
