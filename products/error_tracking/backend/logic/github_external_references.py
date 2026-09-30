import re
from typing import Any, Literal
from urllib.parse import unquote
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from posthog.dataclasses import frozen
from posthog.models.integration import GitHubIntegration, Integration

from products.error_tracking.backend.facade import contracts
from products.error_tracking.backend.logic import external_references
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueFingerprintV2

# A cheap shed before we spend a Celery task and a GitHub API call, not a trust gate: OWNER and
# MEMBER say nothing about access to this repo, and COLLABORATOR covers read/triage-only invites.
# CONTRIBUTOR is admitted because the field is unreliable in App-delivered payloads: GitHub
# computes it with less context than a user-token call, so org members on private repos arrive
# downgraded. link_reference holds the authoritative gate (see _WRITE_PERMISSIONS).
_PAYLOAD_GATE_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR", "CONTRIBUTOR"})
_SUPPORTED_ACTIONS = frozenset({"opened", "edited"})
_MAX_REFERENCES_PER_WEBHOOK = 20

# The reference is permanent (references cannot be deleted), so linking must require someone who
# could change the repo anyway. GitHub's legacy permission field folds maintain into write and
# triage into read.
#
# Asymmetric cache TTLs: a cached ALLOW is a revocation window, so it stays short. A cached DENY
# only delays a just-promoted collaborator's first link, which is harmless.
_WRITE_PERMISSIONS = frozenset({"admin", "write"})
_ACTOR_PERMISSION_ALLOW_CACHE_SECONDS = 60
_ACTOR_PERMISSION_DENY_CACHE_SECONDS = 10 * 60


@frozen
class _PostHogIssueReference:
    team_id: int
    issue_id: UUID | None = None
    fingerprint: str | None = None


def prepare_jobs(event_type: str, payload: dict[str, Any]) -> list[contracts.GitHubExternalReferenceJob]:
    resource_type: Literal["issue", "pull_request"]
    resource: Any
    if event_type == "issues":
        resource_type = "issue"
        resource = payload.get("issue")
    elif event_type == "pull_request":
        resource_type = "pull_request"
        resource = payload.get("pull_request")
    else:
        return []

    if payload.get("action") not in _SUPPORTED_ACTIONS or not isinstance(resource, dict):
        return []

    sender = payload.get("sender") or {}
    # A bot (dependabot, renovate) cannot be a repo collaborator, so the permission lookup would
    # only ever deny it. Drop it here rather than pay a task and an API call to reach that answer.
    if sender.get("type") == "Bot":
        return []

    # The actor is the sender, not the resource author: on an edit they are different people, and
    # only the sender chose to add the link. author_association describes the author, so it says
    # something about the actor only when the two are the same person.
    actor_login = sender.get("login")
    author_login = (resource.get("user") or {}).get("login")
    if (
        actor_login == author_login
        and str(resource.get("author_association") or "").upper() not in _PAYLOAD_GATE_ASSOCIATIONS
    ):
        return []

    installation_id = (payload.get("installation") or {}).get("id")
    repository_full_name = (payload.get("repository") or {}).get("full_name")
    number = resource.get("number")
    title = resource.get("title")
    body = resource.get("body")
    if (
        not isinstance(actor_login, str)
        or not actor_login
        or isinstance(installation_id, bool)
        or not isinstance(installation_id, int)
        or installation_id <= 0
        or not isinstance(repository_full_name, str)
        or repository_full_name.count("/") != 1
        or isinstance(number, bool)
        or not isinstance(number, int)
        or number <= 0
        or not isinstance(title, str)
        or not isinstance(body, str)
    ):
        return []

    return [
        contracts.GitHubExternalReferenceJob(
            team_id=reference.team_id,
            installation_id=str(installation_id),
            repository_full_name=repository_full_name,
            number=number,
            title=title,
            resource_type=resource_type,
            actor_login=actor_login,
            issue_id=reference.issue_id,
            fingerprint=reference.fingerprint,
        )
        for reference in _extract_posthog_issue_references(body)
    ]


