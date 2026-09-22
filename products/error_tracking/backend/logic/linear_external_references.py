import re
from collections.abc import Mapping
from typing import Any

from django.db import transaction

from posthog.models.integration import Integration

from products.error_tracking.backend.facade import contracts
from products.error_tracking.backend.logic import external_references
from products.error_tracking.backend.logic.posthog_issue_links import extract_posthog_issue_references, resolve_issue
from products.error_tracking.backend.models import ErrorTrackingIssue

_SUPPORTED_ACTIONS = frozenset({"create", "update"})
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9]+-[0-9]+")
_IDENTIFIER_FROM_URL_PATTERN = re.compile(r"/issue/([A-Za-z0-9]+-[0-9]+)")
# create_external_reference refuses a longer title, and the task would then retry to exhaustion
# over a title Linear will never shorten.
_MAX_TITLE_LENGTH = 500


def prepare_jobs(event_type: str, payload: dict[str, Any]) -> list[contracts.LinearExternalReferenceJob]:
    if event_type not in {"Issue", "Comment"} or payload.get("action") not in _SUPPORTED_ACTIONS:
        return []

    text_field = "description" if event_type == "Issue" else "body"
    # Without updatedFrom, Linear gives no evidence about which fields changed, so process the text.
    if payload.get("action") == "update" and "updatedFrom" in payload:
        updated_from = payload["updatedFrom"]
        if not isinstance(updated_from, Mapping) or text_field not in updated_from:
            return []

    data = payload.get("data")
    organization_id = payload.get("organizationId")
    if not isinstance(data, dict) or not isinstance(organization_id, str) or not organization_id:
        return []

    text = data.get(text_field)
    if not isinstance(text, str) or not text.strip():
        return []

    if event_type == "Issue":
        identifier = data.get("identifier")
        title = data.get("title")
    else:
        # A comment payload is not guaranteed to carry the parent issue, so both fields stay
        # optional here and the URL below supplies the identifier.
        raw_parent_issue = data.get("issue")
        parent_issue: dict[str, Any] = raw_parent_issue if isinstance(raw_parent_issue, dict) else {}
        identifier = parent_issue.get("identifier")
        title = parent_issue.get("title")

    if identifier is None:
        url = payload.get("url")
        identifier_match = _IDENTIFIER_FROM_URL_PATTERN.search(url) if isinstance(url, str) else None
        identifier = identifier_match.group(1) if identifier_match is not None else None

    if not isinstance(identifier, str) or not _IDENTIFIER_PATTERN.fullmatch(identifier):
        return []
    title = title.strip()[:_MAX_TITLE_LENGTH] if isinstance(title, str) and title.strip() else identifier

    return [
        contracts.LinearExternalReferenceJob(
            team_id=reference.team_id,
            organization_id=organization_id,
            identifier=identifier,
            title=title,
            issue_id=reference.issue_id,
            fingerprint=reference.fingerprint,
        )
        for reference in extract_posthog_issue_references(text)
    ]


def link_reference(job: contracts.LinearExternalReferenceJob) -> bool:
    # The URL names the PostHog team and the signed payload names the Linear workspace, so this
    # lookup permits a link only when that exact team connected that exact workspace. There is no
    # per-actor permission call because only workspace members or guests can edit Linear text,
    # unlike GitHub repositories that outside contributors can edit without write permission.
    integration = (
        Integration.objects.filter(
            team_id=job.team_id,
            kind=Integration.IntegrationKind.LINEAR.value,
            integration_id=job.organization_id,
        )
        .order_by("id")
        .first()
    )
    if integration is None:
        return False

    issue = resolve_issue(team_id=job.team_id, issue_id=job.issue_id, fingerprint=job.fingerprint)
    if issue is None:
        return False

    with transaction.atomic():
        locked_issue = ErrorTrackingIssue.objects.select_for_update().filter(team_id=job.team_id, id=issue.id).first()
        if locked_issue is None:
            return False
        # Linear text already carries the pasted link, so no back-link is needed. Attaching one would
        # hold the issue row lock open across an HTTP request.
        _, created = external_references.create_external_reference(
            team_id=job.team_id,
            issue_id=locked_issue.id,
            integration_id=integration.id,
            external_context={"id": job.identifier, "title": job.title},
            attach_backlink=False,
        )
    return created
