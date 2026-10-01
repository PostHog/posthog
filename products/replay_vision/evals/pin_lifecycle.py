"""Keep a pinned golden dataset on the same lifecycle as the recordings it copies.

A pinned case is live only while its source recording is: the recording API still returns it, and
its `expiry_time` has not passed. Deleting a recording (by a user, a person deletion, or a team
deletion) hides its metadata, so the API returns 404 for it. Readers drop dead cases before they
fetch any bytes, and `prune_pinned_datasets` deletes the bytes of dead cases from every pinned
version.

This module imports neither Django nor the dataset models, so the prune job can run it with only
boto3 and requests installed:

    POSTHOG_API_KEY=... REPLAY_VISION_EVAL_DATASET_BUCKET=... \\
        python -m products.replay_vision.evals.pin_lifecycle --prefix replay-vision/golden/
"""

import os
import json
import argparse
import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any
from urllib.parse import quote

import requests

DATASET_BUCKET_ENV_VAR = "REPLAY_VISION_EVAL_DATASET_BUCKET"
# Optional S3 endpoint override, for a local S3-compatible store; unset means AWS.
DATASET_ENDPOINT_ENV_VAR = "REPLAY_VISION_EVAL_DATASET_ENDPOINT"
MANIFEST_NAME = "manifest.json"
VIDEO_NAME = "video.mp4"
INPUTS_NAME = "inputs.json"
# A case id is also a directory and key segment, so it must not be able to leave its prefix.
CASE_ID_PATTERN = r"^[A-Za-z0-9_-]+$"
# The checks send POSTHOG_API_KEY to the manifest's host, so a tampered manifest must not
# be able to send the key to any other origin.
CONSENT_HOSTS = ("https://us.posthog.com", "https://eu.posthog.com")


def api_headers(host: str, api_key: str) -> dict[str, str]:
    if host.rstrip("/") not in CONSENT_HOSTS:
        raise RuntimeError(f"Dataset host {host!r} is not one of {CONSENT_HOSTS}; refusing to send the API key")
    if not api_key:
        raise RuntimeError("Set POSTHOG_API_KEY so the dataset's source recordings and consent can be re-verified")
    return {"Authorization": f"Bearer {api_key}"}


def recording_is_live(*, host: str, project_id: int, session_id: str, api_key: str, now: dt.datetime) -> bool:
    """Whether the source recording still exists and has not expired; raises when the API cannot say."""
    response = requests.get(
        f"{host.rstrip('/')}/api/environments/{project_id}/session_recordings/{quote(session_id, safe='')}/",
        headers=api_headers(host, api_key),
        timeout=60,
    )
    if response.status_code == 404:
        return False
    response.raise_for_status()
    # Compared directly, because the metadata row outlives `expiry_time` until ClickHouse merges its TTL.
    expiry = response.json().get("expiry_time")
    return expiry is not None and dt.datetime.fromisoformat(expiry) > now


def live_session_ids(*, host: str, project_id: int, session_ids: Iterable[str], api_key: str) -> set[str]:
    now = dt.datetime.now(dt.UTC)
    return {
        session_id
        for session_id in set(session_ids)
        if recording_is_live(host=host, project_id=project_id, session_id=session_id, api_key=api_key, now=now)
    }


def case_key(manifest_key: str, case_id: str, file_name: str) -> str:
    """Object key of one case file; the case files sit beside the manifest."""
    return f"{manifest_key.rsplit('/', 1)[0]}/cases/{case_id}/{file_name}"


def pin_client() -> Any:
    """S3 client for the pin, on the default AWS credential chain.

    Not `posthog.storage.object_storage`: that client takes a fixed key pair from Django settings and
    no session token, so it cannot use the temporary credentials of GitHub OIDC or AWS SSO.
    """
    import boto3  # noqa: PLC0415 - keeps boto3 off the eval import path
    from botocore.config import Config  # noqa: PLC0415 - keeps boto3 off the eval import path

    return boto3.client(
        "s3",
        endpoint_url=os.environ.get(DATASET_ENDPOINT_ENV_VAR, "").strip() or None,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )


def _object_keys(client: Any, bucket: str, prefix: str) -> Iterator[str]:
    token: str | None = None
    while True:
        page = client.list_objects_v2(Bucket=bucket, Prefix=prefix, **({"ContinuationToken": token} if token else {}))
        yield from (item["Key"] for item in page.get("Contents", []))
        token = page.get("NextContinuationToken")
        if not token:
            return


def prune_pinned_datasets(*, client: Any, bucket: str, prefix: str, api_key: str) -> list[str]:
    """Remove every pinned case whose source recording is deleted or expired.

    Covers every pinned version under `prefix`, because versions share no files but can share a
    recording. The case files go first and the manifest is rewritten last, so a run that fails
    between the two leaves the dead entries for the next run. Any API error stops the run before
    a later deletion, so an outage never deletes a live case.
    """
    deleted: list[str] = []
    liveness: dict[tuple[str, int, str], bool] = {}
    now = dt.datetime.now(dt.UTC)
    keys = set(_object_keys(client, bucket, prefix))
    for manifest_key in sorted(key for key in keys if key.endswith(f"/{MANIFEST_NAME}")):
        manifest = json.loads(client.get_object(Bucket=bucket, Key=manifest_key)["Body"].read())
        host, project_id = str(manifest["host"]), int(manifest["project_id"])
        live_cases = []
        for case in manifest.get("cases", []):
            case_id, session_id = str(case["case_id"]), str(case["session_id"])
            source = (host, project_id, session_id)
            if source not in liveness:
                liveness[source] = recording_is_live(
                    host=host, project_id=project_id, session_id=session_id, api_key=api_key, now=now
                )
            if liveness[source]:
                live_cases.append(case)
                continue
            for file_name in (VIDEO_NAME, INPUTS_NAME):
                key = case_key(manifest_key, case_id, file_name)
                if key not in keys:
                    continue
                client.delete_object(Bucket=bucket, Key=key)
                deleted.append(key)
        if len(live_cases) < len(manifest.get("cases", [])):
            client.put_object(
                Bucket=bucket, Key=manifest_key, Body=json.dumps({**manifest, "cases": live_cases}, indent=2).encode()
            )
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bucket", default=os.environ.get(DATASET_BUCKET_ENV_VAR, ""), help="Pin bucket.")
    parser.add_argument("--prefix", required=True, help="Key prefix that holds the pinned versions.")
    args = parser.parse_args()
    if not args.bucket:
        parser.error(f"pass --bucket or set {DATASET_BUCKET_ENV_VAR}")
    deleted = prune_pinned_datasets(
        client=pin_client(), bucket=args.bucket, prefix=args.prefix, api_key=os.environ.get("POSTHOG_API_KEY", "")
    )
    # A count only: the job log is public, and keys carry observation ids.
    print(f"Deleted {len(deleted)} case files whose source recording is deleted or expired")  # noqa: T201


if __name__ == "__main__":
    main()
