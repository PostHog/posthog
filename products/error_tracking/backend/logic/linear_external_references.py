"""External references from Linear tickets whose description links to a PostHog error tracking issue.

A linked issue gets the same reference a user adds by hand, so the issue shows the ticket and the
Linear status sync acts on it. Only a project that connects the ticket's Linear workspace gets the
reference, and only when that project's token can read the ticket.
"""

import re
from collections.abc import Mapping
from typing import Any

from django.db import transaction

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.ingress.contracts import DeliveryOwnership
from posthog.ingress.dispatch.database import bounded_statement_timeout
from posthog.integrations import IntegrationManager

# `bounded_statement_timeout` gets the database alias of a read from the router, and the router needs
# the model class. So `Integration` is imported only to cap the ownership lookup, and every read of a
# row goes through the SDK.
from posthog.models.integration import (  # nosemgrep: semgrep.rules.devex.integration-model-through-sdk
    Integration,
    LinearIntegration,
)
from posthog.ph_client import ph_scoped_capture

from products.error_tracking.backend.facade import contracts
from products.error_tracking.backend.logic import external_references
from products.error_tracking.backend.models import ErrorTrackingExternalReference, ErrorTrackingIssue

# Linear lists only the fields an update changed in `updatedFrom`. An update that changes neither of
# these cannot add a link or rename a linked ticket.
_LINKING_FIELDS = ("description", "title")
_IDENTIFIER = re.compile(r"[A-Za-z0-9]+-[1-9][0-9]*")
_MAX_TITLE_LENGTH = 500
# Matches a link to any region, because the receiving region decides where a delivery goes before
# the region that holds the issue reads it.
_ANY_REGION_ISSUE_LINK = re.compile(r"/project/[1-9][0-9]*/error[_-]tracking/")
_WORKSPACE_LOOKUP_TIMEOUT_MS = 800


@frozen
class _Ticket:
    organization_id: str
    identifier: str
    title: str | None
    description: str


def _ticket(payload: Mapping[str, Any]) -> _Ticket | None:
    if payload.get("type") != "Issue":
        return None
    action = payload.get("action")
    if action == "update":
        updated_from = payload.get("updatedFrom")
        if not isinstance(updated_from, Mapping) or not any(field in updated_from for field in _LINKING_FIELDS):
            return None
    elif action != "create":
        return None

    organization_id = payload.get("organizationId")
    data = payload.get("data")
    if not isinstance(organization_id, str) or not organization_id or not isinstance(data, Mapping):
        return None
    identifier = data.get("identifier")
    description = data.get("description")
    if not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier) or not isinstance(description, str):
        return None
    title = data.get("title")
    title = title.strip()[:_MAX_TITLE_LENGTH].strip() if isinstance(title, str) else ""
    return _Ticket(organization_id=organization_id, identifier=identifier, title=title or None, description=description)


def prepare_jobs(payload: Mapping[str, Any]) -> list[contracts.LinearExternalReferenceJob]:
    ticket = _ticket(payload)
    if ticket is None:
        return []
    return [
        contracts.LinearExternalReferenceJob(
            team_id=reference.team_id,
            organization_id=ticket.organization_id,
            identifier=ticket.identifier,
            title=ticket.title,
            issue_id=reference.issue_id,
            fingerprint=reference.fingerprint,
        )
        for reference in external_references.extract_posthog_issue_references(ticket.description)
    ]


def delivery_ownership(payload: Mapping[str, Any]) -> DeliveryOwnership:
    """Which region holds the Linear workspace of a ticket that links to an error tracking issue.

    A delivery whose ticket links to no issue is `UNDECIDED`, so the ticket's contents do not cross
    the region boundary. A lookup that raises is let out, so Linear sends the delivery again.
    """
    ticket = _ticket(payload)
    if ticket is None or not _ANY_REGION_ISSUE_LINK.search(ticket.description):
        return DeliveryOwnership.UNDECIDED
    with bounded_statement_timeout(_WORKSPACE_LOOKUP_TIMEOUT_MS, models=[Integration]):
        held_here = IntegrationManager.linear.oauth.exists_by_external_id(ticket.organization_id)
    return DeliveryOwnership.LOCAL if held_here else DeliveryOwnership.ELSEWHERE


def link_reference(job: contracts.LinearExternalReferenceJob) -> bool:
    integration = IntegrationManager.linear.oauth.find(job.team_id, external_id=job.organization_id)
    if integration is None:
        return False
    issue = external_references.resolve_referenced_issue(
        job.team_id, issue_id=job.issue_id, fingerprint=job.fingerprint
    )
    if issue is None:
        return False

    already_linked = ErrorTrackingExternalReference.objects.filter(
        issue_id=issue.id, integration_id=integration.id, external_context__contains={"id": job.identifier}
    ).exists()
    # The status sync reads every linked ticket with this token, and a ticket that it cannot read keeps
    # the issue open. Raises LinearIntegrationError when the read fails, so the task retries.
    if not already_linked and job.identifier not in LinearIntegration(integration).issue_state_types([job.identifier]):
        return False

    external_context: dict[str, Any] = {"id": job.identifier}
    if job.title is not None:
        external_context["title"] = job.title
    with transaction.atomic():
        locked_issue = ErrorTrackingIssue.objects.select_for_update().filter(team_id=job.team_id, id=issue.id).first()
        if locked_issue is None:
            return False
        # The ticket already links to PostHog in its description, so it gets no attachment as well.
        _, created = external_references.create_external_reference(
            team_id=job.team_id,
            issue_id=locked_issue.id,
            integration_id=integration.id,
            external_context=external_context,
            attach_back_link=False,
        )
    if created:
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=str(issue.team.uuid),
                # pinned: analytics event name, renaming it breaks dashboards
                event="error_tracking_issue_linked_from_linear",
                properties={"linked_by": "fingerprint" if job.fingerprint is not None else "issue_id"},
                groups=groups(issue.team.organization, issue.team),
            )
    return created
