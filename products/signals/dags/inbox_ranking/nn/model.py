"""The `nn` families' model record and its ONNX scoring, without torch.

A candidate is two ONNX graphs under `inbox_ranking_models/v1/<model_name>/dt=D/`: `model.onnx`, the refit on
every labeled row that a store serves, and `model.holdout.onnx`, the train-only fit that produced the
holdout metrics. A later candidate grades the champion through the second one on its own holdout,
as the per-head families grade a champion through `<head>.holdout.ubj`.
"""

import datetime
import dataclasses
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from posthog import settings
from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import (
    DAYS_SINCE_LAST_VIEW_CAP,
    USER_HISTORY_KINDS,
    PairUserHistoryFeatureSet,
)
from products.signals.backend.ranking.model_store import ONNX_OUTPUT_HEADS_KEY
from products.signals.backend.ranking.serving_manifest import ONNX_MODEL_FILE, ONNX_MODEL_KIND
from products.signals.dags.inbox_ranking.common import DATASET_VERSION
from products.signals.dags.inbox_ranking.dataset.project_vectors import USER_HISTORY_LIMIT
from products.signals.dags.inbox_ranking.dataset.queries import LABELS_TEAM_ID
from products.signals.dags.inbox_ranking.multihead.inputs import ONNX_INPUTS, ONNX_OUTPUT, NetworkConfig, NetworkInputs
from products.signals.dags.inbox_ranking.multihead.prototype import ExampleTable
from products.signals.dags.inbox_ranking.nn.examples import NN_HEAD_NAMES, NN_HEADS
from products.signals.dags.inbox_ranking.training.calibration import CalibrationBucket
from products.signals.dags.inbox_ranking.training.families import PAIR_GRAIN, ModelFamily
from products.signals.dags.inbox_ranking.training.heads import HEADS_BY_NAME, Head
from products.signals.dags.inbox_ranking.training.recipe import model_recipe, with_recipe
from products.signals.dags.inbox_ranking.training.train import HeadMetrics, HoldoutGrade, _auc, holdout_grade
from products.signals.dags.inbox_ranking.training.within_team import within_team_auc

HOLDOUT_MODEL_FILE = "model.holdout.onnx"


@frozen
class NetworkHead:
    metrics: HeadMetrics
    calibration: tuple[CalibrationBucket, ...]


@frozen
class TrainedNetwork:
    # The graphs' output columns, in order. Every head the network was fit on has a column, a
    # skipped head included.
    output_heads: tuple[str, ...]
    # None when no head had anything to fit.
    model_onnx: bytes | None
    holdout_model_onnx: bytes | None
    heads: tuple[NetworkHead, ...]
    skipped: tuple[str, ...]
    network_train_rows: int
    refit_rows: int
    # The project-vector kinds the graphs take, empty for a report-only network.
    vector_kinds: tuple[str, ...]
    # The user-history kinds the graphs take, empty for a network without a `user` input.
    user_vector_kinds: tuple[str, ...] = ()


def network_vector_kinds(inputs: NetworkInputs) -> tuple[str, ...]:
    """The project-vector kinds a network fit on `inputs` takes, empty for a report-only network."""
    return inputs.context.kinds if inputs.context is not None else ()


def network_user_kinds(inputs: NetworkInputs) -> tuple[str, ...]:
    """The user-history kinds a network fit on `inputs` takes, empty for a network without them."""
    return USER_HISTORY_KINDS if inputs.users is not None else ()


def family_user_kinds(family: ModelFamily) -> tuple[str, ...]:
    """The user-history kinds the pair lane gives a `family` network. A pair set's network takes
    them even when the set holds them at zero, so the two arms of a comparison share one shape."""
    return USER_HISTORY_KINDS if isinstance(family.feature_set, PairUserHistoryFeatureSet) else ()


def family_heads(family: ModelFamily) -> tuple[Head, ...]:
    """The heads a `family` network is fit on, in its label and output column order."""
    if family.grain == PAIR_GRAIN:
        return tuple(HEADS_BY_NAME[name] for name in family.heads)
    return NN_HEADS


