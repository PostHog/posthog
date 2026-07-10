import dataclasses
from collections.abc import Callable, Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.vellum.settings import (
    VELLUM_BASE_URL,
    VELLUM_ENDPOINTS,
    VellumEndpointConfig,
)

PAGE_SIZE = 100


class VellumRetryableError(Exception):
    pass


@dataclasses.dataclass
class VellumResumeConfig:
    # Next `offset` to request for the resource currently being paginated.
    offset: int = 0
    # Fan-out only: the workflow deployment whose execution events we're partway through. A stable id
    # bookmark (not a positional index) so deployments added/removed between a crash and the retry can't
    # resume us into the wrong parent. None for the standard top-level endpoints.
    deployment_id: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {"X-API-KEY": api_key, "Accept": "application/json"}


def check_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe an auth-gated list endpoint. Returns ``(reachable, status_code)``.

    ``/document-indexes`` strictly requires a key (unlike ``/workflow-deployments``, which serves
    public demo data without one), so a 200 confirms the key is genuinely valid.
    """
    url = f"{VELLUM_BASE_URL}/document-indexes"
    try:
        session = make_tracked_session(redact_values=(api_key,))
        response = session.get(url, headers=_get_headers(api_key), params={"limit": 1}, timeout=10)
        return response.status_code == 200, response.status_code
    except Exception:
        return False, None


@retry(
    retry=retry_if_exception_type(
        (
            VellumRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict:
    response = session.get(url, headers=headers, params=params, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise VellumRetryableError(f"Vellum API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404 is expected during the execution-events fan-out (a deployment deleted mid-sync).
        # Never log the response body: Vellum error payloads can echo synced execution data
        # (workflow inputs/outputs), which must not leak into operational logs.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Vellum API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    return response.json()


def _paginate(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[VellumResumeConfig],
    ordering: str | None,
    start_offset: int,
    deployment_id: str | None,
    transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> Iterator[Any]:
    """Walk a Vellum list endpoint via `limit`/`offset` and yield batches.

    Vellum's list responses carry `count`/`results` (top-level endpoints also carry `next`/`previous`,
    but the execution-events response does not), so we page purely on offset and stop when a page comes
    back short or the accumulated offset reaches `count`. When a batch is yielded we save the *current*
    page's offset (not the next page's): a crash then resumes by re-fetching this page and merge dedupes
    the rows already yielded on the primary key. Advancing the saved offset past the current page could
    skip its unyielded tail.
    """
    offset = start_offset
    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE, "offset": offset}
        if ordering:
            params["ordering"] = ordering

        data = _fetch_page(session, url, headers, params, logger)
        results = data.get("results", [])
        count = data.get("count")

        for item in results:
            batcher.batch(transform(item) if transform else item)
            if batcher.should_yield():
                yield batcher.get_table()
                manager.save_state(VellumResumeConfig(offset=offset, deployment_id=deployment_id))

        offset += len(results)
        if not results or (count is not None and offset >= count):
            break


def _iter_workflow_deployment_ids(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[str]:
    """Page through /workflow-deployments (oldest-first) yielding each deployment id for the fan-out."""
    offset = 0
    while True:
        params = {"limit": PAGE_SIZE, "offset": offset, "ordering": "created"}
        data = _fetch_page(session, f"{VELLUM_BASE_URL}/workflow-deployments", headers, params, logger)
        results = data.get("results", [])
        if not results:
            break
        for item in results:
            yield item["id"]
        offset += len(results)
        count = data.get("count")
        if count is not None and offset >= count:
            break


def _get_execution_event_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[VellumResumeConfig],
    config: VellumEndpointConfig,
) -> Iterator[Any]:
    """Fan out over every workflow deployment, pulling its execution events and stamping the parent id.

    The parent id is injected under `config.parent_id_field` so the composite primary key
    (`[workflow_deployment_id, span_id]`) is unique across the whole table. Full refresh: we can't
    verify Vellum's `filters`/`ordering` params for this endpoint without a live key, so we don't rely
    on them and merge dedupes across syncs.
    """
    # Fan-out configs always set `parent_id_field`; assert it so the child-row injection is well-typed.
    parent_id_field = config.parent_id_field
    assert parent_id_field is not None, "fan-out endpoints must define parent_id_field"

    deployment_ids = list(_iter_workflow_deployment_ids(session, headers, logger))

    resume = manager.load_state() if manager.can_resume() else None
    remaining = deployment_ids
    resume_offset = 0
    if resume is not None and resume.deployment_id is not None and resume.deployment_id in deployment_ids:
        remaining = deployment_ids[deployment_ids.index(resume.deployment_id) :]
        resume_offset = resume.offset
        logger.debug(
            f"Vellum: resuming execution events from deployment_id={resume.deployment_id}, offset={resume_offset}"
        )

    for index, deployment_id in enumerate(remaining):
        start_offset = resume_offset
        resume_offset = 0  # only the resumed-into deployment uses the saved offset
        url = f"{VELLUM_BASE_URL}{config.path.replace('{deployment_id}', deployment_id)}"

        def _inject_parent_id(
            item: dict[str, Any], _dep_id: str = deployment_id, _field: str = parent_id_field
        ) -> dict[str, Any]:
            item[_field] = _dep_id
            return item

        try:
            yield from _paginate(
                session,
                url,
                headers,
                logger,
                batcher,
                manager,
                ordering=None,
                start_offset=start_offset,
                deployment_id=deployment_id,
                transform=_inject_parent_id,
            )
        except requests.HTTPError as exc:
            # A deployment deleted between enumeration and this fetch 404s. Skip it rather than failing
            # the whole sync; any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Vellum: workflow deployment {deployment_id} not found while fetching events, skipping")
            else:
                raise

        # Advance the bookmark to the next deployment so a crash between deployments resumes correctly.
        if index + 1 < len(remaining):
            manager.save_state(VellumResumeConfig(offset=0, deployment_id=remaining[index + 1]))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[VellumResumeConfig],
) -> Iterator[Any]:
    config = VELLUM_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    session = make_tracked_session(redact_values=(api_key,))

    if config.fan_out_over_workflow_deployments:
        yield from _get_execution_event_rows(session, headers, logger, batcher, resumable_source_manager, config)
    else:
        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        start_offset = resume.offset if resume is not None else 0
        if start_offset:
            logger.debug(f"Vellum: resuming {endpoint} from offset={start_offset}")
        yield from _paginate(
            session,
            f"{VELLUM_BASE_URL}{config.path}",
            headers,
            logger,
            batcher,
            resumable_source_manager,
            ordering=config.ordering,
            start_offset=start_offset,
            deployment_id=None,
        )

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def vellum_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[VellumResumeConfig],
) -> SourceResponse:
    config = VELLUM_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
