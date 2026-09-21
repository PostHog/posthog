import re
from urllib.parse import unquote
from uuid import UUID

from django.conf import settings

from posthog.dataclasses import frozen

from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueFingerprintV2

MAX_REFERENCES_PER_WEBHOOK = 20


@frozen
class PostHogIssueReference:
    team_id: int
    issue_id: UUID | None = None
    fingerprint: str | None = None


def extract_posthog_issue_references(body: str) -> list[PostHogIssueReference]:
    site_url = re.escape(settings.SITE_URL.rstrip("/"))
    pattern = re.compile(
        rf"{site_url}/project/(?P<team_id>[1-9][0-9]*)/error_tracking/"
        rf"(?:fingerprint/(?P<fingerprint>[^/?#\s<>\]\)]+)|"
        rf"(?P<issue_id>[0-9a-fA-F]{{8}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-"
        rf"[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{12}}))"
    )

    references: list[PostHogIssueReference] = []
    seen: set[PostHogIssueReference] = set()
    for match in pattern.finditer(body):
        issue_id = match.group("issue_id")
        reference = PostHogIssueReference(
            team_id=int(match.group("team_id")),
            issue_id=UUID(issue_id) if issue_id else None,
            fingerprint=unquote(match.group("fingerprint")) if match.group("fingerprint") else None,
        )
        if reference in seen:
            continue
        seen.add(reference)
        references.append(reference)
        if len(references) == MAX_REFERENCES_PER_WEBHOOK:
            break
    return references


def resolve_issue(*, team_id: int, issue_id: UUID | None, fingerprint: str | None) -> ErrorTrackingIssue | None:
    if issue_id is not None:
        return ErrorTrackingIssue.objects.filter(team_id=team_id, id=issue_id).first()
    if fingerprint is None:
        return None
    fingerprint_record = ErrorTrackingIssueFingerprintV2.objects.filter(
        team_id=team_id, fingerprint=fingerprint
    ).first()
    return fingerprint_record.issue if fingerprint_record is not None else None
