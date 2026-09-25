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
from products.signals.backend.ranking.serving_manifest import (
    DEFAULT_MODEL_KIND,
    METADATA_FILE,
    ServingManifest,
    ServingManifestEntry,
    serving_manifest_key,
)

logger = structlog.get_logger(__name__)

HEAD_FILE_SUFFIX = ".ubj"


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


class ModelKindHandler(Protocol):
    def load(
        self, entry: ServingManifestEntry, metadata: Mapping[str, Any], head_files: Mapping[str, bytes]
    ) -> LoadedModel: ...


class XGBoostHandler:
    """One binary XGBoost booster per head, all fit on the same feature set."""

    def load(
        self, entry: ServingManifestEntry, metadata: Mapping[str, Any], head_files: Mapping[str, bytes]
    ) -> LoadedModel:
        import xgboost as xgb  # noqa: PLC0415 — keeps xgboost's native OpenMP runtime off the Temporal worker import path

        feature_set = model_feature_set(metadata)
        if feature_set is None:
            raise ModelLoadError(f"{entry.key} declares a feature set this build cannot produce")
        boosters: dict[str, xgb.Booster] = {}
        for head, raw in head_files.items():
            booster = xgb.Booster()
            try:
                booster.load_model(bytearray(raw))
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


# The place a new learner plugs in, e.g. a torch model with its own `predict`.
MODEL_KIND_HANDLERS: Mapping[str, ModelKindHandler] = {DEFAULT_MODEL_KIND: XGBoostHandler()}

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
        raise ModelLoadError(f"{entry.key} {METADATA_FILE} has no trained booster for {untrained}")
    head_files: dict[str, bytes] = {}
    for head in entry.heads:
        body = object_storage.read_bytes(f"{entry.prefix}/{head}{HEAD_FILE_SUFFIX}", missing_ok=True)
        if body is None:
            raise ModelLoadError(f"{entry.key} has no {head}{HEAD_FILE_SUFFIX} under {entry.prefix}")
        head_files[head] = body
    return handler.load(entry, metadata, head_files)


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


def load_serving_set() -> ServingSet | None:
    """Every model the manifest names, or None when no manifest is published yet.

    A served entry that fails to load raises, because a pass without a served score is worse than
    no pass. Any other entry that fails is recorded in `skipped`, and the scorer writes it as a
    skipped result, so the coverage of each model stays readable.
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
    return ServingSet(manifest=manifest, served=served, others=others, skipped=skipped)