def network_recipe(
    family: ModelFamily,
    config: NetworkConfig,
    vector_kinds: Sequence[str],
    pair_settings: Mapping[str, Any] | None = None,
    *,
    user_vector_kinds: Sequence[str] = (),
) -> dict[str, Any]:
    """`pair_settings` is the pair examples' label horizon and schema, and `user_vector_kinds` the
    user-history kinds the graphs take, both for a pair-grain family only, so a report-grain family's
    recipe and hash stay as they were."""
    recipe = model_recipe(
        model_kind=ONNX_MODEL_KIND,
        feature_set=family.feature_set,
        heads=family_heads(family),
        learner_params=dataclasses.asdict(config),
        project_vector_kinds=vector_kinds,
    )
    if family.grain == PAIR_GRAIN:
        recipe = {
            **recipe,
            "grain": PAIR_GRAIN,
            "pair": dict(pair_settings or {}),
            "user_vector_kinds": list(user_vector_kinds),
            # Both change the user inputs, so they matter only to a model that reads user history.
            "user_vector_settings": (
                {"history_limit": USER_HISTORY_LIMIT, "days_since_last_view_cap": DAYS_SINCE_LAST_VIEW_CAP}
                if user_vector_kinds
                else {}
            ),
        }
    return recipe


def candidate_metadata(
    partition_key: str,
    trained: TrainedNetwork,
    *,
    family: ModelFamily,
    config: NetworkConfig,
    windows: Mapping[str, Mapping[str, object]],
    trained_at: datetime.datetime,
    run_id: str,
    pair_settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The `metadata.json` of a `family` candidate, in the layout of the per-head families.

    The heads carry the metric fields of `HeadMetrics`, the fields the per-head booster families
    wrote, so the promotion rule, the events and the manifest read every family alike. A pair-grain
    candidate also records its grain, and its heads carry the pair labels' horizon.
    """
    feature_set = family.feature_set
    metadata = {
        "model_name": family.name,
        "model_version": partition_key,
        "dataset_version": DATASET_VERSION,
        "model_kind": ONNX_MODEL_KIND,
        # The set that builds the `report` input, so the grader and the store check the graph
        # against it like any other family.
        "feature_set": feature_set.name,
        "feature_schema_version": feature_set.schema_version,
        "feature_names": list(feature_set.feature_names),
        ONNX_OUTPUT_HEADS_KEY: list(trained.output_heads),
        "project_vector_kinds": list(trained.vector_kinds),
        "trained_at": trained_at.isoformat(),
        "run_id": run_id,
        "lookback_days": settings.INBOX_RANKING_TRAINING_LOOKBACK_DAYS,
        "holdout_days": settings.INBOX_RANKING_TRAINING_HOLDOUT_DAYS,
        "network_config": dataclasses.asdict(config),
        "network_train_rows": trained.network_train_rows,
        "refit_rows": trained.refit_rows,
        "heads": [
            head.metrics.as_dict()
            | {
                "cohort": HEADS_BY_NAME[head.metrics.head].cohort.__name__,
                "horizon_days": (pair_settings or {}).get(
                    "label_horizon_days", HEADS_BY_NAME[head.metrics.head].horizon_days
                ),
                "example_window_start": windows.get(head.metrics.head, {}).get("example_window_start"),
                "example_cap_bound": windows.get(head.metrics.head, {}).get("example_cap_bound"),
                "file": ONNX_MODEL_FILE,
                "holdout_file": HOLDOUT_MODEL_FILE,
            }
            for head in trained.heads
        ],
        "skipped_heads": list(trained.skipped),
    }
    if family.grain == PAIR_GRAIN:
        metadata["grain"] = PAIR_GRAIN
        metadata["user_vector_kinds"] = list(trained.user_vector_kinds)
    return with_recipe(
        metadata,
        network_recipe(
            family, config, trained.vector_kinds, pair_settings, user_vector_kinds=trained.user_vector_kinds
        ),
    )


def onnx_probabilities(model: bytes, inputs: NetworkInputs, output_heads: Sequence[str]) -> dict[str, np.ndarray]:
    """Each output head's probability for every row of `inputs`, from a graph `export_onnx` wrote.

    The graph is fed only the inputs it declares, so a report-only graph reads the report vectors
    of a table built with context.
    """
    import onnxruntime as ort  # noqa: PLC0415 — keeps onnxruntime's native runtime off the location's import path

    session = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
    declared = {node.name for node in session.get_inputs()}
    report_input, project_input, history_input, user_input = ONNX_INPUTS
    feeds: dict[str, np.ndarray] = {report_input: np.ascontiguousarray(inputs.reports, dtype=np.float32)}
    if project_input in declared:
        if inputs.context is None:
            raise ValueError("the graph takes project vectors and the inputs carry none")
        pairs = inputs.context.index
        feeds[project_input] = np.ascontiguousarray(inputs.context.vectors[pairs], dtype=np.float32)
        feeds[history_input] = np.ascontiguousarray(inputs.context.has_history[pairs], dtype=np.float32)
    if user_input in declared:
        if inputs.users is None:
            raise ValueError("the graph takes user offsets and the inputs carry none")
        feeds[user_input] = np.ascontiguousarray(inputs.users.vectors[inputs.users.index], dtype=np.float32)
    (probabilities,) = session.run([ONNX_OUTPUT], {name: value for name, value in feeds.items() if name in declared})
    return {head: probabilities[:, column] for column, head in enumerate(output_heads)}


def champion_grades(
    champion: Mapping[str, Any], holdout_model: bytes, table: ExampleTable, inputs: NetworkInputs
) -> dict[str, HoldoutGrade]:
    """The champion's readable heads graded on the candidate's holdout rows of `table`, through the
    champion's train-only graph. `inputs` holds a row for each row of `table`."""
    probabilities = onnx_probabilities(holdout_model, inputs, champion.get(ONNX_OUTPUT_HEADS_KEY) or ())
    grades: dict[str, HoldoutGrade] = {}
    for entry in champion.get("heads", []):
        name = entry.get("head")
        if not entry.get("readable") or name not in probabilities or name not in NN_HEAD_NAMES:
            continue
        index = NN_HEAD_NAMES.index(name)
        rows = table.head_rows(index, holdout=True)
        if len(rows) == 0:
            continue
        grades[name] = holdout_grade(table.labels[rows, index].astype(int), probabilities[name][rows])
    return grades


def _paired(experiment_aucs: Sequence[float | None], baseline_aucs: Sequence[float | None]) -> dict[str, Any]:
    deltas = [
        experiment - base
        for experiment, base in zip(experiment_aucs, baseline_aucs)
        if experiment is not None and base is not None
    ]
    return {
        "experiment_aucs": list(experiment_aucs),
        "baseline_aucs": list(baseline_aucs),
        "paired_seeds": len(deltas),
        "mean_delta_auc": float(np.mean(deltas)) if deltas else None,
        "min_delta_auc": min(deltas) if deltas else None,
        "max_delta_auc": max(deltas) if deltas else None,
        "wins": sum(1 for delta in deltas if delta > 0),
    }


def vs_baseline_block(
    table: ExampleTable,
    *,
    baseline: str,
    seeds: Sequence[int],
    experiment_scores: Sequence[np.ndarray],
    baseline_scores: Sequence[np.ndarray],
) -> dict[str, Any]:
    """The experiment against its baseline, per head, on the same holdout rows.

    Each seed fits both arms on the same train rows, so the two AUCs of one seed form a pair. One
    seed's gap can be noise from the network's initialization alone, so the block keeps the range
    of the gaps across seeds. `within_team` is the read the inbox order depends on, and `pooled` is
    there for reference. `within_team_non_dogfood` leaves out PostHog's own project, whose inbox use
    is not a customer's. A seed where either arm has no AUC drops out of the pairs.
    """
    train_rows = table.network_train_rows()
    heads: dict[str, dict[str, Any]] = {}
    for index, name in enumerate(NN_HEAD_NAMES):
        rows = table.head_rows(index, holdout=True)
        y = table.labels[rows, index].astype(int)
        team_ids = table.team_ids(rows)
        customer = team_ids != LABELS_TEAM_ID
        heads[name] = {
            "train_rows": int((~np.isnan(table.labels[train_rows, index])).sum()),
            "holdout_rows": len(rows),
            "holdout_positives": int(y.sum()),
            "within_team": _paired(
                [within_team_auc(y, scores[rows, index], team_ids).auc for scores in experiment_scores],
                [within_team_auc(y, scores[rows, index], team_ids).auc for scores in baseline_scores],
            ),
            "within_team_non_dogfood": _paired(
                [
                    within_team_auc(y[customer], scores[rows, index][customer], team_ids[customer]).auc
                    for scores in experiment_scores
                ],
                [
                    within_team_auc(y[customer], scores[rows, index][customer], team_ids[customer]).auc
                    for scores in baseline_scores
                ],
            ),
            "pooled": _paired(
                [_auc(y, scores[rows, index]) for scores in experiment_scores],
                [_auc(y, scores[rows, index]) for scores in baseline_scores],
            ),
        }
    return {"baseline": baseline, "seeds": list(seeds), "heads": heads}
