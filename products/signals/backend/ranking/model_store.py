"""Loads the models the serving manifest names, from the deployment's own object store.

The training dag publishes the manifest and every model it names under
`<INBOX_RANKING_DATASET_S3_PREFIX>/serving/` (see `serving_manifest.py`). This module is the reader.
It uses `posthog.storage.object_storage`, the client the dag publishes with, and never the dataset
bucket: the scoring workers hold no credential for that bucket.

A model key is `<name>@<version>`, and the dag never re-copies a published version, so a loaded
model is cached in the process by key with no invalidation. The manifest itself is read on every
call, because a promotion changes it in place.

A model that reads its team's project vectors reads them from the one day the manifest names
(`load_project_vectors`). The sweep reads that day once per pass, for the teams it scores. User
vectors follow the same path (`load_user_vectors`), for the users a pass scores.
"""

from __future__ import annotations

import io
import json
import datetime
import threading
from collections import OrderedDict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import replace
from typing import Any, Protocol

from django.conf import settings

import numpy as np
import pandas as pd
import structlog

from posthog.dataclasses import frozen
from posthog.storage import object_storage

from products.signals.backend.artefact_schemas import MAX_RANKING_MODEL_RESULTS
from products.signals.backend.ranking.features import (
    ALL_PROJECT_VECTOR_KINDS,
    EMBEDDING_DIMENSIONS,
    PROJECT_VECTOR_KINDS,
    FeatureSet,
    ProjectInputs,
    project_inputs,
)
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
# The inputs that take the team's project vectors and their history flags, in the order of the kinds
# the graph's `metadata.json` lists under `ONNX_PROJECT_VECTOR_KINDS_KEY`. Only a graph that lists
# kinds takes them.
ONNX_PROJECT_INPUT = "project"
ONNX_HAS_HISTORY_INPUT = "has_history"
ONNX_PROJECT_VECTOR_KINDS_KEY = "project_vector_kinds"
# The `inbox_project_vectors` columns `project_inputs` reads.
PROJECT_VECTORS_COLUMNS = ["team_id", "kind", "vector", "n_reports"]
# The `inbox_user_vectors` columns `load_user_vectors` reads.
USER_VECTORS_COLUMNS = ["organization_id", "user_distinct_id", "kind", "vector", "n_reports", "last_at", "user_hash"]
# Threads one ONNX session may use for one operator. The sweep shares the worker with other
# activities, so a model must not take every core.
ONNX_INTRA_OP_THREADS = 2


class ModelLoadError(Exception):
    """One manifest entry could not be loaded into a model this build can score."""


class Predict(Protocol):
    def __call__(self, matrix: np.ndarray, project: ProjectInputs | None = None) -> Mapping[str, np.ndarray]:
        """`project` holds one row per row of `matrix`, and only a model that reads project vectors needs it."""
        ...


@frozen
class LoadedModel:
    entry: ServingManifestEntry
    # From `feature_set_by_name(metadata["feature_set"])`, the set the model was fit on.
    feature_set: FeatureSet
    # The model's `metadata.json`, copied onto every result it produces.
    metadata: Mapping[str, Any]
    # A matrix in `feature_set.feature_names` order to the probabilities of each head.
    predict: Predict
    # The project vector kinds `predict` also needs, in the graph's input order. Empty when the
    # model reads no project vectors.
    project_vector_kinds: tuple[str, ...] = ()

    @property
    def reads_project_vectors(self) -> bool:
        return bool(self.project_vector_kinds)


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
    def load(
        self,
        entry: ServingManifestEntry,
        metadata: Mapping[str, Any],
        feature_set: FeatureSet,
        files: Mapping[str, bytes],
    ) -> LoadedModel:
        """`feature_set` is the set `metadata` declares, and `files` holds the body of each name in `entry.files`."""
        ...


class XGBoostHandler:
    """One binary XGBoost booster per head, all fit on the same feature set."""

    def load(
        self,
        entry: ServingManifestEntry,
        metadata: Mapping[str, Any],
        feature_set: FeatureSet,
        files: Mapping[str, bytes],
    ) -> LoadedModel:
        import xgboost as xgb  # noqa: PLC0415 — keeps xgboost's native OpenMP runtime off the Temporal worker import path

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

        def predict(matrix: np.ndarray, project: ProjectInputs | None = None) -> dict[str, np.ndarray]:
            dmatrix = xgb.DMatrix(matrix, feature_names=feature_names)
            return {head: booster.predict(dmatrix) for head, booster in boosters.items()}

        return LoadedModel(entry=entry, feature_set=feature_set, metadata=metadata, predict=predict)


