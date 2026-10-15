import io
import json
import datetime
from typing import Any

import pytest

import numpy as np
import dagster
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.exceptions import ClientError
from sklearn.metrics import roc_auc_score

from posthog import settings

from products.signals.backend.ranking.model_contract import model_mismatch
from products.signals.backend.ranking.model_store import ONNX_OUTPUT_HEADS_KEY
from products.signals.backend.ranking.overrides import NO_OVERRIDES
from products.signals.backend.ranking.serving_manifest import CROSS_FAMILY_ROLE, ONNX_MODEL_FILE, ONNX_MODEL_KIND
from products.signals.dags.inbox_ranking.common import partition_object_key
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
    onnx_probabilities,
)
from products.signals.dags.inbox_ranking.tests.test_multihead import D0, DAYS, HOLDOUT_DAYS, _SyntheticInbox
from products.signals.dags.inbox_ranking.training.dag import (
    CHAMPION_FILE,
    METADATA_FILE,
    champion_object_key,
    inbox_ranking_model_candidate,
    inbox_ranking_model_champion,
    model_object_key,
)
from products.signals.dags.inbox_ranking.training.serving import FamilyModels, compose_manifest
from products.signals.dags.inbox_ranking.training.train import HeadMetrics
from products.signals.dags.inbox_ranking.training.unseen import (
    NN_MODEL_NAME,
    REPORT_EMBEDDINGS_MODEL_NAME,
    TITLE_EMBEDDINGS_MODEL_NAME,
)

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

    def paginate(self, *, Bucket, Prefix):
        yield {"Contents": [{"Key": key} for key in sorted(self.objects) if key.startswith(Prefix)]}

    def delete_objects(self, *, Bucket, Delete):
        for obj in Delete["Objects"]:
            self.objects.pop(obj["Key"])


def _parquet(table: pa.Table) -> bytes:
    sink = io.BytesIO()
    pq.write_table(table, sink)
    return sink.getvalue()


def _trained_network() -> TrainedNetwork:
    metrics = HeadMetrics(
        head="open",
        train_rows=400,
        train_positives=120,
        holdout_rows=200,
        holdout_positives=60,
        holdout_auc=0.8,
        null_auc=0.5,
        null_auc_std=0.01,
        readable=True,
    )
    return TrainedNetwork(
        output_heads=NN_HEAD_NAMES,
        model_onnx=b"graph",
        holdout_model_onnx=b"holdout-graph",
        heads=(NetworkHead(metrics=metrics, calibration=()),),
        skipped=(),
        network_train_rows=400,
        refit_rows=600,
        vector_kinds=(),
    )


def _nn_metadata(version: str) -> dict[str, Any]:
    return candidate_metadata(
        version, _trained_network(), config=NetworkConfig(), windows={}, trained_at=NOW, run_id="run-1"
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
    monkeypatch.setattr(settings, "INBOX_RANKING_AUTO_PROMOTE", True)


def test_the_main_location_never_fits_or_promotes_nn(monkeypatch, no_side_effects):
    # Every family has a candidate and no champion, so the main champion asset promotes each family
    # it walks. An `nn` pointer written here would name XGBoost files the sweep loads as ONNX.
    client = _S3(
        {
            model_object_key(PREFIX, name, PARTITION, METADATA_FILE): json.dumps(
                _xgboost_metadata(name, PARTITION)
            ).encode()
            for name in (REPORT_EMBEDDINGS_MODEL_NAME, TITLE_EMBEDDINGS_MODEL_NAME, NN_MODEL_NAME)
        }
    )
    monkeypatch.setattr("products.signals.dags.inbox_ranking.training.dag.s3_client", lambda: client)

    with dagster.build_asset_context(partition_key=PARTITION) as context:
        inbox_ranking_model_candidate(context)
        inbox_ranking_model_champion(context)

    champions = {key.split("/")[-2] for key in client.objects if key.endswith(CHAMPION_FILE)}
    assert champions == {REPORT_EMBEDDINGS_MODEL_NAME, TITLE_EMBEDDINGS_MODEL_NAME}
    assert not [key for key in client.objects if f"/{NN_MODEL_NAME}/" in key and not key.endswith(METADATA_FILE)]


def test_the_manifest_carries_an_nn_champion_as_an_onnx_entry():
    decision = compose_manifest(
        [
            FamilyModels(
                name=REPORT_EMBEDDINGS_MODEL_NAME,
                candidate=None,
                champion=_xgboost_metadata(REPORT_EMBEDDINGS_MODEL_NAME, "2026-08-15"),
            ),
            FamilyModels(name=NN_MODEL_NAME, candidate=None, champion=_nn_metadata("2026-08-16")),
        ],
        served_family=REPORT_EMBEDDINGS_MODEL_NAME,
        prefix=PREFIX,
        now=NOW,
    )

    assert decision.manifest is not None
    (entry,) = [entry for entry in decision.manifest.models if entry.model_name == NN_MODEL_NAME]
    assert entry.roles == [CROSS_FAMILY_ROLE]
    assert entry.model_kind == ONNX_MODEL_KIND
    assert entry.files == [ONNX_MODEL_FILE]
    assert entry.heads == ["open"]


def test_nn_promotion_writes_only_its_own_pointer(no_side_effects):
    other_champion = json.dumps(_xgboost_metadata(REPORT_EMBEDDINGS_MODEL_NAME, "2026-08-15")).encode()
    client = _S3(
        {
            model_object_key(PREFIX, NN_MODEL_NAME, PARTITION, METADATA_FILE): json.dumps(
                _nn_metadata(PARTITION)
            ).encode(),
            champion_object_key(PREFIX, REPORT_EMBEDDINGS_MODEL_NAME): other_champion,
        }
    )
    before = set(client.objects)

    with dagster.build_asset_context(partition_key=PARTITION) as context:
        nn_dag.decide_champion(context, client, "bucket", PARTITION)

    assert set(client.objects) - before == {champion_object_key(PREFIX, NN_MODEL_NAME)}
    assert client.objects[champion_object_key(PREFIX, REPORT_EMBEDDINGS_MODEL_NAME)] == other_champion
    assert json.loads(client.objects[champion_object_key(PREFIX, NN_MODEL_NAME)])["model_version"] == PARTITION


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
