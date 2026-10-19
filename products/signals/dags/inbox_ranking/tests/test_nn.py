import io
import json
import datetime
import dataclasses
from typing import Any

import pytest

import numpy as np
import dagster
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.exceptions import ClientError
from sklearn.metrics import roc_auc_score

from posthog import settings

from products.signals.backend.ranking.features import PROJECT_VECTOR_KINDS, REPORT_EMBEDDINGS_FEATURE_SET
from products.signals.backend.ranking.model_contract import model_mismatch
from products.signals.backend.ranking.model_store import ONNX_OUTPUT_HEADS_KEY
from products.signals.backend.ranking.overrides import NO_OVERRIDES
from products.signals.backend.ranking.serving_manifest import (
    CROSS_FAMILY_ROLE,
    ONNX_MODEL_FILE,
    ONNX_MODEL_KIND,
    RECENT_ROLE,
    SERVED_ROLE,
)
from products.signals.dags.inbox_ranking.common import DATASET_VERSION, partition_object_key
from products.signals.dags.inbox_ranking.dataset import project_vectors
from products.signals.dags.inbox_ranking.dataset.dag import EMBEDDINGS_TABLE, LABELS_TABLE
from products.signals.dags.inbox_ranking.multihead.inputs import NetworkConfig
from products.signals.dags.inbox_ranking.multihead.local import report_vectors
from products.signals.dags.inbox_ranking.nn import dag as nn_dag
from products.signals.dags.inbox_ranking.nn.examples import (
    NN_HEAD_NAMES,
    build_examples,
    examples_arrow,
    network_inputs,
    subset,
)
from products.signals.dags.inbox_ranking.nn.model import (
    HOLDOUT_MODEL_FILE,
    NetworkHead,
    TrainedNetwork,
    candidate_metadata,
    network_recipe,
    onnx_probabilities,
)
from products.signals.dags.inbox_ranking.tests.test_multihead import D0, DAYS, HOLDOUT_DAYS, _SyntheticInbox
from products.signals.dags.inbox_ranking.training import recipe as recipe_module
from products.signals.dags.inbox_ranking.training.dag import (
    CHAMPION_FILE,
    METADATA_FILE,
    SERVED_FILE,
    booster_recipe,
    check_recipe,
    inbox_ranking_model_candidate,
    inbox_ranking_model_champion,
    model_object_key,
    served_object_key,
)
from products.signals.dags.inbox_ranking.training.heads import HEADS_BY_NAME, Head
from products.signals.dags.inbox_ranking.training.recipe import RECIPE_HASH_KEY, RECIPE_KEY, model_recipe, recipe_hash
from products.signals.dags.inbox_ranking.training.serving import FamilyModels, compose_manifest
from products.signals.dags.inbox_ranking.training.train import HeadMetrics
from products.signals.dags.inbox_ranking.training.unseen import NN_MODEL_NAME, REPORT_EMBEDDINGS_MODEL_NAME

PREFIX = settings.INBOX_RANKING_DATASET_S3_PREFIX
PARTITION = "2026-08-19"
NOW = datetime.datetime(2026, 8, 20, 6, tzinfo=datetime.UTC)


class _S3:
    def __init__(self, objects: dict[str, bytes] | None = None):
        self.objects = dict(objects or {})

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, *, Bucket, Key, Body, **kwargs):
        self.objects[Key] = Body

    def upload_fileobj(self, fileobj, bucket, key, ExtraArgs=None):
        self.objects[key] = fileobj.read()

    def get_paginator(self, _name):
        return self

    def paginate(self, *, Bucket, Prefix, Delimiter=None):
        keys = [key for key in sorted(self.objects) if key.startswith(Prefix)]
        if Delimiter is None:
            yield {"Contents": [{"Key": key} for key in keys]}
            return
        folders = {
            Prefix + key[len(Prefix) :].split(Delimiter)[0] + Delimiter
            for key in keys
            if Delimiter in key[len(Prefix) :]
        }
        yield {"CommonPrefixes": [{"Prefix": folder} for folder in sorted(folders)]}

    def delete_objects(self, *, Bucket, Delete):
        for obj in Delete["Objects"]:
            self.objects.pop(obj["Key"])


def _parquet(table: pa.Table) -> bytes:
    sink = io.BytesIO()
    pq.write_table(table, sink)
    return sink.getvalue()


def _trained_network(heads: tuple[str, ...] = ("open",)) -> TrainedNetwork:
    return TrainedNetwork(
        output_heads=NN_HEAD_NAMES,
        model_onnx=b"graph",
        holdout_model_onnx=b"holdout-graph",
        heads=tuple(NetworkHead(metrics=_head_metrics(head), calibration=()) for head in heads),
        skipped=(),
        network_train_rows=400,
        refit_rows=600,
        vector_kinds=(),
    )