class ONNXHandler:
    """One ONNX graph that scores every head, from the inputs the feature set builds."""

    def load(
        self,
        entry: ServingManifestEntry,
        metadata: Mapping[str, Any],
        feature_set: FeatureSet,
        files: Mapping[str, bytes],
    ) -> LoadedModel:
        import onnxruntime as ort  # noqa: PLC0415 — keeps onnxruntime's native runtime off the Temporal worker import path

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
        kinds = tuple(metadata.get(ONNX_PROJECT_VECTOR_KINDS_KEY) or ())
        if len(set(kinds)) != len(kinds) or not set(kinds) <= set(ALL_PROJECT_VECTOR_KINDS):
            raise ModelLoadError(
                f"{entry.key} {METADATA_FILE} {ONNX_PROJECT_VECTOR_KINDS_KEY} {list(kinds)} are not distinct "
                f"kinds of {list(ALL_PROJECT_VECTOR_KINDS)}"
            )
        reads_project_vectors = bool(kinds)
        mismatch = _onnx_input_mismatch(session.get_inputs(), _onnx_input_shapes(feature_set, kinds))
        if mismatch is not None:
            raise ModelLoadError(f"{entry.key} {mismatch}")
        output_heads = list(metadata.get(ONNX_OUTPUT_HEADS_KEY) or ())
        mismatch = _onnx_output_mismatch(session.get_outputs(), output_heads, entry.heads)
        if mismatch is not None:
            raise ModelLoadError(f"{entry.key} {mismatch}")
        columns = {head: output_heads.index(head) for head in entry.heads}

        def predict(matrix: np.ndarray, project: ProjectInputs | None = None) -> dict[str, np.ndarray]:
            feeds = {ONNX_REPORT_INPUT: np.ascontiguousarray(matrix, dtype=np.float32)}
            if reads_project_vectors:
                if project is None:
                    raise ValueError(f"{entry.key} reads project vectors and none were given")
                feeds[ONNX_PROJECT_INPUT] = np.ascontiguousarray(project.vectors, dtype=np.float32)
                feeds[ONNX_HAS_HISTORY_INPUT] = np.ascontiguousarray(project.has_history, dtype=np.float32)
            (probabilities,) = session.run([ONNX_OUTPUT], feeds)
            return {head: probabilities[:, column] for head, column in columns.items()}

        return LoadedModel(
            entry=entry,
            feature_set=feature_set,
            metadata=metadata,
            predict=predict,
            project_vector_kinds=kinds,
        )


def _onnx_input_shapes(feature_set: FeatureSet, project_vector_kinds: Sequence[str]) -> dict[str, tuple[int, ...]]:
    """The shape after the batch axis of each ONNX input the scorer feeds for `feature_set`."""
    shapes: dict[str, tuple[int, ...]] = {ONNX_REPORT_INPUT: (len(feature_set.feature_names),)}
    if project_vector_kinds:
        shapes[ONNX_PROJECT_INPUT] = (len(project_vector_kinds), EMBEDDING_DIMENSIONS)
        shapes[ONNX_HAS_HISTORY_INPUT] = (len(project_vector_kinds),)
    return shapes


def _onnx_input_mismatch(inputs: Sequence[Any], shapes: Mapping[str, tuple[int, ...]]) -> str | None:
    """Why the graph's inputs differ from what the scorer feeds, or None when they agree.

    Each input must be float32 with shape `(batch, *shape)`.
    """
    names = sorted(node.name for node in inputs)
    if names != sorted(shapes):
        return f"{ONNX_MODEL_FILE} inputs {names} are not {sorted(shapes)}"
    for node in inputs:
        shape = shapes[node.name]
        if node.type != "tensor(float)" or tuple(node.shape[1:]) != shape or len(node.shape) != 1 + len(shape):
            expected = ", ".join(str(size) for size in shape)
            return f"{ONNX_MODEL_FILE} input {node.name} is {node.type} {node.shape}, not float (batch, {expected})"
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
    feature_set = model_feature_set(metadata)
    mismatch = model_mismatch(metadata)
    if feature_set is None or mismatch is not None:
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
    return handler.load(entry, metadata, feature_set, files)


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


