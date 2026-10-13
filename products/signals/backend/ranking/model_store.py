"""Loads the models the serving manifest names, from the deployment's own object store.

The training dag publishes the manifest and every model it names under
`<INBOX_RANKING_DATASET_S3_PREFIX>/serving/` (see `serving_manifest.py`). This module is the reader.
It uses `posthog.storage.object_storage`, the client the dag publishes with, and never the dataset
bucket: the scoring workers hold no credential for that bucket.

A model key is `<name>@<version>`, and the dag never re-copies a published version, so a loaded
model is cached in the process by key with no invalidation. The manifest itself is read on every
call, because a promotion changes it in place.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any, Protocol

from django.conf import settings

import numpy as np
import structlog

from posthog.dataclasses import frozen
from posthog.storage import object_storage

from products.signals.backend.artefact_schemas import MAX_RANKING_MODEL_RESULTS
from products.signals.backend.ranking.features import FeatureSet
from products.signals.backend.ranking.model_contract import (
    booster_mismatch,
    model_feature_set,
    model_mismatch,
    trained_head_files,
)
from products.signals.backend.ranking.overrides import RankingOverrides
from products.signals.backend.ranking.serving_manifest import (
    DEFAULT_MODEL_KIND,
    HEAD_FILE_SUFFIX,
    MANIFEST_SERVED_ROLE,
    METADATA_FILE,
    ONNX_MODEL_FILE,
    ONNX_MODEL_KIND,
    SERVED_OVERRIDE_ROLE,
    SERVED_ROLE,
    ServingManifest,
    ServingManifestEntry,
    serving_manifest_key,
)

logger = structlog.get_logger(__name__)

# The ONNX output that holds one probability column per head, in the order of `ONNX_OUTPUT_HEADS_KEY`
# in the model's `metadata.json`.
ONNX_OUTPUT = "probabilities"
ONNX_OUTPUT_HEADS_KEY = "output_heads"
# The input that takes the feature set's matrix, the report vector.
ONNX_REPORT_INPUT = "report"
# Threads one ONNX session may use for one operator. The sweep shares the worker with other
# activities, so a model must not take every core.
ONNX_INTRA_OP_THREADS = 2


class ModelLoadError(Exception):
    """One manifest entry could not be loaded into a model this build can score."""


@frozen
class LoadedModel:
    entry: ServingManifestEntry
    # From `feature_set_by_name(metadata["feature_set"])`, the set the model was fit on.
    feature_set: FeatureSet
    # The model's `metadata.json`, copied onto every result it produces.
    metadata: Mapping[str, Any]
    # A matrix in `feature_set.feature_names` order to the probabilities of each head.
    predict: Callable[[np.ndarray], Mapping[str, np.ndarray]]


@frozen
class ServingSet:
    manifest: ServingManifest
    served: LoadedModel
    # The other entries that loaded, in manifest order.
    others: Sequence[LoadedModel]
    # Model key to the reason the entry could not be loaded.
    skipped: Mapping[str, str]
    # The overrides whose `served` key this set serves. None when the manifest's served model serves.
    served_override: RankingOverrides | None = None


class ModelKindHandler(Protocol):
    def load(self, entry: ServingManifestEntry, metadata: Mapping[str, Any], files: Mapping[str, bytes]) -> LoadedModel:
        """`files` holds the body of each name in `entry.files`."""
        ...


class XGBoostHandler:
    """One binary XGBoost booster per head, all fit on the same feature set."""

    def load(self, entry: ServingManifestEntry, metadata: Mapping[str, Any], files: Mapping[str, bytes]) -> LoadedModel:
        import xgboost as xgb  # noqa: PLC0415 — keeps xgboost's native OpenMP runtime off the Temporal worker import path

        feature_set = model_feature_set(metadata)
        if feature_set is None:
            raise ModelLoadError(f"{entry.key} declares a feature set this build cannot produce")
        boosters: dict[str, xgb.Booster] = {}
        for head in entry.heads:
            booster = xgb.Booster()
            try:
                booster.load_model(bytearray(files[f"{head}{HEAD_FILE_SUFFIX}"]))
            except xgb.core.XGBoostError as error:
                raise ModelLoadError(f"{entry.key} {head} booster does not load: {error}") from error
            mismatch = booster_mismatch(head, booster.feature_names, feature_set)
            if mismatch is not None:
                raise ModelLoadError(f"{entry.key} {mismatch}")
            boosters[head] = booster
        feature_names = list(feature_set.feature_names)

        def predict(matrix: np.ndarray) -> dict[str, np.ndarray]:
            dmatrix = xgb.DMatrix(matrix, feature_names=feature_names)
            return {head: booster.predict(dmatrix) for head, booster in boosters.items()}

        return LoadedModel(entry=entry, feature_set=feature_set, metadata=metadata, predict=predict)


class ONNXHandler:
    """One ONNX graph that scores every head, from the inputs the feature set builds."""

    def load(self, entry: ServingManifestEntry, metadata: Mapping[str, Any], files: Mapping[str, bytes]) -> LoadedModel:
        import onnxruntime as ort  # noqa: PLC0415 — keeps onnxruntime's native runtime off the Temporal worker import path

        feature_set = model_feature_set(metadata)
        if feature_set is None:
            raise ModelLoadError(f"{entry.key} declares a feature set this build cannot produce")
        options = ort.SessionOptions()
        options.intra_op_num_threads = ONNX_INTRA_OP_THREADS
        options.inter_op_num_threads = 1
        try:
            session = ort.InferenceSession(
                files[ONNX_MODEL_FILE], sess_options=options, providers=["CPUExecutionProvider"]
            )
        # onnxruntime's errors share no base class below Exception.
        except Exception as error:
            raise ModelLoadError(f"{entry.key} {ONNX_MODEL_FILE} does not load: {error}") from error
        mismatch = _onnx_input_mismatch(session.get_inputs(), _onnx_input_widths(feature_set))
        if mismatch is not None:
            raise ModelLoadError(f"{entry.key} {mismatch}")
        output_heads = list(metadata.get(ONNX_OUTPUT_HEADS_KEY) or ())
        mismatch = _onnx_output_mismatch(session.get_outputs(), output_heads, entry.heads)
        if mismatch is not None:
            raise ModelLoadError(f"{entry.key} {mismatch}")
        columns = {head: output_heads.index(head) for head in entry.heads}

        def predict(matrix: np.ndarray) -> dict[str, np.ndarray]:
            (probabilities,) = session.run(
                [ONNX_OUTPUT], {ONNX_REPORT_INPUT: np.ascontiguousarray(matrix, dtype=np.float32)}
            )
            return {head: probabilities[:, column] for head, column in columns.items()}

        return LoadedModel(entry=entry, feature_set=feature_set, metadata=metadata, predict=predict)


def _onnx_input_widths(feature_set: FeatureSet) -> dict[str, int]:
    """The width of each ONNX input the scorer can feed for `feature_set`.

    Only the report vector today. The project-vector inputs join here when the sweep can read
    project vectors, and `predict` then feeds them too.
    """
    return {ONNX_REPORT_INPUT: len(feature_set.feature_names)}


def _onnx_input_mismatch(inputs: Sequence[Any], widths: Mapping[str, int]) -> str | None:
    """Why the graph's inputs differ from what the scorer feeds, or None when they agree.

    Each input must be float32 with shape `(batch, width)`.
    """
    names = sorted(node.name for node in inputs)
    if names != sorted(widths):
        return f"{ONNX_MODEL_FILE} inputs {names} are not {sorted(widths)}"
    for node in inputs:
        if node.type != "tensor(float)" or len(node.shape) != 2 or node.shape[1] != widths[node.name]:
            return f"{ONNX_MODEL_FILE} input {node.name} is {node.type} {node.shape}, not float (batch, {widths[node.name]})"
    return None


def _onnx_output_mismatch(outputs: Sequence[Any], output_heads: Sequence[str], heads: Sequence[str]) -> str | None:
    """Why the graph's output cannot give a probability for each of `heads`, or None when it can."""
    output = next((node for node in outputs if node.name == ONNX_OUTPUT), None)
    if output is None:
        return f"{ONNX_MODEL_FILE} has no {ONNX_OUTPUT} output"
    if len(output.shape) != 2 or output.shape[1] != len(output_heads):
        return f"{ONNX_MODEL_FILE} {ONNX_OUTPUT} is {output.shape}, not (batch, {len(output_heads)}) for {ONNX_OUTPUT_HEADS_KEY}"
    missing = sorted(set(heads) - set(output_heads))
    if missing:
        return f"{METADATA_FILE} {ONNX_OUTPUT_HEADS_KEY} has no column for {missing}"
    return None