def _head_metrics(head: str) -> HeadMetrics:
    return HeadMetrics(
        head=head,
        train_rows=400,
        train_positives=120,
        holdout_rows=200,
        holdout_positives=60,
        holdout_auc=0.8,
        null_auc=0.5,
        null_auc_std=0.01,
        readable=True,
    )


def _nn_metadata(version: str, heads: tuple[str, ...] = ("open",)) -> dict[str, Any]:
    return candidate_metadata(
        version, _trained_network(heads), config=NetworkConfig(), windows={}, trained_at=NOW, run_id="run-1"
    )


def _xgboost_metadata(model_name: str, version: str) -> dict[str, Any]:
    return {
        "model_name": model_name,
        "model_version": version,
        "heads": [{"head": "open", "readable": True, "holdout_auc": 0.7, "file": "open.ubj"}],
        "promoted_at": "2026-08-01T06:00:00+00:00",
    }


@pytest.fixture
def no_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    for module in ("products.signals.dags.inbox_ranking.training.dag", "products.signals.dags.inbox_ranking.nn.dag"):
        monkeypatch.setattr(f"{module}.capture_training_events", lambda *args, **kwargs: None)
        monkeypatch.setattr(f"{module}.read_ranking_overrides", lambda now: NO_OVERRIDES, raising=False)


def test_the_main_location_never_fits_nn_or_writes_a_pointer(monkeypatch, no_side_effects):
    # Every family has a candidate and nothing is served, so each decision would promote. Training
    # still writes no pointer: only the promote job chooses what the sweep serves.
    client = _S3(
        {
            model_object_key(PREFIX, name, PARTITION, METADATA_FILE): json.dumps(
                _xgboost_metadata(name, PARTITION)
            ).encode()
            for name in (REPORT_EMBEDDINGS_MODEL_NAME, NN_MODEL_NAME)
        }
    )
    monkeypatch.setattr("products.signals.dags.inbox_ranking.training.dag.s3_client", lambda: client)

    with dagster.build_asset_context(partition_key=PARTITION) as context:
        inbox_ranking_model_candidate(context)
        inbox_ranking_model_champion(context)

    assert not [key for key in client.objects if key.endswith((CHAMPION_FILE, SERVED_FILE))]
    assert not [key for key in client.objects if f"/{NN_MODEL_NAME}/" in key and not key.endswith(METADATA_FILE)]


def test_the_manifest_carries_an_nn_champion_as_an_onnx_entry():
    decision = compose_manifest(
        [
            FamilyModels(
                name=REPORT_EMBEDDINGS_MODEL_NAME,
                champion=_xgboost_metadata(REPORT_EMBEDDINGS_MODEL_NAME, "2026-08-15"),
            ),
            FamilyModels(name=NN_MODEL_NAME, champion=_nn_metadata("2026-08-16")),
        ],
        served=_xgboost_metadata(REPORT_EMBEDDINGS_MODEL_NAME, "2026-08-15"),
        prefix=PREFIX,
        now=NOW,
    )

    assert decision.manifest is not None
    (entry,) = [entry for entry in decision.manifest.models if entry.model_name == NN_MODEL_NAME]
    assert entry.roles == [CROSS_FAMILY_ROLE]
    assert entry.model_kind == ONNX_MODEL_KIND
    assert entry.files == [ONNX_MODEL_FILE]
    assert entry.heads == ["open"]


def test_the_manifest_serves_an_nn_model_with_the_xgboost_champion_as_a_challenger():
    decision = compose_manifest(
        [
            FamilyModels(
                name=REPORT_EMBEDDINGS_MODEL_NAME,
                champion=_xgboost_metadata(REPORT_EMBEDDINGS_MODEL_NAME, "2026-08-15"),
            ),
            FamilyModels(name=NN_MODEL_NAME, champion=_nn_metadata("2026-08-16", heads=NN_HEAD_NAMES)),
        ],
        served=_nn_metadata("2026-08-16", heads=NN_HEAD_NAMES),
        prefix=PREFIX,
        now=NOW,
        recent=[_nn_metadata(PARTITION, heads=NN_HEAD_NAMES)],
        recent_versions=3,
    )

    assert decision.manifest is not None
    assert [(entry.model_name, entry.model_version, entry.roles) for entry in decision.manifest.models] == [
        (NN_MODEL_NAME, "2026-08-16", [SERVED_ROLE]),
        (NN_MODEL_NAME, PARTITION, [RECENT_ROLE]),
        (REPORT_EMBEDDINGS_MODEL_NAME, "2026-08-15", [CROSS_FAMILY_ROLE]),
    ]
    served = decision.manifest.served
    assert served.model_kind == ONNX_MODEL_KIND
    assert served.files == [ONNX_MODEL_FILE]
    assert sorted(served.heads) == sorted(NN_HEAD_NAMES)


