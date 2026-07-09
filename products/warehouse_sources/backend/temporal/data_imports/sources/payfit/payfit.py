import dataclasses
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.payfit.settings import (
    PAYFIT_ENDPOINTS,
    PayFitEndpointConfig,
)

PAYFIT_BASE_URL = "https://partner-api.payfit.com"
# The API key only grants access to the key's own company; introspection returns its company_id.
PAYFIT_INTROSPECT_URL = "https://oauth.payfit.com/introspect"
# List endpoints accept a `maxResults` of up to 50 (default 10); the largest page minimises round trips.
PAGE_SIZE = 50
REQUEST_TIMEOUT_SECONDS = 60

INVALID_TOKEN_MESSAGE = "PayFit API key is inactive or invalid"


class PayFitRetryableError(Exception):
    pass


class PayFitInvalidTokenError(Exception):
    pass


@dataclasses.dataclass
class PayFitResumeConfig:
    # `nextPageToken` cursor for the next page. For `payslips` this is the cursor of the
    # *collaborators* page being fanned out over. `None` means start from the first page. A crashed
    # sync resumes from the page after the last one yielded; merge dedupes on the primary key.
    next_page_token: str | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((PayFitRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _introspect(session: requests.Session, api_key: str) -> dict[str, Any]:
    response = session.post(
        PAYFIT_INTROSPECT_URL,
        json={"token": api_key},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise PayFitRetryableError(f"PayFit introspection error (retryable): status={response.status_code}")

    # Introspection authenticates with the token itself, so a 401/403 means the key is bad — the
    # same signal as an {"active": false} body.
    if response.status_code in (401, 403):
        return {"active": False}

    if not response.ok:
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict):
        raise PayFitRetryableError(f"PayFit introspection returned an unexpected payload: {type(data).__name__}")
    return data


def get_company_id(session: requests.Session, api_key: str) -> str:
    claims = _introspect(session, api_key)
    if not claims.get("active"):
        raise PayFitInvalidTokenError(INVALID_TOKEN_MESSAGE)

    company_id = claims.get("company_id")
    if not isinstance(company_id, str) or not company_id:
        raise PayFitInvalidTokenError(f"{INVALID_TOKEN_MESSAGE}: introspection returned no company_id")
    return company_id


@retry(
    retry=retry_if_exception_type((PayFitRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    data_key: str,
    next_page_token: str | None,
    extra_params: dict[str, str],
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], str | None]:
    params: dict[str, Any] = {"maxResults": PAGE_SIZE, **extra_params}
    if next_page_token is not None:
        params["nextPageToken"] = next_page_token

    response = session.get(
        f"{PAYFIT_BASE_URL}{path}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise PayFitRetryableError(f"PayFit API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"PayFit API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # List endpoints wrap rows as {"<data_key>": [...], "meta": {"nextPageToken": str | null}}.
    if not isinstance(data, dict) or not isinstance(data.get(data_key), list):
        raise PayFitRetryableError(f"PayFit returned an unexpected payload for {path}: {type(data).__name__}")

    rows: list[dict[str, Any]] = data[data_key]
    meta = data.get("meta") or {}
    next_token = meta.get("nextPageToken") if isinstance(meta, dict) else None
    return rows, next_token or None


@retry(
    retry=retry_if_exception_type((PayFitRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_payslips(
    session: requests.Session,
    company_id: str,
    collaborator_id: str,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    path = f"/companies/{company_id}/collaborators/{collaborator_id}/payslips"
    response = session.get(f"{PAYFIT_BASE_URL}{path}", timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise PayFitRetryableError(f"PayFit API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"PayFit API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("payslips"), list):
        raise PayFitRetryableError(f"PayFit returned an unexpected payload for {path}: {type(data).__name__}")

    # The response only carries year/month/contractId/payslipId, so stamp the parent id onto each
    # row — it is part of the primary key.
    return [{**payslip, "collaboratorId": collaborator_id} for payslip in data["payslips"]]


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PayFitResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = PAYFIT_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    company_id = get_company_id(session, api_key)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    next_page_token = resume.next_page_token if resume else None
    if resume and resume.next_page_token is not None:
        logger.debug(f"PayFit: resuming {endpoint} from page token {next_page_token}")

    if config.fan_out_over_collaborators:
        yield from _get_payslip_rows(session, company_id, next_page_token, logger, resumable_source_manager)
        return

    path = f"/companies/{company_id}{config.path}"
    while True:
        rows, next_token = _fetch_page(session, path, config.data_key, next_page_token, config.extra_params, logger)
        if rows:
            yield rows

        # A missing/null nextPageToken (or an empty page) means we've reached the end of the list.
        if not next_token or not rows:
            break

        next_page_token = next_token
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(PayFitResumeConfig(next_page_token=next_page_token))


def _get_payslip_rows(
    session: requests.Session,
    company_id: str,
    next_page_token: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PayFitResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    # Payslips have no list-all endpoint, so paginate collaborators and fetch each collaborator's
    # payslips. Resume state tracks the collaborators page cursor: one page of collaborators is one
    # yielded batch.
    collaborators_path = f"/companies/{company_id}/collaborators"
    while True:
        collaborators, next_token = _fetch_page(
            session, collaborators_path, "collaborators", next_page_token, {}, logger
        )

        batch: list[dict[str, Any]] = []
        for collaborator in collaborators:
            batch.extend(_fetch_payslips(session, company_id, collaborator["id"], logger))
        if batch:
            yield batch

        if not next_token or not collaborators:
            break

        next_page_token = next_token
        resumable_source_manager.save_state(PayFitResumeConfig(next_page_token=next_page_token))


def payfit_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PayFitResumeConfig],
) -> SourceResponse:
    config = PAYFIT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Validate the API key via token introspection — one cheap probe that needs no endpoint scope
    and also proves we can resolve the company_id every sync depends on."""
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.post(PAYFIT_INTROSPECT_URL, json={"token": api_key}, timeout=15)
    except Exception as e:
        return False, f"Could not connect to PayFit: {e}"

    if response.status_code in (401, 403):
        return False, "Invalid PayFit API key"

    if not response.ok:
        return False, f"PayFit returned HTTP {response.status_code}"

    claims = response.json()
    if not isinstance(claims, dict) or not claims.get("active"):
        return False, "Invalid PayFit API key"

    if not claims.get("company_id"):
        return False, "PayFit token introspection returned no company ID"

    return True, None


def check_schema_access(api_key: str, schema_name: str) -> tuple[bool, str | None]:
    """Probe a single endpoint to confirm the API key carries the scope that schema needs."""
    endpoint_config = PAYFIT_ENDPOINTS[schema_name]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    try:
        company_id = get_company_id(session, api_key)
    except PayFitInvalidTokenError:
        return False, "Invalid PayFit API key"
    except Exception as e:
        return False, f"Could not validate PayFit API key: {e}"

    probe = _probe_endpoint(endpoint_config)
    try:
        response = session.get(
            f"{PAYFIT_BASE_URL}/companies/{company_id}{probe.path}",
            params={"maxResults": 1, **probe.extra_params},
            timeout=15,
        )
    except Exception as e:
        return False, f"Could not connect to PayFit: {e}"

    if response.status_code == 401:
        return False, "Invalid PayFit API key"
    if response.status_code == 403:
        return False, f"Your PayFit API key is missing the `{probe.scope}` scope required for `{schema_name}`"
    if not response.ok:
        return False, f"PayFit returned HTTP {response.status_code}"
    return True, None


def _probe_endpoint(endpoint_config: PayFitEndpointConfig) -> PayFitEndpointConfig:
    # Payslips are enumerated per collaborator, so probe the collaborators dependency instead of a
    # per-collaborator path; a missing `contracts:payslips:read` scope still surfaces as a
    # non-retryable 403 at sync time.
    if endpoint_config.fan_out_over_collaborators:
        return PAYFIT_ENDPOINTS["collaborators"]
    return endpoint_config
