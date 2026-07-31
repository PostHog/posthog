"""Dispatch and poll Tasks that must run in another PostHog cell.

A `posthog` cross-region Integration (see `posthog.models.integration`) holds a user-consented,
refreshable OAuth grant against a target cell. This module uses that grant to drive the target
cell's Tasks API over HTTP: create a task there (which runs region-resident, e.g. against a
direct-connect source only reachable from that region) and poll it back.

Nothing but the create request and the (bounded, scrubbed) report crosses the cell boundary — the
target task mints its own sandbox credentials in-cell and reads the region-resident data there.
"""

from __future__ import annotations

from typing import Any

import requests
import structlog

from posthog.models.integration import (
    POSTHOG_CROSS_REGION_KIND,
    Integration,
    OauthIntegration,
    posthog_cross_region_base_url,
)

logger = structlog.get_logger(__name__)

# Cross-cell HTTP calls are user-interactive (dispatch) or polled (get), so keep the timeout tight.
CROSS_REGION_REQUEST_TIMEOUT_SECONDS = 30

# WS6 residency bound: cap the derived report that crosses back to the connecting cell. A reference
# to target-cell storage is useless cross-region (the connecting cell can't dereference it), so the
# report must cross by value — and therefore must be size-bounded. Kept conservative; the exact
# limit and scrub policy are pending the residency ruling (see the GATE task).
CROSS_REGION_REPORT_MAX_CHARS = 50_000


class CrossRegionError(Exception):
    """Base error for cross-region task dispatch/polling."""


class CrossRegionIntegrationError(CrossRegionError):
    """The integration is missing, the wrong kind, or has no usable credential."""


class CrossRegionRequestError(CrossRegionError):
    """The target cell rejected the request or was unreachable."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _usable_access_token(integration: Integration) -> str:
    """Return a currently-valid access token for the target cell, refreshing in place if expired.

    The credential lives only here in the Django app DB (encrypted) — it is never handed to a
    sandbox. A failed refresh (revoked/expired grant) surfaces as a reconnect error rather than a
    silent 401 downstream.
    """
    if integration.kind != POSTHOG_CROSS_REGION_KIND:
        raise CrossRegionIntegrationError(f"Integration {integration.id} is not a posthog cross-region integration")

    oauth = OauthIntegration(integration)
    if oauth.access_token_expired():
        oauth.refresh_access_token()
        integration.refresh_from_db()

    token = integration.sensitive_config.get("access_token")
    if not token:
        raise CrossRegionIntegrationError(
            "This cross-region connection has no usable access token — reconnect the integration."
        )
    return token


def _target_base_url(integration: Integration) -> str:
    return posthog_cross_region_base_url(integration.config.get("region"))


def _request(
    integration: Integration, method: str, path: str, *, json: dict[str, Any] | None = None
) -> requests.Response:
    token = _usable_access_token(integration)
    base = _target_base_url(integration)
    try:
        res = requests.request(
            method,
            f"{base}{path}",
            json=json,
            headers={"Authorization": f"Bearer {token}"},
            timeout=CROSS_REGION_REQUEST_TIMEOUT_SECONDS,
            # A compromised/misconfigured target must not be able to 30x us into resending the
            # bearer token to another origin.
            allow_redirects=False,
        )
    except requests.RequestException as err:
        raise CrossRegionRequestError(f"Could not reach the {integration.config.get('region')} region: {err}") from err
    return res


def _raise_for_status(integration: Integration, res: requests.Response, action: str) -> None:
    if 200 <= res.status_code < 300:
        return
    logger.warning(
        "cross_region_task_request_failed",
        action=action,
        integration_id=integration.id,
        region=integration.config.get("region"),
        status_code=res.status_code,
        body=res.text[:500],
    )
    detail = "authorization failed — reconnect the integration" if res.status_code in (401, 403) else res.text[:200]
    raise CrossRegionRequestError(
        f"Remote task {action} failed ({res.status_code}): {detail}", status_code=res.status_code
    )


def scrub_cross_region_report(report: str | None) -> str | None:
    """Bound (and, once the residency ruling lands, scrub) a report derived from region-resident data
    before it crosses back to the connecting cell.

    v1 enforces only the size bound. The authoritative scrub should ultimately run target-side before
    the report leaves its cell; this connecting-cell bound is the interim single chokepoint. See the
    residency GATE task before widening what crosses.
    """
    if report is None:
        return None
    if len(report) <= CROSS_REGION_REPORT_MAX_CHARS:
        return report
    return report[:CROSS_REGION_REPORT_MAX_CHARS] + "\n\n[truncated — report exceeded cross-region size limit]"


def dispatch_remote_task(
    integration: Integration,
    *,
    target_team_id: int,
    description: str,
    title: str | None = None,
    repository: str | None = None,
) -> dict[str, Any]:
    """Create a Task in the integration's target cell, scoped to `target_team_id`.

    Authorization is the connected user's own permissions in the target cell — if they can't create
    tasks on `target_team_id` there, the target returns 403 and this raises. Returns a handle the
    caller polls with `get_remote_task`.
    """
    payload: dict[str, Any] = {"description": description, "origin_product": "user_created"}
    if title:
        payload["title"] = title
        payload["title_manually_set"] = True
    if repository:
        payload["repository"] = repository

    res = _request(integration, "POST", f"/api/projects/{target_team_id}/tasks/", json=payload)
    _raise_for_status(integration, res, "dispatch")
    task = res.json()

    region = integration.config.get("region")
    return {
        "region": region,
        "target_team_id": target_team_id,
        "task_id": task.get("id"),
        "task_number": task.get("task_number"),
        "title": task.get("title"),
        "status": (task.get("latest_run") or {}).get("status"),
    }


def get_remote_task(integration: Integration, *, target_team_id: int, task_id: str) -> dict[str, Any]:
    """Poll a previously dispatched remote task. Returns its status plus the bounded, scrubbed report."""
    res = _request(integration, "GET", f"/api/projects/{target_team_id}/tasks/{task_id}/")
    _raise_for_status(integration, res, "poll")
    task = res.json()

    latest_run = task.get("latest_run") or {}
    return {
        "region": integration.config.get("region"),
        "target_team_id": target_team_id,
        "task_id": task.get("id"),
        "status": latest_run.get("status"),
        "report": scrub_cross_region_report(latest_run.get("output")),
        "error_message": latest_run.get("error_message"),
    }
