import json
import datetime
from typing import Any

import pytest

import dagster
from botocore.exceptions import EndpointConnectionError

from posthog import settings

from products.signals.backend.ranking.features import REPORT_EMBEDDINGS_FEATURE_SET
from products.signals.backend.ranking.overrides import RankingOverrides
from products.signals.backend.ranking.serving_manifest import ServingManifest, serving_manifest_key
from products.signals.dags.inbox_ranking.common import partition_object_key
from products.signals.dags.inbox_ranking.dataset.dag import PROJECT_VECTORS_TABLE
from products.signals.dags.inbox_ranking.tests.test_training import _AppObjectStore, _ModelStoreS3, _patch_capture
from products.signals.dags.inbox_ranking.training import dag
from products.signals.dags.inbox_ranking.training.dag import (
    METADATA_FILE,
    PROMOTION_FILE,
    _publish_manifest,
    model_object_key,
    served_object_key,
)
from products.signals.dags.inbox_ranking.training.families import PAIR_GRAIN, ModelFamily
from products.signals.dags.inbox_ranking.training.heads import HEADS_BY_NAME
from products.signals.dags.inbox_ranking.training.promote import PromoteConfig, inbox_ranking_promote
from products.signals.dags.inbox_ranking.training.telemetry import MODEL_PROMOTED_EVENT

PREFIX = settings.INBOX_RANKING_DATASET_S3_PREFIX
SERVED_VERSION = "2026-10-16"
OLDER_VERSION = "2026-10-01"
# A retired XGBoost family. A rollback can still serve one of its saved versions.
XGBOOST_MODEL_NAME = "report_embeddings_v2"
EXPERIMENT_MODEL_NAME = "report_embeddings_experiment"
PAIR_EXPERIMENT_MODEL_NAME = "report_embeddings_pair_experiment"


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
    _add_model(objects, SERVED_VERSION, all_heads, model_name=PAIR_EXPERIMENT_MODEL_NAME)
    return _WritableS3(objects)


def _patch_stores(monkeypatch: pytest.MonkeyPatch, client: _WritableS3, store: _AppObjectStore):
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
            ModelFamily(
                name=PAIR_EXPERIMENT_MODEL_NAME,
                feature_set=REPORT_EMBEDDINGS_FEATURE_SET,
                experiment=True,
                expires=datetime.date(2026, 12, 31),
                grain=PAIR_GRAIN,
                heads=("open", "action"),
                reference=XGBOOST_MODEL_NAME,
            ),
        ),
    )
    for module in ("dag", "promote"):
        monkeypatch.setattr(f"products.signals.dags.inbox_ranking.training.{module}.s3_client", lambda: client)
    monkeypatch.setattr("posthog.storage.object_storage.object_storage_client", lambda: store)
    return capture


def _promote(monkeypatch: pytest.MonkeyPatch, client: _WritableS3, store: _AppObjectStore, model_key: str):
    capture = _patch_stores(monkeypatch, client, store)
    with dagster.build_op_context() as context:
        inbox_ranking_promote(context, PromoteConfig(model_key=model_key, reason="roll back"))
    return capture


def test_a_rollback_to_an_older_version_rewrites_the_pointer_and_publishes_it(monkeypatch):
    client, store = _dataset(), _AppObjectStore()

    capture = _promote(monkeypatch, client, store, f"{XGBOOST_MODEL_NAME}@{OLDER_VERSION}")

    pointer = json.loads(client.objects[served_object_key(PREFIX)])
    assert (pointer["model_key"], pointer["previous_key"], pointer["reason"], pointer["auto"]) == (
        f"{XGBOOST_MODEL_NAME}@{OLDER_VERSION}",
        f"{XGBOOST_MODEL_NAME}@{SERVED_VERSION}",
        "roll back",
        False,
    )
    manifest = ServingManifest.model_validate_json(store.objects[serving_manifest_key(PREFIX)])
    assert manifest.served.key == pointer["model_key"]
    [event] = [call["properties"] for call in capture.calls if call["event"] == MODEL_PROMOTED_EVENT]
    assert (event["model_key"], event["previous_key"], event["auto"]) == (
        pointer["model_key"],
        pointer["previous_key"],
        False,
    )