def test_the_nn_decision_is_graded_against_the_served_nn_model_and_writes_nothing(no_side_effects):
    served = _nn_metadata("2026-08-16")
    client = _S3(
        {
            model_object_key(PREFIX, NN_MODEL_NAME, PARTITION, METADATA_FILE): json.dumps(
                _nn_metadata(PARTITION)
            ).encode(),
            model_object_key(PREFIX, NN_MODEL_NAME, "2026-08-16", METADATA_FILE): json.dumps(served).encode(),
            served_object_key(PREFIX): json.dumps(
                {"model_key": f"{NN_MODEL_NAME}@2026-08-16", "model_name": NN_MODEL_NAME, "model_version": "2026-08-16"}
            ).encode(),
        }
    )
    before = dict(client.objects)

    with dagster.build_asset_context(partition_key=PARTITION) as context:
        metadata = nn_dag.decide_champion(context, client, "bucket", PARTITION)

    assert metadata is not None
    assert metadata[f"{NN_MODEL_NAME}_incumbent_champion_version"].value == "2026-08-16"
    assert client.objects == before


def test_the_nn_candidate_writes_a_graph_whose_columns_follow_its_recorded_head_order(monkeypatch, no_side_effects):
    pytest.importorskip("torch")
    onnxruntime = pytest.importorskip("onnxruntime")
    monkeypatch.setattr(
        nn_dag, "NETWORK_CONFIG", NetworkConfig(projection_dim=8, trunk_dim=8, dropout=0.1, epochs=40, batch_size=32)
    )
    inbox = _SyntheticInbox()
    embeddings, labels = inbox.embeddings(), inbox.labels()
    extras = report_vectors(embeddings)
    examples = build_examples(inbox.snapshots(), extras, holdout_days=HOLDOUT_DAYS)
    day = (D0 + datetime.timedelta(days=DAYS - 1)).isoformat()
    client = _S3(
        {
            partition_object_key(PREFIX, nn_dag.NN_EXAMPLES_TABLE, day): _parquet(examples_arrow(examples)),
            partition_object_key(PREFIX, EMBEDDINGS_TABLE, day): _parquet(embeddings),
            partition_object_key(PREFIX, LABELS_TABLE, day): _parquet(labels),
        }
    )

    with dagster.build_asset_context(partition_key=day) as context:
        nn_dag.train_candidate(context, client, "bucket", day)

    metadata = json.loads(client.objects[model_object_key(PREFIX, NN_MODEL_NAME, day, METADATA_FILE)])
    assert metadata["model_kind"] == ONNX_MODEL_KIND
    assert metadata[ONNX_OUTPUT_HEADS_KEY] == list(NN_HEAD_NAMES)
    assert model_mismatch(metadata) is None
    assert {head["head"] for head in metadata["heads"]} == set(NN_HEAD_NAMES)
    assert {(head["file"], head["holdout_file"]) for head in metadata["heads"]} == {
        (ONNX_MODEL_FILE, HOLDOUT_MODEL_FILE)
    }
    served = onnxruntime.InferenceSession(
        client.objects[model_object_key(PREFIX, NN_MODEL_NAME, day, ONNX_MODEL_FILE)],
        providers=["CPUExecutionProvider"],
    )
    assert served.get_outputs()[0].shape[1] == len(metadata[ONNX_OUTPUT_HEADS_KEY])

    # Each head's column of the train-only graph, read through `output_heads`, must reproduce the
    # holdout AUC recorded for that head. A column read for the wrong head ranks at chance here.
    table = examples.table
    holdout = subset(table, np.flatnonzero(table.holdout.any(axis=1)))
    probabilities = onnx_probabilities(
        client.objects[model_object_key(PREFIX, NN_MODEL_NAME, day, HOLDOUT_MODEL_FILE)],
        network_inputs(holdout, extras, labels, embeddings),
        metadata[ONNX_OUTPUT_HEADS_KEY],
    )
    for head in metadata["heads"]:
        index = NN_HEAD_NAMES.index(head["head"])
        rows = holdout.head_rows(index, holdout=True)
        auc = roc_auc_score(holdout.labels[rows, index], probabilities[head["head"]][rows])
        assert auc == pytest.approx(head["holdout_auc"], abs=1e-4)
        assert auc > 0.75


