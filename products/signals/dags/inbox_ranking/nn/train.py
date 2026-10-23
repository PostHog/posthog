"""Fit the `nn` family: one multi-head network, graded per head the way the per-head boosters are.

The network trains on the rows in no head's holdout (`ExampleTable.network_train_rows`), and each
head is graded on its own holdout. Readability uses the boosters' rule: a head must clear the mean
holdout AUC of `NULL_PERMUTATIONS` networks fit on permuted labels by `NULL_MARGIN`. The graph that
ships is a refit on every labeled row, as a booster is, and the train-only graph is kept to grade
this model as a later champion.

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
from products.signals.dags.inbox_ranking.dataset.project_vectors import VECTOR_KINDS
from products.signals.dags.inbox_ranking.multihead.inputs import NetworkConfig, NetworkInputs
from products.signals.dags.inbox_ranking.multihead.network import MultiHeadNetwork, export_onnx
from products.signals.dags.inbox_ranking.multihead.prototype import ExampleTable
from products.signals.dags.inbox_ranking.nn.model import NetworkHead, TrainedNetwork, network_vector_kinds
from products.signals.dags.inbox_ranking.training.heads import Head
from products.signals.dags.inbox_ranking.training.train import NULL_PERMUTATIONS, head_metrics


def _fit(
    inputs: NetworkInputs, heads: Sequence[Head], config: NetworkConfig, labels: np.ndarray, rows: np.ndarray
) -> MultiHeadNetwork:
    network = MultiHeadNetwork(
        heads=[head.name for head in heads],
        with_context=inputs.context is not None,
        kinds=len(VECTOR_KINDS),
        config=config,
        report_features=inputs.reports.shape[1] - EMBEDDING_DIMENSIONS,
    )
    network.fit(inputs, labels, rows)
    return network


def _onnx_bytes(network: MultiHeadNetwork) -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "model.onnx"
        export_onnx(network, path)
        return path.read_bytes()


def _auc(y: np.ndarray, scores: np.ndarray) -> float | None:
    if len(y) == 0 or y.sum() in (0, len(y)):
        return None
    return float(roc_auc_score(y, scores))


@frozen
class GradedHeads:
    holdout_network: MultiHeadNetwork
    trained: list[NetworkHead]
    skipped: list[str]


def _graded_heads(
    table: ExampleTable,
    inputs: NetworkInputs,
    heads: Sequence[Head],
    config: NetworkConfig,
    train_rows: np.ndarray,
) -> GradedHeads:
    """The train-only network, each head it can grade, and each head with nothing to fit."""
    all_rows = np.arange(len(inputs))
    holdout_network = _fit(inputs, heads, config, table.labels, train_rows)
    scores = holdout_network.predict(inputs, all_rows)
    rng = np.random.default_rng(config.seed)
    null_scores = []
    for draw in range(NULL_PERMUTATIONS):
        permuted = table.labels.copy()
        permuted[train_rows] = table.labels[rng.permutation(train_rows)]
        null_config = dataclasses.replace(config, seed=config.seed + draw)
        null_scores.append(_fit(inputs, heads, null_config, permuted, train_rows).predict(inputs, all_rows))

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
    return GradedHeads(holdout_network=holdout_network, trained=trained, skipped=skipped)


def train_network(
    table: ExampleTable, inputs: NetworkInputs, heads: Sequence[Head], config: NetworkConfig
) -> TrainedNetwork:
    """`heads` is the column order of `table`'s labels and of the graphs' output."""
    output_heads = tuple(head.name for head in heads)
    train_rows = table.network_train_rows()
    refit_rows = np.flatnonzero((~np.isnan(table.labels)).any(axis=1))
    graded = _graded_heads(table, inputs, heads, config, train_rows) if len(train_rows) else None
    trained = graded.trained if graded is not None else []
    skipped = graded.skipped if graded is not None else list(output_heads)
    model_onnx = holdout_model_onnx = None
    if graded is not None and trained:
        # Refit on everything before shipping: the holdout only exists to grade the recipe.
        model_onnx = _onnx_bytes(_fit(inputs, heads, config, table.labels, refit_rows))
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
    )


def seed_scores(
    table: ExampleTable, inputs: NetworkInputs, heads: Sequence[Head], config: NetworkConfig, seeds: Sequence[int]
) -> list[np.ndarray]:
    """One train-only fit per seed, each scoring every row. Two arms fit with the same seeds on the
    same rows give the paired scores `vs_baseline_block` grades."""
    train_rows = table.network_train_rows()
    all_rows = np.arange(len(inputs))
    return [
        _fit(inputs, heads, dataclasses.replace(config, seed=seed), table.labels, train_rows).predict(inputs, all_rows)
        for seed in seeds
    ]
