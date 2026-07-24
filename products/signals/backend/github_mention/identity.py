"""Resolve a GitHub PR commenter to an eligible, push-capable PostHog user.

This is the security boundary for the @-mention trigger. Identity is anchored on the commenter's
**immutable GitHub account id** (from the webhook payload), never the login string — a login is
renamable and reusable, so matching on it would let someone claim another person's PostHog identity.
The account-id match against a personal GitHub connection is trustworthy because that connection was
established via an OAuth flow proving control of the account.
"""

from dataclasses import dataclass
from enum import Enum

from posthog.models import OrganizationMembership, Team, User
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration

from products.signals.backend.report_generation.resolve_reviewers import get_org_member_github_login_to_user_map


class MentionIdentityStatus(Enum):
    # Commenter is an org member with a usable personal GitHub connection covering the repo — run as them.
    ELIGIBLE = "eligible"
    # Commenter needs to connect (or re-scope) a personal GitHub connection before we can run as them.
    # Covers: no connection at all, an unusable/expired one, one that doesn't cover the repo, and the
    # can't-resolve-the-person-yet case. All lead to the connect-gate (link + pending-mention row).
    NEEDS_CONNECT = "needs_connect"
    # Commenter is a known GitHub identity that is definitively NOT a member of this PR's org.
    NOT_MEMBER = "not_member"


@dataclass
class MentionIdentity:
    status: MentionIdentityStatus
    # Set when we could resolve the commenter to a PostHog user (always for ELIGIBLE; sometimes for
    # NEEDS_CONNECT when the login mapped to a member who simply lacks a push token).
    user: User | None = None
    # Set only for ELIGIBLE — the push-capable personal GitHub connection to author commits with.
    user_github_integration: UserGitHubIntegration | None = None


def _integration_is_usable(github: UserGitHubIntegration) -> bool:
    """Push-capable: a user-to-server token exists and its refresh token hasn't expired."""
    return (
        not github.user_refresh_token_expired() and bool(github.user_refresh_token) and bool(github.user_access_token)
    )


def _cached_list_covers(repositories: object, repository_normalized: str) -> bool:
    if not isinstance(repositories, list):
        return False
    return any(str(repo.get("full_name", "")).lower() == repository_normalized for repo in repositories)


def _integration_covers_repository(integration: UserIntegration, repository_normalized: str) -> bool:
    if _cached_list_covers(integration.repository_cache, repository_normalized):
        return True
    # A populated cache that doesn't list the repo is authoritative — the installation doesn't cover it.
    if integration.repository_cache_updated_at is not None:
        return False
    # Never populated (freshly connected) — refresh once before deciding.
    try:
        repositories = UserGitHubIntegration(integration).list_all_cached_repositories()
    except Exception:
        return False
    return _cached_list_covers(repositories, repository_normalized)


def resolve_commenter_identity(
    *,
    team: Team,
    github_account_id: int,
    github_login: str,
    repository: str,
) -> MentionIdentity:
    """Decide whether a commenter may trigger a run on ``repository`` for ``team``'s project."""
    org_id = team.organization_id
    repository_normalized = repository.lower()

    # Personal GitHub connections matching the immutable account id — the trust anchor.
    integrations = list(UserIntegration.objects.filter(kind="github", config__github_user__id=github_account_id))
    if integrations:
        matched_user_ids = {integration.user_id for integration in integrations}
        member_user_ids = set(
            OrganizationMembership.objects.filter(organization_id=org_id, user_id__in=matched_user_ids).values_list(
                "user_id", flat=True
            )
        )
        member_integrations = [i for i in integrations if i.user_id in member_user_ids]
        if not member_integrations:
            # A known GitHub identity, but not a member of this org — cannot run as them, and a connect
            # link wouldn't help (they'd need an org invite, which is outside this flow).
            return MentionIdentity(status=MentionIdentityStatus.NOT_MEMBER)
        for integration in member_integrations:
            github = UserGitHubIntegration(integration)
            if _integration_is_usable(github) and _integration_covers_repository(integration, repository_normalized):
                return MentionIdentity(
                    status=MentionIdentityStatus.ELIGIBLE,
                    user=integration.user,
                    user_github_integration=github,
                )
        # Member(s) matched by id, but no connection is usable / covers this repo — ask them to re-connect.
        return MentionIdentity(status=MentionIdentityStatus.NEEDS_CONNECT, user=member_integrations[0].user)

    # No personal connection by account id. Try to at least identify the member by login so the
    # connect-gate message can be addressed. Login is spoofable, but this branch grants no privilege
    # (no run launches) — it only decides messaging and records a pending row re-checked at replay time.
    login_map = get_org_member_github_login_to_user_map(team.id) or {}
    member = login_map.get(github_login.lower()) if github_login else None
    return MentionIdentity(status=MentionIdentityStatus.NEEDS_CONNECT, user=member)
