"""Read access to trial-run output written by the batch-import worker.

The worker lays results out as `{prefix}/team_{team_id}/job_{job_id}/pages/{page:05}.jsonl`
plus a `summary.json`; this module only reads them back for the API. Objects
expire via an S3 lifecycle rule on the prefix, so a missing object for a known
page means the results are gone, not that the path is wrong.
"""

import json

from django.conf import settings

import structlog
from boto3 import client as boto3_client
from botocore.client import Config
from botocore.exceptions import ClientError

logger = structlog.get_logger(__name__)


class TrialResultsUnavailable(Exception):
    """The requested trial object no longer exists (expired) or storage is not configured."""


def is_configured() -> bool:
    return bool(settings.MANAGED_MIGRATIONS_TRIAL_S3_BUCKET)


def _client():
    return boto3_client(
        "s3",
        endpoint_url=settings.MANAGED_MIGRATIONS_TRIAL_S3_ENDPOINT or None,
        aws_access_key_id=settings.MANAGED_MIGRATIONS_TRIAL_S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.MANAGED_MIGRATIONS_TRIAL_S3_SECRET_ACCESS_KEY,
        region_name=settings.MANAGED_MIGRATIONS_TRIAL_S3_REGION,
        config=Config(signature_version="s3v4", connect_timeout=5, retries={"max_attempts": 2}),
    )


def _job_prefix(team_id: int, job_id: str) -> str:
    prefix = settings.MANAGED_MIGRATIONS_TRIAL_S3_PREFIX.strip("/")
    return f"{prefix}/team_{team_id}/job_{job_id}"


def _read_object(key: str) -> bytes:
    if not is_configured():
        raise TrialResultsUnavailable("trial storage is not configured")
    try:
        response = _client().get_object(Bucket=settings.MANAGED_MIGRATIONS_TRIAL_S3_BUCKET, Key=key)
        return response["Body"].read()
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "NoSuchBucket", "404"):
            raise TrialResultsUnavailable(f"trial object {key} not found") from exc
        logger.exception("managed_migrations.trial_storage.read_failed", key=key)
        raise


def read_trial_page(team_id: int, job_id: str, page: int) -> list[dict]:
    """Return one page of trial records (source event, outputs, error), in order.

    Raises TrialResultsUnavailable when the page object is gone (lifecycle
    expiry) or storage is not configured.
    """
    key = f"{_job_prefix(team_id, job_id)}/pages/{page:05}.jsonl"
    body = _read_object(key)
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
