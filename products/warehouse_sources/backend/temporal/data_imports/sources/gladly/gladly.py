import re
import json
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.settings import GLADLY_ENDPOINTS

REQUEST_TIMEOUT_SECONDS = 300
# 10 req/s per org; back off on 429.
MAX_RETRY_ATTEMPTS = 5
# Yield JSONL rows in chunks so big files don't build one giant list.
CHUNK_SIZE = 5000


class GladlyRetryableError(Exception):
    pass


@dataclasses.dataclass
class GladlyResumeConfig:
    # Jobs are processed oldest-first; persisting the last fully-processed
    # job's updatedAt lets a retried sync skip straight past it.
    last_job_updated_at: str


def _get_session(agent_email: str, api_token: str) -> requests.Session:
    session = make_tracked_session(redact_values=(api_token,))
    session.auth = (agent_email, api_token)
    return session


def _clean_organization(organization: str) -> str:
    """Accept either the bare org subdomain or a pasted full domain/URL."""
    org = organization.strip().removeprefix("https://").removeprefix("http://")
    org = org.split(".")[0].split("/")[0]
    if not re.fullmatch(r"[a-zA-Z0-9-]+", org):
        raise ValueError(f"Invalid Gladly organization: {organization}")
    return org


def _base_url(organization: str) -> str:
    return f"https://{_clean_organization(organization)}.gladly.com/api/v1"


def _format_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00.000Z")
    return str(value)


def validate_credentials(organization: str, agent_email: str, api_token: str) -> bool:
    """Confirm the credentials are valid with a cheap agents probe."""
    # Resolve the org first so a malformed organization surfaces its own ValueError
    # rather than being mislabelled as a credentials problem by the caller.
    base_url = _base_url(organization)
    try:
        response = _get_session(agent_email, api_token).get(
            f"{base_url}/agents",
            timeout=15,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    organization: str,
    agent_email: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GladlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = GLADLY_ENDPOINTS[endpoint]
    session = _get_session(agent_email, api_token)
    base_url = _base_url(organization)

    @retry(
        retry=retry_if_exception_type((GladlyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=90),
        reraise=True,
    )
    def fetch(url: str) -> requests.Response:
        # stream=True keeps the large JSONL export files off the heap — iter_lines()
        # then streams them. The small jobs-list call still works with .json().
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS, stream=True)

        if response.status_code == 429 or response.status_code >= 500:
            raise GladlyRetryableError(f"Gladly API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Gladly API error: status={response.status_code}, body={response.text[:500]}, url={url}")
            response.raise_for_status()

        return response

    # The cutoff is the later of the incremental watermark and the resume
    # state, so retried syncs skip already-processed jobs either way.
    cutoff: Optional[str] = None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        cutoff = _format_timestamp(db_incremental_field_last_value)
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and (cutoff is None or resume_config.last_job_updated_at > cutoff):
        cutoff = resume_config.last_job_updated_at
        logger.debug(f"Gladly: resuming {endpoint} after job updatedAt {cutoff}")

    jobs_body = fetch(f"{base_url}/export/jobs?{urlencode({'status': 'COMPLETED'})}").json()
    jobs = jobs_body if isinstance(jobs_body, list) else []
    jobs = [job for job in jobs if job.get("updatedAt")]
    jobs.sort(key=lambda job: job["updatedAt"])

    for job in jobs:
        job_updated_at = job["updatedAt"]
        # Strict less-than: jobs sharing the cutoff timestamp are re-yielded rather
        # than skipped, so a late-arriving job with the same updatedAt as the
        # watermark isn't lost. Merge-on-id dedupes the boundary job's re-yielded rows.
        if cutoff is not None and job_updated_at < cutoff:
            continue

        files = job.get("files") or []
        if config.filename not in files:
            continue

        # id is required per the export contract and is needed for the download
        # URL — a missing one is a broken API response, so fail loud.
        job_id = job["id"]

        response = fetch(f"{base_url}/export/jobs/{quote(job_id)}/files/{quote(config.filename)}")
        chunk: list[dict[str, Any]] = []
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                logger.warning(f"Gladly: skipping malformed JSONL line in job {job_id} {config.filename}")
                continue
            chunk.append({**row, "_job_id": job_id, "_job_updated_at": job_updated_at})
            if len(chunk) >= CHUNK_SIZE:
                yield chunk
                chunk = []
        if chunk:
            yield chunk

        # Save state AFTER the job's file is fully yielded so a crash re-yields
        # this job (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(GladlyResumeConfig(last_job_updated_at=job_updated_at))


def gladly_source(
    organization: str,
    agent_email: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GladlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = GLADLY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            organization=organization,
            agent_email=agent_email,
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        # Jobs are processed oldest-first, so the injected job watermark only
        # moves forward.
        sort_mode="asc",
    )