# The place a new learner plugs in, with its own `predict`.
MODEL_KIND_HANDLERS: Mapping[str, ModelKindHandler] = {
    DEFAULT_MODEL_KIND: XGBoostHandler(),
    ONNX_MODEL_KIND: ONNXHandler(),
}

_cache: OrderedDict[str, LoadedModel] = OrderedDict()
_cache_lock = threading.Lock()


def _read_entry(entry: ServingManifestEntry) -> LoadedModel:
    handler = MODEL_KIND_HANDLERS.get(entry.model_kind)
    if handler is None:
        raise ModelLoadError(f"{entry.key} has model_kind {entry.model_kind}, which this build cannot load")
    raw_metadata = object_storage.read(f"{entry.prefix}/{METADATA_FILE}", missing_ok=True)
    if raw_metadata is None:
        raise ModelLoadError(f"{entry.key} has no {METADATA_FILE} under {entry.prefix}")
    metadata = json.loads(raw_metadata)
    if (metadata.get("model_name"), metadata.get("model_version")) != (entry.model_name, entry.model_version):
        raise ModelLoadError(f"{entry.key} {METADATA_FILE} describes another model")
    mismatch = model_mismatch(metadata)
    if mismatch is not None:
        raise ModelLoadError(f"{entry.key} {mismatch}")
    untrained = sorted(set(entry.heads) - set(trained_head_files(metadata, entry.heads)))
    if untrained:
        raise ModelLoadError(f"{entry.key} {METADATA_FILE} has no trained model file for {untrained}")
    files: dict[str, bytes] = {}
    for name in entry.files:
        body = object_storage.read_bytes(f"{entry.prefix}/{name}", missing_ok=True)
        if body is None:
            raise ModelLoadError(f"{entry.key} has no {name} under {entry.prefix}")
        files[name] = body
    return handler.load(entry, metadata, files)


