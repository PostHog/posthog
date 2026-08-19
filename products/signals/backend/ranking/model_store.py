"""Where the ranking model lives and how the sweep loads it.

The training dag (`products/signals/dags/inbox_ranking/training/`) writes one candidate per day
under `inbox_ranking_models/v1/dt=<version>/` and points `champion.json` at the one to serve. The
key layout here is that contract; the dag imports it. Loading asserts the serving-side feature
contract: a booster trained under a different feature schema or with different feature names is
refused rather than scored, because a silent mismatch produces confident garbage.
"""

import json
from collections.abc import Mapping
from typing import Any

import boto3
import xgboost as xgb
from botocore.exceptions import ClientError

from posthog import settings
from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION

DATASET_VERSION = "v1"
MODELS_TABLE = "inbox_ranking_models"
CHAMPION_FILE = "champion.json"
METADATA_FILE = "metadata.json"


class ModelContractError(Exception):
    """The champion artifact does not match the feature contract this code can serve."""


def model_object_key(prefix: str, model_version: str, filename: str) -> str:
    return f"{prefix}/{MODELS_TABLE}/{DATASET_VERSION}/dt={model_version}/{filename}"


def champion_object_key(prefix: str) -> str:
    return f"{prefix}/{MODELS_TABLE}/{DATASET_VERSION}/{CHAMPION_FILE}"


def ranking_bucket() -> str:
    return settings.INBOX_RANKING_DATASET_S3_BUCKET or settings.OBJECT_STORAGE_BUCKET


# boto3.client("s3") is left untyped on purpose: mypy and pyright resolve it to different stub
# packages, so a concrete S3Client annotation can't satisfy both. Mirrors the dag's
# `common.s3_client`: the dedicated bucket via ambient AWS config, the deployment's object-storage
# service everywhere else.
def ranking_s3_client():  # noqa: ANN201
    if settings.INBOX_RANKING_DATASET_S3_BUCKET:
        return boto3.client("s3")
    return boto3.client(
        "s3",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        region_name=settings.OBJECT_STORAGE_REGION,
    )


@frozen
class RankingModel:
    model_version: str
    feature_schema_version: int
    # head name -> booster; only heads the champion could read are served.
    boosters: Mapping[str, xgb.Booster]
    metadata: Mapping[str, Any]


def _read_object(client, bucket: str, key: str) -> bytes | None:
    try:
        return client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def booster_from_bytes(raw: bytes) -> xgb.Booster:
    booster = xgb.Booster()
    booster.load_model(bytearray(raw))
    return booster


def assert_feature_contract(metadata: Mapping[str, Any], boosters: Mapping[str, xgb.Booster]) -> None:
    version = metadata.get("feature_schema_version")
    if version != FEATURE_SCHEMA_VERSION:
        raise ModelContractError(f"champion feature_schema_version {version} != serving {FEATURE_SCHEMA_VERSION}")
    names = metadata.get("feature_names")
    if names != list(FEATURE_NAMES):
        raise ModelContractError("champion feature_names differ from the serving feature universe")
    for head, booster in boosters.items():
        if booster.feature_names != list(FEATURE_NAMES):
            raise ModelContractError(f"{head} booster feature_names differ from the serving feature universe")


def load_champion(client=None) -> RankingModel | None:  # noqa: ANN001
    """The champion model, or None when no champion has been promoted yet."""
    client = client or ranking_s3_client()
    bucket, prefix = ranking_bucket(), settings.INBOX_RANKING_DATASET_S3_PREFIX
    raw = _read_object(client, bucket, champion_object_key(prefix))
    if raw is None:
        return None
    metadata = json.loads(raw)
    model_version = str(metadata["model_version"])
    boosters: dict[str, xgb.Booster] = {}
    for head in metadata.get("heads", []):
        if not head.get("readable"):
            continue
        body = _read_object(client, bucket, model_object_key(prefix, model_version, head["file"]))
        if body is None:
            raise ModelContractError(f"champion {model_version} names {head['file']} but the object is missing")
        boosters[head["head"]] = booster_from_bytes(body)
    assert_feature_contract(metadata, boosters)
    return RankingModel(
        model_version=model_version,
        feature_schema_version=int(metadata["feature_schema_version"]),
        boosters=boosters,
        metadata=metadata,
    )
