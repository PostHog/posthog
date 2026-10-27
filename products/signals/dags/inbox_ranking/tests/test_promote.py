import json
import datetime
from typing import Any

import pytest

import dagster

from posthog import settings

from products.signals.backend.ranking.features import REPORT_EMBEDDINGS_FEATURE_SET
from products.signals.backend.ranking.serving_manifest import ServingManifest, serving_manifest_key
from products.signals.dags.inbox_ranking.common import partition_object_key
from products.signals.dags.inbox_ranking.dataset.dag import PROJECT_VECTORS_TABLE
from products.signals.dags.inbox_ranking.tests.test_training import _AppObjectStore, _ModelStoreS3, _patch_capture
from products.signals.dags.inbox_ranking.training.dag import METADATA_FILE, model_object_key, served_object_key
from products.signals.dags.inbox_ranking.training.families import ModelFamily
from products.signals.dags.inbox_ranking.training.heads import HEADS_BY_NAME
from products.signals.dags.inbox_ranking.training.promote import PromoteConfig, inbox_ranking_promote
from products.signals.dags.inbox_ranking.training.telemetry import MODEL_PROMOTED_EVENT

PREFIX = settings.INBOX_RANKING_DATASET_S3_PREFIX
SERVED_VERSION = "2026-10-16"
OLDER_VERSION = "2026-10-01"
# A retired XGBoost family. A rollback can still serve one of its saved versions.
XGBOOST_MODEL_NAME = "report_embeddings_v2"
EXPERIMENT_MODEL_NAME = "report_embeddings_experiment"


class _WritableS3(_ModelStoreS3):
    def put_object(self, *, Bucket, Key, Body, ContentType=None):
        self.objects[Key] = Body


def _metadata(version: str, heads: tuple[str, ...], model_name: str = XGBOOST_MODEL_NAME) -> dict[str, Any]:
    return {
        "model_name": model_name,
        "model_version": version,
        "feature_set": REPORT_EMBEDDINGS_FEATURE_SET.name,
        "feature_schema_version": REPORT_EMBEDDINGS_FEATURE_SET.schema_version,
        "feature_names": list(REPORT_EMBEDDINGS_FEATURE_SET.feature_names),
        "heads": [{"head": head, "readable": True, "file": f"{head}.ubj"} for head in heads],
    }


def _add_model(
    objects: dict[str, bytes],
    version: str,
    heads: tuple[str, ...],
    *,
    files: bool = True,
    model_name: str = XGBOOST_MODEL_NAME,
) -> None:
    folder = model_object_key(PREFIX, model_name, version, "")
    objects[folder + METADATA_FILE] = json.dumps(_metadata(version, heads, model_name)).encode()
    if files:
        for head in heads:
            objects[folder + f"{head}.ubj"] = b"booster"


def _dataset() -> _WritableS3:
    all_heads = tuple(sorted(HEADS_BY_NAME))
    objects: dict[str, bytes] = {
        served_object_key(PREFIX): json.dumps(
            {
                "model_key": f"{XGBOOST_MODEL_NAME}@{SERVED_VERSION}",
                "model_name": XGBOOST_MODEL_NAME,
                "model_version": SERVED_VERSION,
            }
        ).encode(),
    }
    yesterday = (datetime.datetime.now(datetime.UTC).date() - datetime.timedelta(days=1)).isoformat()
    objects[partition_object_key(PREFIX, PROJECT_VECTORS_TABLE, yesterday)] = b"vectors"
    _add_model(objects, SERVED_VERSION, all_heads)
    _add_model(objects, OLDER_VERSION, all_heads)
    _add_model(objects, "2026-09-01", all_heads, files=False)
    _add_model(objects, "2026-09-02", all_heads[:1])
    # Every head and every file: only being an experiment keeps it from serving.
    _add_model(objects, SERVED_VERSION, all_heads, model_name=EXPERIMENT_MODEL_NAME)
    return _WritableS3(objects)


def _promote(monkeypatch: pytest.MonkeyPatch, client: _WritableS3, store: _AppObjectStore, model_key: str):
    capture = _patch_capture(monkeypatch, cloud=True, debug=False)
    monkeypatch.setattr(settings, "INBOX_RANKING_DATASET_S3_BUCKET", "test-bucket")
    monkeypatch.setattr(settings, "INBOX_RANKING_SERVING_MIRROR_BUCKET", "")
    monkeypatch.setattr(
        "products.signals.dags.inbox_ranking.training.dag.MODEL_FAMILIES",
        (
            ModelFamily(name=XGBOOST_MODEL_NAME, feature_set=REPORT_EMBEDDINGS_FEATURE_SET),
            ModelFamily(
                name=EXPERIMENT_MODEL_NAME,
                feature_set=REPORT_EMBEDDINGS_FEATURE_SET,
                experiment=True,
                baseline=XGBOOST_MODEL_NAME,
                expires=datetime.date(2026, 12, 31),
            ),
        ),
    )
    for module in ("dag", "promote"):
        monkeypatch.setattr(f"products.signals.dags.inbox_ranking.training.{module}.s3_client", lambda: client)
    monkeypatch.setattr("posthog.storage.object_storage.object_storage_client", lambda: store)
    with dagster.build_op_context() as context:
        inbox_ranking_promote(context, PromoteConfig(model_key=model_key, reason="roll back"))
    return capture


def test_a_rollback_to_an_older_version_rewrites_the_pointer_and_publishes_it(monkeypatch):
    client, store = _dataset(), _AppObjectStore()

    capture = _promote(monkeypatch, client, store, f"{XGBOOST_MODEL_NAME}@{OLDER_VERSION}")

    pointer = json.loads(client.objects[served_object_key(PREFIX)])
    assert (pointer["model_key"], pointer["previous_key"], pointer["reason"]) == (
        f"{XGBOOST_MODEL_NAME}@{OLDER_VERSION}",
        f"{XGBOOST_MODEL_NAME}@{SERVED_VERSION}",
        "roll back",
    )
    manifest = ServingManifest.model_validate_json(store.objects[serving_manifest_key(PREFIX)])
    assert manifest.served.key == pointer["model_key"]
    [event] = [call["properties"] for call in capture.calls if call["event"] == MODEL_PROMOTED_EVENT]
    assert event["model_key"] == pointer["model_key"]
    assert event["previous_key"] == pointer["previous_key"]


@pytest.mark.parametrize(
    "model_key,message",
    [
        ("report_embeddings@latest", "not a `<model_name>@<YYYY-MM-DD>` model key"),
        (f"{XGBOOST_MODEL_NAME}@2026-09-01", "missing model files"),
        (f"{XGBOOST_MODEL_NAME}@2026-09-02", "has no model for the heads"),
        (f"{EXPERIMENT_MODEL_NAME}@{SERVED_VERSION}", "is an experiment family, and an experiment never serves"),
    ],
    ids=["malformed_key", "missing_file", "missing_head", "experiment"],
)
def test_a_model_the_sweep_could_not_serve_is_refused_and_nothing_is_written(monkeypatch, model_key, message):
    client, store = _dataset(), _AppObjectStore()
    before = dict(client.objects)

    with pytest.raises(dagster.Failure, match=message):
        _promote(monkeypatch, client, store, model_key)

    assert client.objects == before
    assert store.objects == {}