def _extract_posthog_issue_references(body: str) -> list[_PostHogIssueReference]:
    site_url = re.escape(settings.SITE_URL.rstrip("/"))
    pattern = re.compile(
        rf"{site_url}/project/(?P<team_id>[1-9][0-9]*)/error_tracking/"
        rf"(?:fingerprint/(?P<fingerprint>[^/?#\s<>\]\)]+)|"
        rf"(?P<issue_id>[0-9a-fA-F]{{8}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-"
        rf"[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{12}}))"
    )

    references: list[_PostHogIssueReference] = []
    seen: set[_PostHogIssueReference] = set()
    for match in pattern.finditer(body):
        issue_id = match.group("issue_id")
        reference = _PostHogIssueReference(
            team_id=int(match.group("team_id")),
            issue_id=UUID(issue_id) if issue_id else None,
            fingerprint=unquote(match.group("fingerprint")) if match.group("fingerprint") else None,
        )
        if reference in seen:
            continue
        seen.add(reference)
        references.append(reference)
        if len(references) == _MAX_REFERENCES_PER_WEBHOOK:
            break
    return references


def _resolve_issue(job: contracts.GitHubExternalReferenceJob) -> ErrorTrackingIssue | None:
    if job.issue_id is not None:
        return ErrorTrackingIssue.objects.filter(team_id=job.team_id, id=job.issue_id).first()
    if job.fingerprint is None:
        return None
    fingerprint = ErrorTrackingIssueFingerprintV2.objects.filter(
        team_id=job.team_id, fingerprint=job.fingerprint
    ).first()
    return fingerprint.issue if fingerprint is not None else None


def _actor_lacks_write_permission(integration: Integration, job: contracts.GitHubExternalReferenceJob) -> bool:
    """Whether the actor's effective permission on the repo is below write.

    This is the only gate that proves repo access, because the webhook's author_association
    does not.
    Costs a GitHub API call, so it runs after the cheaper checks and the result is cached briefly
    per (integration, repo, login). Lookup errors propagate: the caller retries the delivery rather
    than failing open.
    """
    cache_key = (
        f"error_tracking:github_actor_permission:{integration.id}:"
        f"{job.repository_full_name.casefold()}:{job.actor_login.casefold()}"
    )
    permission = cache.get(cache_key)
    if permission is None:
        permission = GitHubIntegration(integration).get_collaborator_permission(
            job.repository_full_name, job.actor_login
        )
        ttl = (
            _ACTOR_PERMISSION_ALLOW_CACHE_SECONDS
            if permission in _WRITE_PERMISSIONS
            else _ACTOR_PERMISSION_DENY_CACHE_SECONDS
        )
        cache.set(cache_key, permission, ttl)
    return permission not in _WRITE_PERMISSIONS


def link_reference(job: contracts.GitHubExternalReferenceJob) -> bool:
    owner, repository = job.repository_full_name.split("/", 1)
    integration = (
        Integration.objects.filter(
            team_id=job.team_id,
            kind=Integration.IntegrationKind.GITHUB.value,
            integration_id=job.installation_id,
        )
        .order_by("id")
        .first()
    )
    if integration is None:
        return False
    try:
        integration_owner = GitHubIntegration(integration).organization()
    except ValueError:
        return False
    if integration_owner.casefold() != owner.casefold():
        return False

    if _actor_lacks_write_permission(integration, job):
        return False

    issue = _resolve_issue(job)
    if issue is None:
        return False

    with transaction.atomic():
        locked_issue = ErrorTrackingIssue.objects.select_for_update().filter(team_id=job.team_id, id=issue.id).first()
        if locked_issue is None:
            return False
        _, created = external_references.create_external_reference(
            team_id=job.team_id,
            issue_id=locked_issue.id,
            integration_id=integration.id,
            external_context={
                "repository": repository,
                "number": job.number,
                "title": job.title,
                "resource_type": job.resource_type,
            },
        )
    return created
