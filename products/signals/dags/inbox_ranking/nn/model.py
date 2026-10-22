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

from products.signals.backend.ranking.model_store import ONNX_OUTPUT_HEADS_KEY
from products.signals.backend.ranking.serving_manifest import ONNX_MODEL_FILE, ONNX_MODEL_KIND
from products.signals.dags.inbox_ranking.common import DATASET_VERSION
from products.signals.dags.inbox_ranking.dataset.project_vectors import VECTOR_KINDS
from products.signals.dags.inbox_ranking.multihead.inputs import ONNX_INPUTS, ONNX_OUTPUT, NetworkConfig, NetworkInputs
from products.signals.dags.inbox_ranking.multihead.prototype import ExampleTable
from products.signals.dags.inbox_ranking.nn.examples import NN_HEAD_NAMES, NN_HEADS
from products.signals.dags.inbox_ranking.training.calibration import CalibrationBucket
from products.signals.dags.inbox_ranking.training.heads import HEADS_BY_NAME
from products.signals.dags.inbox_ranking.training.recipe import model_recipe, with_recipe
from products.signals.dags.inbox_ranking.training.train import HeadMetrics, HoldoutGrade, holdout_grade
from products.signals.dags.inbox_ranking.training.unseen import ModelFamily

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


def network_vector_kinds(inputs: NetworkInputs) -> tuple[str, ...]:
    """The project-vector kinds a network fit on `inputs` takes, empty for a report-only network."""
    return VECTOR_KINDS if inputs.context is not None else ()


def network_recipe(family: ModelFamily, config: NetworkConfig, vector_kinds: Sequence[str]) -> dict[str, Any]:
    return model_recipe(
        model_kind=ONNX_MODEL_KIND,
        feature_set=family.feature_set,
        heads=NN_HEADS,
        learner_params=dataclasses.asdict(config),
        project_vector_kinds=vector_kinds,
    )


def candidate_metadata(
    partition_key: str,
    trained: TrainedNetwork,
    *,
    family: ModelFamily,
    config: NetworkConfig,
    windows: Mapping[str, Mapping[str, object]],
    trained_at: datetime.datetime,
    run_id: str,
) -> dict[str, Any]:
    """The `metadata.json` of a `family` candidate, in the layout of the per-head families.

    The heads carry the metric fields of `HeadMetrics`, the fields the per-head booster families
    wrote, so the promotion rule, the events and the manifest read every family alike.
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
                "horizon_days": HEADS_BY_NAME[head.metrics.head].horizon_days,
                "example_window_start": windows.get(head.metrics.head, {}).get("example_window_start"),
                "example_cap_bound": windows.get(head.metrics.head, {}).get("example_cap_bound"),
                "file": ONNX_MODEL_FILE,
                "holdout_file": HOLDOUT_MODEL_FILE,
            }
            for head in trained.heads
        ],
        "skipped_heads": list(trained.skipped),
    }
    return with_recipe(metadata, network_recipe(family, config, trained.vector_kinds))


def onnx_probabilities(model: bytes, inputs: NetworkInputs, output_heads: Sequence[str]) -> dict[str, np.ndarray]:
    """Each output head's probability for every row of `inputs`, from a graph `export_onnx` wrote.

    The graph is fed only the inputs it declares, so a report-only graph reads the report vectors
    of a table built with context.
    """
    import onnxruntime as ort  # noqa: PLC0415 — keeps onnxruntime's native runtime off the location's import path

    session = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
    declared = {node.name for node in session.get_inputs()}
    report_input, project_input, history_input = ONNX_INPUTS
    feeds: dict[str, np.ndarray] = {report_input: np.ascontiguousarray(inputs.reports, dtype=np.float32)}
    if project_input in declared:
        if inputs.context is None:
            raise ValueError("the graph takes project vectors and the inputs carry none")
        pairs = inputs.context.index
        feeds[project_input] = np.ascontiguousarray(inputs.context.vectors[pairs], dtype=np.float32)
        feeds[history_input] = np.ascontiguousarray(inputs.context.has_history[pairs], dtype=np.float32)
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