def _stored_version(
    model_name: str, version: str, recipe: dict[str, Any] | None, dataset_version: str = DATASET_VERSION
) -> tuple[str, bytes]:
    metadata: dict[str, Any] = {"model_name": model_name, "model_version": version}
    if recipe is not None:
        metadata |= {RECIPE_KEY: recipe, RECIPE_HASH_KEY: recipe_hash(recipe)}
    key = model_object_key(PREFIX, model_name, version, METADATA_FILE)
    key = key.replace(f"/{DATASET_VERSION}/", f"/{dataset_version}/", 1)
    return key, json.dumps(metadata).encode()


ACTION = HEADS_BY_NAME["action"]


def _action_recipe(head: Head) -> dict[str, Any]:
    return model_recipe(
        model_kind=ONNX_MODEL_KIND, feature_set=REPORT_EMBEDDINGS_FEATURE_SET, heads=[head], learner_params={}
    )


@pytest.mark.parametrize(
    "stored, recipe, patch, changed",
    [
        ({"2026-08-18": "booster"}, "booster", None, None),
        (
            {"2026-08-18": "booster"},
            "booster",
            (settings, "INBOX_RANKING_TRAINING_LOOKBACK_DAYS", 120),
            "lookback_days",
        ),
        ({"2026-08-18": "network"}, "network_more_epochs", None, "learner_params.epochs"),
        ({"2026-08-17": "network", "2026-08-18": None}, "network_more_epochs", None, "learner_params.epochs"),
        ({"2026-08-18": None}, "network_more_epochs", None, None),
        ({"2026-08-20": "network"}, "network_more_epochs", None, None),
        ({PARTITION: "network"}, "network", None, None),
        ({PARTITION: "network"}, "network_more_epochs", None, "learner_params.epochs"),
        ({"2026-08-18": "action"}, "action_without_status_labels", None, "heads.action.status_labels"),
        ({"2026-08-18": "action"}, "action_without_label_columns", None, "heads.action.label_columns"),
        (
            {"2026-08-18": "network_with_vectors"},
            "network_with_vectors",
            (project_vectors, "HISTORY_LIMIT", 10),
            "project_vector_settings.history_limit",
        ),
        (
            {"2026-08-18": "network_with_vectors"},
            "network_with_vectors",
            (recipe_module, "MIN_PROJECT_HISTORY_REPORTS", 1),
            "project_vector_settings.min_history_reports",
        ),
    ],
    ids=[
        "daily_retrain",
        "env_lookback_change",
        "network_config_change",
        "skips_a_version_without_a_hash",
        "nothing_hashed_to_compare",
        "ignores_later_versions",
        "rerun_with_the_same_recipe",
        "rerun_with_another_recipe",
        "head_status_labels_change",
        "head_label_columns_change",
        "project_history_limit_change",
        "project_min_history_change",
    ],
)
def test_check_recipe_refuses_a_new_recipe_under_an_old_name(monkeypatch, stored, recipe, patch, changed):
    recipes = {
        "booster": lambda: booster_recipe(REPORT_EMBEDDINGS_FEATURE_SET),
        "network": lambda: network_recipe(NetworkConfig(), ()),
        "network_more_epochs": lambda: network_recipe(NetworkConfig(epochs=NetworkConfig().epochs + 5), ()),
        "network_with_vectors": lambda: network_recipe(NetworkConfig(), PROJECT_VECTOR_KINDS),
        "action": lambda: _action_recipe(ACTION),
        "action_without_status_labels": lambda: _action_recipe(dataclasses.replace(ACTION, status_labels=False)),
        "action_without_label_columns": lambda: _action_recipe(dataclasses.replace(ACTION, label_columns=())),
    }
    objects = dict(
        _stored_version("family", version, None if name is None else recipes[name]())
        for version, name in stored.items()
    )
    if patch is not None:
        monkeypatch.setattr(*patch)
    check = lambda: check_recipe(_S3(objects), "bucket", PREFIX, "family", PARTITION, recipes[recipe]())
    if changed is None:
        check()
        return
    with pytest.raises(dagster.Failure) as failure:
        check()
    assert changed in (failure.value.description or "")


def test_check_recipe_finds_the_recipe_under_an_earlier_dataset_version():
    # A DATASET_VERSION bump moves the models to a new folder, so searching only the current one
    # would let the old name train on the new dataset with no recipe to compare against.
    earlier = {**booster_recipe(REPORT_EMBEDDINGS_FEATURE_SET), "dataset_version": "v0"}
    objects = dict([_stored_version("family", "2026-08-18", earlier, dataset_version="v0")])

    with pytest.raises(dagster.Failure) as failure:
        check_recipe(_S3(objects), "bucket", PREFIX, "family", PARTITION, booster_recipe(REPORT_EMBEDDINGS_FEATURE_SET))
    assert "dataset_version" in (failure.value.description or "")
