"""
SDK Doctor alerts — emit `$sdk_doctor_alert_firing` internal events when a team
has outdated SDKs, with a per-team cooldown so subscribers aren't spammed.

The event is consumed by HogFunctions that users create via the AlertWizard in
the SDK Doctor scene (Slack / Discord / Teams / email / webhook).

Outdatedness detection lives in `products/growth/backend/sdk_health.py`; this
module is the thin adapter between that report and the CDP event bus.
"""

from __future__ import annotations

from typing import Any

import structlog

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client

from products.growth.backend.sdk_health import SdkHealthReport

logger = structlog.get_logger(__name__)


SDK_DOCTOR_ALERT_EVENT = "$sdk_doctor_alert_firing"

# One week between alert emissions per team, so subscribers aren't spammed daily
# while the underlying SDKs stay outdated.
ALERT_COOLDOWN_SECONDS = 7 * 24 * 60 * 60


def alert_cooldown_key(team_id: int) -> str:
    return f"sdk_doctor:alert_cooldown:{team_id}"


def _is_on_cooldown(team_id: int) -> bool:
    try:
        return bool(get_client().get(alert_cooldown_key(team_id)))
    except Exception as e:
        logger.warning(
            "Failed to read SDK Doctor alert cooldown; proceeding as if not on cooldown",
            team_id=team_id,
            error=str(e),
        )
        return False


def _set_cooldown(team_id: int) -> None:
    try:
        get_client().setex(alert_cooldown_key(team_id), ALERT_COOLDOWN_SECONDS, b"1")
    except Exception as e:
        logger.warning("Failed to set SDK Doctor alert cooldown", team_id=team_id, error=str(e))


def _build_event_properties(report: SdkHealthReport) -> dict[str, Any]:
    outdated_sdks = [
        {
            "sdk_type": sdk.lib,
            "name": sdk.readable_name,
            "latest_version": sdk.latest_version,
            "current_version": sdk.releases[0].version if sdk.releases else None,
            "severity": sdk.severity,
            "is_outdated": sdk.is_outdated,
            "is_old": sdk.is_old,
            "reason": sdk.reason,
            "banners": list(sdk.banners),
        }
        for sdk in report.sdks
        if sdk.needs_updating
    ]

    return {
        "outdated_sdks": outdated_sdks,
        "needs_updating_count": report.needs_updating_count,
        "team_sdk_count": report.team_sdk_count,
        "overall_health": report.overall_health,
        "health": report.health,
    }


def emit_sdk_doctor_alert_event(
    team_id: int,
    report: SdkHealthReport,
    *,
    force: bool = False,
) -> bool:
    """
    Emit `$sdk_doctor_alert_firing` for a team whose SDKs need updating.

    Returns True if the event was produced, False if skipped (report is healthy
    or cooldown active). Honors a 7-day per-team cooldown; pass `force=True`
    to bypass (used by manual-trigger paths and tests).
    """
    if report.overall_health != "needs_attention" or report.needs_updating_count == 0:
        return False

    if not force and _is_on_cooldown(team_id):
        logger.debug("SDK Doctor alert on cooldown, skipping", team_id=team_id)
        return False

    try:
        produce_internal_event(
            team_id=team_id,
            event=InternalEventEvent(
                event=SDK_DOCTOR_ALERT_EVENT,
                distinct_id=f"team_{team_id}",
                properties=_build_event_properties(report),
            ),
        )
    except Exception as e:
        logger.exception("Failed to produce SDK Doctor alert event", team_id=team_id, error=str(e))
        capture_exception(e, additional_properties={"team_id": team_id})
        return False

    _set_cooldown(team_id)
    return True


def report_to_event_payload(report: SdkHealthReport) -> dict[str, Any]:
    """Public helper for tests / manual inspection of the event payload shape."""
    return _build_event_properties(report)


__all__ = [
    "SDK_DOCTOR_ALERT_EVENT",
    "ALERT_COOLDOWN_SECONDS",
    "alert_cooldown_key",
    "emit_sdk_doctor_alert_event",
    "report_to_event_payload",
]
