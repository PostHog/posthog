"""Self-driving free trial gate.

Sibling of `quota.py` (the org-level billing quota gate) with the same call shape and the same
fail-open posture. While the `self-driving-free-trial` flag is on for an org, Self-driving still
researches and writes reports but opens no pull requests: auto-start creates no implementation
task and the manual create-from-report path refuses one. Nothing is billed because nothing ships
a PR, so the billing exemption and refund machinery in `billing.py` stays untouched.
"""

from typing import TYPE_CHECKING

import structlog
import posthoganalytics
from rest_framework import status
from rest_framework.exceptions import APIException

from posthog.event_usage import groups

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)

# Org-keyed; sales toggles it per trial.
SELF_DRIVING_FREE_TRIAL_FLAG = "self-driving-free-trial"

# Shown wherever a trial org asks for a pull request: the disabled Create PR button and the
# refused create-from-report call. One sentence, so it reads the same on every surface.
FREE_TRIAL_PR_MESSAGE = (
    "During your free trial, Self-driving writes reports but doesn't open pull requests. Contact us to upgrade."
)


class FreeTrialPullRequestRefused(APIException):
    """A trial org asked for a pull request. 402 like the quota gate, with its own code so clients
    can tell the trial apart from a spend limit."""

    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = "self_driving_free_trial"
    default_detail = FREE_TRIAL_PR_MESSAGE


def self_driving_free_trial_enabled(team: "Team") -> bool:
    """Whether the team's org is on a Self-driving free trial.

    Org-keyed like the quota-enforcement and refund flags. Fails open (not on trial) on a
    flag-read error: a flag outage must not stop every org's pull requests. Blocking network
    I/O; wrap in `sync_to_async` from async code.
    """
    try:
        org_id = str(team.organization_id)
        return (
            posthoganalytics.feature_enabled(
                SELF_DRIVING_FREE_TRIAL_FLAG,
                org_id,
                groups={"organization": org_id},
                group_properties={"organization": {"id": org_id}},
            )
            is True
        )
    except Exception:
        logger.warning("self_driving_free_trial_flag_check_failed", exc_info=True)
        return False


def capture_signal_report_free_trial_paused(team: "Team", *, report_id: str | None, stage: str) -> None:
    """`signal_report_free_trial_paused`: a gate held back a pull request at `stage` because the
    team's org is on a free trial. Every event is a real block. Best-effort: telemetry must never
    fail the step that emitted it. Requires `team.organization` to be loaded.
    """
    try:
        posthoganalytics.capture(
            event="signal_report_free_trial_paused",
            distinct_id=str(team.uuid),
            properties={
                "team_id": team.id,
                "organization_id": str(team.organization_id),
                "report_id": report_id,
                "stage": stage,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.exception(
            "Failed to capture signal_report_free_trial_paused", report_id=report_id, team_id=team.id, stage=stage
        )
