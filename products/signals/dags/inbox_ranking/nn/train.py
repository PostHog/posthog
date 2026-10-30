"""Fit the `nn` family: one multi-head network, graded per head the way the per-head boosters are.

The network trains on the rows in no head's holdout (`ExampleTable.network_train_rows`), and each
head is graded on its own holdout. Readability uses the boosters' rule: a head must clear the mean
holdout AUC of `NULL_PERMUTATIONS` networks fit on permuted labels by `NULL_MARGIN`. The graph that
ships is a refit on every labeled row, as a booster is, and the train-only graph is kept to grade
this model as a later champion.

A pair network fit with a `PairFit` holds the newest train days out as validation rows, stops early
on them, and its refit runs for the epochs the train-only fit kept. It reads the table's loss
weights, and records each head's train, validation and holdout AUC.

This module imports torch through `multihead/network.py`. Import it only inside an asset body.
"""

import tempfile
import dataclasses
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS
from products.signals.dags.inbox_ranking.multihead.inputs import NetworkConfig, NetworkInputs, PairTrainingConfig
from products.signals.dags.inbox_ranking.multihead.network import MultiHeadNetwork, export_onnx
from products.signals.dags.inbox_ranking.multihead.prototype import ExampleTable
from products.signals.dags.inbox_ranking.nn.model import (
    HeadFitAucs,
    NetworkHead,
    PairFitRecord,
    TrainedNetwork,
    network_user_kinds,
    network_vector_kinds,
)
from products.signals.dags.inbox_ranking.training.heads import Head
from products.signals.dags.inbox_ranking.training.train import NULL_PERMUTATIONS, head_metrics


@frozen
class PairFit:
    """A pair network's training settings and the report-input columns its user-input dropout zeroes."""

    config: PairTrainingConfig
    user_columns: tuple[int, ...]


@frozen
class _FitRows:
    # The rows the network fits on.
    fit: np.ndarray
    # The rows early stopping reads, empty without a `PairFit`.
    validation: np.ndarray


def validation_split(table: ExampleTable, train_rows: np.ndarray, share: float) -> _FitRows:
    """The newest `share` of the train rows' report days as validation rows, at least one day, and
    the rest as fit rows. Cut by day like the holdout, so a report never straddles the two and the
    validation rows are the nearest in time to the holdout. A single train day gives no validation."""
    days = table.rows["snapshot_date"].to_numpy()[train_rows]
    unique = np.unique(days)
    if share <= 0 or len(unique) < 2:
        return _FitRows(fit=train_rows, validation=train_rows[:0])
    cut = unique[-max(1, round(share * len(unique)))]
    newest = days >= cut
    return _FitRows(fit=train_rows[~newest], validation=train_rows[newest])


def _fit(
    inputs: NetworkInputs,
    heads: Sequence[Head],
    config: NetworkConfig,
    labels: np.ndarray,
    rows: _FitRows,
    *,
    pair: PairFit | None = None,
    weights: np.ndarray | None = None,
    epochs: int | None = None,
) -> MultiHeadNetwork:
    network = MultiHeadNetwork(
        heads=[head.name for head in heads],
        with_context=inputs.context is not None,
        kinds=len(network_vector_kinds(inputs)),
        config=config,
        report_features=inputs.reports.shape[1] - EMBEDDING_DIMENSIONS,
        user_kinds=inputs.users.vectors.shape[1] if inputs.users is not None else 0,
        pair=pair.config if pair is not None else None,
        user_columns=pair.user_columns if pair is not None else (),
    )
    network.fit(inputs, labels, rows.fit, weights=weights, validation_rows=rows.validation, epochs=epochs)
    return network


def _fit_rows(table: ExampleTable, train_rows: np.ndarray, pair: PairFit | None) -> _FitRows:
    if pair is None:
        return _FitRows(fit=train_rows, validation=train_rows[:0])
    return validation_split(table, train_rows, pair.config.validation_share)


def _onnx_bytes(network: MultiHeadNetwork) -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "model.onnx"
        export_onnx(network, path)
        return path.read_bytes()


def _auc(y: np.ndarray, scores: np.ndarray, weights: np.ndarray | None = None) -> float | None:
    if len(y) == 0 or y.sum() in (0, len(y)):
        return None
    return float(roc_auc_score(y, scores, sample_weight=weights))


@frozen
class GradedHeads:
    holdout_network: MultiHeadNetwork
    trained: list[NetworkHead]
    skipped: list[str]
    pair_fit: PairFitRecord | None = None


def _pair_fit_record(
    table: ExampleTable, heads: Sequence[Head], scores: np.ndarray, rows: _FitRows, epochs_kept: int
) -> PairFitRecord:
    def head_auc(index: int, head_rows: np.ndarray) -> float | None:
        head_rows = head_rows[~np.isnan(table.labels[head_rows, index])]
        weights = table.weights[head_rows, index] if table.weights is not None else None
        return _auc(table.labels[head_rows, index].astype(int), scores[head_rows, index], weights)

    return PairFitRecord(
        epochs_kept=epochs_kept,
        fit_rows=len(rows.fit),
        validation_rows=len(rows.validation),
        heads=tuple(
            HeadFitAucs(
                head=head.name,
                train_auc=head_auc(index, rows.fit),
                validation_auc=head_auc(index, rows.validation),
                holdout_auc=head_auc(index, table.head_rows(index, holdout=True)),
            )
            for index, head in enumerate(heads)
        ),
    )