@frozen
class ProjectVectors:
    """The project vectors one pass reads, for the teams it scores."""

    # False when the manifest names no object or the object is missing, so no team has vectors.
    available: bool
    # One row per team, in `ALL_PROJECT_VECTOR_KINDS` order.
    by_team: Mapping[int, ProjectInputs]
    # The kinds the day has rows for. A day written before `fixed` was stored has no `fixed` rows.
    kinds: frozenset[str] = frozenset()

    def missing_kinds(self, kinds: Sequence[str]) -> list[str]:
        """The kinds of `kinds` the day has no rows for. A model must not read them as all-zero vectors."""
        return [kind for kind in kinds if kind not in self.kinds]

    def for_team(self, team_id: int, kinds: Sequence[str] = PROJECT_VECTOR_KINDS) -> ProjectInputs | None:
        """One row of the team's vectors in `kinds` order, all zero when the day has no row for the
        team, or None when the pass has no project vectors at all."""
        if not self.available:
            return None
        inputs = self.by_team.get(team_id) or project_inputs(
            pd.DataFrame(columns=PROJECT_VECTORS_COLUMNS), [team_id], ALL_PROJECT_VECTOR_KINDS
        )
        positions = [ALL_PROJECT_VECTOR_KINDS.index(kind) for kind in kinds]
        return ProjectInputs(vectors=inputs.vectors[:, positions], has_history=inputs.has_history[:, positions])


def load_project_vectors(manifest: ServingManifest, team_ids: Collection[int]) -> ProjectVectors:
    """The vectors of `team_ids` from the day the manifest names, read once.

    Only the rows of `team_ids` are kept, so the pass holds one vector per (team, kind) it scores.
    A missing object is no vectors at all rather than an empty day, so the models that read them
    are skipped instead of scoring every team as a team without history.
    """
    key = manifest.project_vectors
    teams = sorted({int(team_id) for team_id in team_ids})
    body = None if key is None or not teams else object_storage.read_bytes(key, missing_ok=True)
    if body is None:
        if key is not None and teams:
            logger.warning("inbox_ranking_project_vectors_missing", project_vectors_key=key)
        return ProjectVectors(available=False, by_team={})
    # The kinds come from every row, so a day without rows for these teams still says what it carries.
    kinds = frozenset(pd.read_parquet(io.BytesIO(body), columns=["kind"])["kind"].unique())
    rows = pd.read_parquet(io.BytesIO(body), columns=PROJECT_VECTORS_COLUMNS, filters=[("team_id", "in", teams)])
    inputs = project_inputs(rows, teams, ALL_PROJECT_VECTOR_KINDS)
    by_team = {
        team_id: ProjectInputs(
            vectors=inputs.vectors[index : index + 1], has_history=inputs.has_history[index : index + 1]
        )
        for index, team_id in enumerate(teams)
    }
    return ProjectVectors(available=True, by_team=by_team, kinds=kinds)


@frozen
class UserKindVector:
    vector: np.ndarray
    n_reports: int
    last_at: datetime.datetime


@frozen
class UserVectors:
    """The user vectors one pass reads, for the users it scores."""

    # False when the manifest names no object or the object is missing, so no user has vectors.
    available: bool
    # (organization id, user distinct id) to the user's vector of each kind with history. A user
    # without history has no entry.
    by_user: Mapping[tuple[str, str], Mapping[str, UserKindVector]]
    # The same key to the hash of the user's kinds, counts and vectors. It changes only when one of them changes.
    hashes: Mapping[tuple[str, str], str]


def load_user_vectors(manifest: ServingManifest, users: Collection[tuple[str, str]]) -> UserVectors:
    """The vectors of `users`, each an (organization id, user distinct id), from the day the manifest
    names, read once.

    Only the rows of `users` are kept. A missing object is no vectors at all rather than an empty
    day, like `load_project_vectors`.
    """
    key = manifest.user_vectors
    wanted = {(str(organization_id), str(user)) for organization_id, user in users}
    body = None if key is None or not wanted else object_storage.read_bytes(key, missing_ok=True)
    if body is None:
        if key is not None and wanted:
            logger.warning("inbox_ranking_user_vectors_missing", user_vectors_key=key)
        return UserVectors(available=False, by_user={}, hashes={})
    # Both filters reach the Parquet reader, so only rows of the requested organizations and users are decoded.
    rows = pd.read_parquet(
        io.BytesIO(body),
        columns=USER_VECTORS_COLUMNS,
        filters=[
            ("organization_id", "in", sorted({organization_id for organization_id, _ in wanted})),
            ("user_distinct_id", "in", sorted({user for _, user in wanted})),
        ],
    )
    by_user: dict[tuple[str, str], dict[str, UserKindVector]] = {}
    hashes: dict[tuple[str, str], str] = {}
    for row in rows.itertuples(index=False):
        user = (row.organization_id, row.user_distinct_id)
        if user not in wanted:
            continue
        by_user.setdefault(user, {})[row.kind] = UserKindVector(
            vector=np.asarray(row.vector, dtype=np.float32),
            n_reports=int(row.n_reports),
            last_at=row.last_at.to_pydatetime(),
        )
        hashes[user] = row.user_hash
    return UserVectors(available=True, by_user=by_user, hashes=hashes)


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
    if model.reads_project_vectors and serving.manifest.project_vectors is None:
        return f"{key} reads project vectors and the manifest names none"
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