def load_model(entry: ServingManifestEntry) -> LoadedModel:
    """The model one entry names, from the process cache when this key was loaded before.

    The cached model carries the entry it was first loaded under, and roles change between
    manifests, so the returned model carries the current entry instead.
    """
    with _cache_lock:
        cached = _cache.get(entry.key)
        if cached is not None:
            _cache.move_to_end(entry.key)
    if cached is None:
        cached = _read_entry(entry)
        with _cache_lock:
            _cache[entry.key] = cached
            while len(_cache) > MAX_RANKING_MODEL_RESULTS:
                _cache.popitem(last=False)
    return replace(cached, entry=entry)


def clear_model_cache() -> None:
    with _cache_lock:
        _cache.clear()


def load_serving_set(overrides: RankingOverrides | None = None) -> ServingSet | None:
    """Every model the manifest names, or None when no manifest is published yet.

    A served entry that fails to load raises, because a pass without a served score is worse than
    no pass. Any other entry that fails is recorded in `skipped`, and the scorer writes it as a
    skipped result, so the coverage of each model stays readable.

    A `served` override moves the served role to another model the manifest names. An override
    that cannot apply is logged and the manifest's served model serves, so a bad override never
    stops a pass.
    """
    raw_manifest = object_storage.read(serving_manifest_key(settings.INBOX_RANKING_DATASET_S3_PREFIX), missing_ok=True)
    if raw_manifest is None:
        return None
    manifest = ServingManifest.model_validate_json(raw_manifest)
    served = load_model(manifest.served)
    others: list[LoadedModel] = []
    skipped: dict[str, str] = {}
    for entry in manifest.models:
        if entry.key == manifest.served.key:
            continue
        try:
            others.append(load_model(entry))
        except ModelLoadError as error:
            logger.warning("inbox_ranking_model_skipped", model_key=entry.key, reason=str(error))
            skipped[entry.key] = str(error)
    serving = ServingSet(manifest=manifest, served=served, others=others, skipped=skipped)
    if overrides is None or overrides.served is None or overrides.served == manifest.served.key:
        return serving
    rejection = served_override_rejection(serving, overrides.served)
    if rejection is not None:
        logger.warning(
            "inbox_ranking_override_rejected",
            override_served=overrides.served,
            manifest_served=manifest.served.key,
            reason=rejection,
        )
        return serving
    return _with_served_override(serving, overrides)


def served_override_rejection(serving: ServingSet, key: str) -> str | None:
    """Why the model `key` cannot take the served role this pass, or None when it can.

    Only a model the manifest names and the pass loaded qualifies, so an override never makes a
    pod load a model it did not already hold. The model must also have every head the manifest's
    served model has, because consumers read `p_<head>` off the served score.
    """
    if key in serving.skipped:
        return f"{key} did not load: {serving.skipped[key]}"
    model = next((model for model in serving.others if model.entry.key == key), None)
    if model is None:
        return f"{key} is not in the serving manifest"
    missing_heads = sorted(set(serving.served.entry.heads) - set(model.entry.heads))
    if missing_heads:
        return f"{key} has no head for {missing_heads}"
    return None


def _with_served_override(serving: ServingSet, overrides: RankingOverrides) -> ServingSet:
    def roles(entry: ServingManifestEntry) -> list[str]:
        if entry.key == overrides.served:
            return [SERVED_ROLE, SERVED_OVERRIDE_ROLE, *entry.roles]
        if SERVED_ROLE in entry.roles:
            return [MANIFEST_SERVED_ROLE, *(role for role in entry.roles if role != SERVED_ROLE)]
        return list(entry.roles)

    entries = [entry.model_copy(update={"roles": roles(entry)}) for entry in serving.manifest.models]
    manifest = serving.manifest.model_copy(update={"models": entries})
    by_key = {entry.key: entry for entry in entries}
    loaded = [serving.served, *serving.others]
    served = next(model for model in loaded if model.entry.key == overrides.served)
    return ServingSet(
        manifest=manifest,
        served=replace(served, entry=by_key[served.entry.key]),
        others=[replace(model, entry=by_key[model.entry.key]) for model in loaded if model is not served],
        skipped=serving.skipped,
        served_override=overrides,
    )