def _graded_heads(
    table: ExampleTable,
    inputs: NetworkInputs,
    heads: Sequence[Head],
    config: NetworkConfig,
    train_rows: np.ndarray,
    pair: PairFit | None = None,
) -> GradedHeads:
    """The train-only network, each head it can grade, and each head with nothing to fit."""
    all_rows = np.arange(len(inputs))
    rows = _fit_rows(table, train_rows, pair)
    holdout_network = _fit(inputs, heads, config, table.labels, rows, pair=pair, weights=table.weights)
    scores = holdout_network.predict(inputs, all_rows)
    rng = np.random.default_rng(config.seed)
    null_scores = []
    for draw in range(NULL_PERMUTATIONS):
        order = rng.permutation(train_rows)
        permuted = table.labels.copy()
        permuted[train_rows] = table.labels[order]
        permuted_weights = None
        if table.weights is not None:
            permuted_weights = table.weights.copy()
            permuted_weights[train_rows] = table.weights[order]
        null_config = dataclasses.replace(config, seed=config.seed + draw)
        null_scores.append(
            _fit(inputs, heads, null_config, permuted, rows, pair=pair, weights=permuted_weights).predict(
                inputs, all_rows
            )
        )

    trained: list[NetworkHead] = []
    skipped: list[str] = []
    for index, head in enumerate(heads):
        observed = ~np.isnan(table.labels[:, index])
        head_train = train_rows[observed[train_rows]]
        test = table.head_rows(index, holdout=True)
        y_train = table.labels[head_train, index].astype(int)
        if len(y_train) == 0 or y_train.sum() in (0, len(y_train)):
            skipped.append(head.name)
            continue
        y_test = table.labels[test, index].astype(int)
        null_aucs: list[float] = []
        if _auc(y_test, scores[test, index]) is not None:
            null_aucs = [auc for draws in null_scores if (auc := _auc(y_test, draws[test, index])) is not None]
        metrics, calibration = head_metrics(
            head,
            y_train=y_train,
            train_scores=scores[head_train, index],
            y_test=y_test,
            holdout_scores=scores[test, index],
            null_aucs=null_aucs,
            refit_positive_rate=float(table.labels[observed, index].mean()),
            holdout_team_ids=table.team_ids(test),
        )
        trained.append(NetworkHead(metrics=metrics, calibration=calibration))
    return GradedHeads(
        holdout_network=holdout_network,
        trained=trained,
        skipped=skipped,
        pair_fit=(
            _pair_fit_record(table, heads, scores, rows, holdout_network.epochs_kept) if pair is not None else None
        ),
    )


def train_network(
    table: ExampleTable,
    inputs: NetworkInputs,
    heads: Sequence[Head],
    config: NetworkConfig,
    pair: PairFit | None = None,
) -> TrainedNetwork:
    """`heads` is the column order of `table`'s labels and of the graphs' output."""
    output_heads = tuple(head.name for head in heads)
    train_rows = table.network_train_rows()
    refit_rows = np.flatnonzero((~np.isnan(table.labels)).any(axis=1))
    graded = _graded_heads(table, inputs, heads, config, train_rows, pair) if len(train_rows) else None
    trained = graded.trained if graded is not None else []
    skipped = graded.skipped if graded is not None else list(output_heads)
    model_onnx = holdout_model_onnx = None
    if graded is not None and trained:
        # Refit on everything before shipping: the holdout only exists to grade the recipe. With
        # nothing left to validate on, the refit runs the epochs the train-only fit kept.
        refit = _fit(
            inputs,
            heads,
            config,
            table.labels,
            _FitRows(fit=refit_rows, validation=refit_rows[:0]),
            pair=pair,
            weights=table.weights,
            epochs=graded.holdout_network.epochs_kept if pair is not None else None,
        )
        model_onnx = _onnx_bytes(refit)
        holdout_model_onnx = _onnx_bytes(graded.holdout_network)
    return TrainedNetwork(
        output_heads=output_heads,
        model_onnx=model_onnx,
        holdout_model_onnx=holdout_model_onnx,
        heads=tuple(trained),
        skipped=tuple(skipped),
        network_train_rows=len(train_rows),
        refit_rows=len(refit_rows),
        vector_kinds=network_vector_kinds(inputs),
        user_vector_kinds=network_user_kinds(inputs),
        pair_fit=graded.pair_fit if graded is not None else None,
    )


def seed_networks(
    table: ExampleTable,
    inputs: NetworkInputs,
    heads: Sequence[Head],
    config: NetworkConfig,
    seeds: Sequence[int],
    train_rows: np.ndarray | None = None,
    pair: PairFit | None = None,
) -> list[MultiHeadNetwork]:
    """One train-only fit per seed. `train_rows` defaults to the table's network train rows; the
    pair lane's report-level reference narrows them to the pair train days."""
    if train_rows is None:
        train_rows = table.network_train_rows()
    rows = _fit_rows(table, train_rows, pair)
    return [
        _fit(
            inputs, heads, dataclasses.replace(config, seed=seed), table.labels, rows, pair=pair, weights=table.weights
        )
        for seed in seeds
    ]


def seed_scores(
    table: ExampleTable,
    inputs: NetworkInputs,
    heads: Sequence[Head],
    config: NetworkConfig,
    seeds: Sequence[int],
    train_rows: np.ndarray | None = None,
    pair: PairFit | None = None,
) -> list[np.ndarray]:
    """One train-only fit per seed, each scoring every row. Two arms fit with the same seeds on the
    same rows give the paired scores `vs_baseline_block` grades."""
    all_rows = np.arange(len(inputs))
    return [
        network.predict(inputs, all_rows)
        for network in seed_networks(table, inputs, heads, config, seeds, train_rows, pair)
    ]