@pytest.mark.parametrize("mode", ["due", "held", "pointer_moved", "transport_error"])
def test_the_daily_publish_auto_promotes_the_newest_passing_version_and_serves_it_in_the_same_run(monkeypatch, mode):
    served_key, newer_version, partition_key = f"{XGBOOST_MODEL_NAME}@{SERVED_VERSION}", "2026-10-18", "2026-10-19"
    client, store = _dataset(), _AppObjectStore()
    served = json.loads(client.objects[served_object_key(PREFIX)])
    client.objects[served_object_key(PREFIX)] = json.dumps(
        {**served, "promoted_at": "2026-10-16T05:00:00+00:00"}
    ).encode()
    _add_model(client.objects, newer_version, tuple(sorted(HEADS_BY_NAME)))
    promotion_key = model_object_key(PREFIX, XGBOOST_MODEL_NAME, newer_version, PROMOTION_FILE)
    client.objects[promotion_key] = json.dumps(
        {"would_promote": True, "reason": "candidate at or above", "incumbent_key": served_key}
    ).encode()
    capture = _patch_stores(monkeypatch, client, store)
    monkeypatch.setattr(settings, "INBOX_RANKING_AUTO_PROMOTE_INTERVAL_DAYS", 3)
    monkeypatch.setattr(
        "products.signals.dags.inbox_ranking.training.dag.read_ranking_overrides",
        lambda now: RankingOverrides(hold_auto_promotion=mode == "held"),
    )
    manual_pointer = {**served, "promoted_at": "2026-10-19T05:00:30+00:00", "run_id": "manual"}
    if mode == "pointer_moved":
        original = dag.promotable_model

        def manual_promotion_lands_mid_step(*args, **kwargs):
            client.objects[served_object_key(PREFIX)] = json.dumps(manual_pointer).encode()
            return original(*args, **kwargs)

        monkeypatch.setattr(dag, "promotable_model", manual_promotion_lands_mid_step)
    if mode == "transport_error":
        get_object = client.get_object

        def timing_out_get_object(*, Bucket, Key):
            if Key == promotion_key:
                raise EndpointConnectionError(endpoint_url="https://s3.example.com")
            return get_object(Bucket=Bucket, Key=Key)

        monkeypatch.setattr(client, "get_object", timing_out_get_object)

    _publish_manifest(
        dagster.build_asset_context(partition_key=partition_key), partition_key, "run-1", auto_promote=True
    )

    pointer = json.loads(client.objects[served_object_key(PREFIX)])
    manifest = ServingManifest.model_validate_json(store.objects[serving_manifest_key(PREFIX)])
    events = [call["properties"] for call in capture.calls if call["event"] == MODEL_PROMOTED_EVENT]
    if mode != "due":
        assert pointer == (
            manual_pointer if mode == "pointer_moved" else {**served, "promoted_at": "2026-10-16T05:00:00+00:00"}
        )
        assert manifest.served.key == served_key
        assert events == []
        return
    new_key = f"{XGBOOST_MODEL_NAME}@{newer_version}"
    assert (pointer["model_key"], pointer["previous_key"], pointer["auto"]) == (new_key, served_key, True)
    assert manifest.served.key == new_key
    [event] = events
    assert (event["model_key"], event["previous_key"], event["auto"]) == (new_key, served_key, True)


@pytest.mark.parametrize(
    "model_key,message",
    [
        ("report_embeddings@latest", "not a `<model_name>@<YYYY-MM-DD>` model key"),
        (f"{XGBOOST_MODEL_NAME}@2026-09-01", "missing model files"),
        (f"{XGBOOST_MODEL_NAME}@2026-09-02", "has no model for the heads"),
        (f"{EXPERIMENT_MODEL_NAME}@{SERVED_VERSION}", "is an experiment family, and an experiment never serves"),
        (f"{PAIR_EXPERIMENT_MODEL_NAME}@{SERVED_VERSION}", "is an experiment family, and an experiment never serves"),
    ],
    ids=["malformed_key", "missing_file", "missing_head", "experiment", "pair_experiment"],
)
def test_a_model_the_sweep_could_not_serve_is_refused_and_nothing_is_written(monkeypatch, model_key, message):
    client, store = _dataset(), _AppObjectStore()
    before = dict(client.objects)

    with pytest.raises(dagster.Failure, match=message):
        _promote(monkeypatch, client, store, model_key)

    assert client.objects == before
    assert store.objects == {}
