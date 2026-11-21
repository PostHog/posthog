"""External references from Linear tickets whose description links to a PostHog error tracking issue.

A linked issue gets the same reference a user adds by hand, so the issue shows the ticket and the
Linear status sync acts on it. Only a project that connects the ticket's Linear workspace gets the
reference, and only when its token can read the ticket and confirm the actor's team access.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction

from posthog import regions
from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.ingress.contracts import DeliveryOwnership
from posthog.integrations import IntegrationManager, IntegrationRecord
from posthog.models.integration import LinearIntegration
from posthog.models.integration.linear import LinearIssueForReference
from posthog.ph_client import ph_scoped_capture

from products.error_tracking.backend.facade import contracts
from products.error_tracking.backend.logic import external_references
from products.error_tracking.backend.logic.linear_workspace import workspace_ownership
from products.error_tracking.backend.models import ErrorTrackingExternalReference, ErrorTrackingIssue

# Linear lists only the fields an update changed in `updatedFrom`. An update that changes neither of
# these cannot add a link or rename a linked ticket.
_LINKING_FIELDS = ("description", "title")
_IDENTIFIER = re.compile(r"[A-Za-z0-9]+-[1-9][0-9]*")
_MAX_TITLE_LENGTH = 500


@frozen
class _Ticket:
    organization_id: str
    id: UUID
    actor_id: UUID
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
    actor = payload.get("actor")
    if (
        not isinstance(organization_id, str)
        or not organization_id
        or not isinstance(data, Mapping)
        or not isinstance(actor, Mapping)
        or actor.get("type") != "user"
    ):
        return None
    try:
        ticket_id = UUID(str(data.get("id")))
        actor_id = UUID(str(actor.get("id")))
    except ValueError:
        return None
    identifier = data.get("identifier")
    description = data.get("description")
    if not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier) or not isinstance(description, str):
        return None
    title = data.get("title")
    title = title.strip()[:_MAX_TITLE_LENGTH].strip() if isinstance(title, str) else ""
    return _Ticket(
        organization_id=organization_id,
        id=ticket_id,
        actor_id=actor_id,
        identifier=identifier,
        title=title or None,
        description=description,
    )


def prepare_jobs(payload: Mapping[str, Any]) -> list[contracts.LinearExternalReferenceJob]:
    ticket = _ticket(payload)
    if ticket is None:
        return []
    return [
        contracts.LinearExternalReferenceJob(
            team_id=reference.team_id,
            organization_id=ticket.organization_id,
            ticket_id=ticket.id,
            actor_id=ticket.actor_id,
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
    if ticket is None or not external_references.extract_posthog_issue_references(
        ticket.description,
        site_urls=(
            settings.SITE_URL,
            f"https://{regions.PRIMARY_REGION_DOMAIN}",
            f"https://{regions.SECONDARY_REGION_DOMAIN}",
        ),
    ):
        return DeliveryOwnership.UNDECIDED
    return workspace_ownership(ticket.organization_id)


@frozen
class _ReferenceAccessKey:
    integration_id: int
    ticket_id: UUID
    actor_id: UUID


def link_reference(job: contracts.LinearExternalReferenceJob) -> bool:
    return link_references([job])[0]


def link_references(jobs: Sequence[contracts.LinearExternalReferenceJob]) -> list[bool]:
    access: dict[_ReferenceAccessKey, LinearIssueForReference | None] = {}
    return [_link_reference(job, access) for job in jobs]


def _link_reference(
    job: contracts.LinearExternalReferenceJob,
    access: dict[_ReferenceAccessKey, LinearIssueForReference | None],
) -> bool:
    integration = IntegrationManager.linear.oauth.find(job.team_id, external_id=job.organization_id)
    if integration is None:
        return False
    issue = external_references.resolve_referenced_issue(
        job.team_id, issue_id=job.issue_id, fingerprint=job.fingerprint
    )
    if issue is None:
        return False

    from products.error_tracking.backend.logic.linear_status_sync import (  # noqa: PLC0415 - issue_mutations imports the facade through core tasks
        issue_status_lock,
    )

    with issue_status_lock(issue.id):
        key = _ReferenceAccessKey(integration_id=integration.id, ticket_id=job.ticket_id, actor_id=job.actor_id)
        if key not in access:
            access[key] = LinearIntegration(integration).issue_for_reference(str(job.ticket_id), str(job.actor_id))
        ticket = access[key]
        if ticket is None:
            return False
        return _link_and_reconcile(job, integration, issue, ticket)


def _link_and_reconcile(
    job: contracts.LinearExternalReferenceJob,
    integration: IntegrationRecord,
    issue: ErrorTrackingIssue,
    ticket: LinearIssueForReference,
) -> bool:
    external_context: dict[str, Any] = {"id": ticket.identifier}
    if job.title is not None:
        external_context["title"] = job.title
    with transaction.atomic():
        locked_issue = ErrorTrackingIssue.objects.select_for_update().filter(team_id=job.team_id, id=issue.id).first()
        if locked_issue is None:
            return False
        references = ErrorTrackingExternalReference.objects.filter(
            issue_id=locked_issue.id,
            integration_id=integration.id,
            external_context__id__in={job.identifier, *ticket.previous_identifiers} - {ticket.identifier},
        )
        for reference in references:
            reference.external_context = {**(reference.external_context or {}), "id": ticket.identifier}
            reference.save(update_fields=["external_context"])
        # The event snapshot authorizes the link even if the description changed while the task waited.
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
    from products.error_tracking.backend.logic.linear_status_sync import (  # noqa: PLC0415 - issue_mutations imports the facade through core tasks
        reconcile_linked_issue,
    )

    # Reconcile on retries too: the reference may have committed before a previous status read failed.
    reconcile_linked_issue(issue, organization_id=job.organization_id, identifier=ticket.identifier)
    return created
