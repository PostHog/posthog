from datetime import timedelta

from django.utils import timezone

from posthog.models.oauth import OAuthAccessToken, find_oauth_access_token, mint_oauth_access_token
from posthog.models.personal_api_key import find_personal_api_key, looks_like_legacy_personal_api_key
from posthog.models.team import Team
from posthog.models.utils import OAUTH_ACCESS_TOKEN_PREFIX, PERSONAL_API_KEY_PREFIX

CONFINED_TOKEN_LIFETIME = timedelta(minutes=15)
CONFINED_TOKEN_MIN_REMAINING = timedelta(minutes=2)


class BorrowedCredentialRefused(Exception):
    pass


def confine_borrowed_credential(token: str, team_id: int) -> str | None:
    """Return a credential for `token` that only reaches `team_id`, for a caller who is not its owner.

    Returns None when `token` is not a PostHog credential, so a third-party server gets it unchanged.
    Raises BorrowedCredentialRefused when it is a PostHog credential that cannot be confined.
    """
    if token.startswith(OAUTH_ACCESS_TOKEN_PREFIX):
        return _confine_oauth_token(token, team_id)
    if token.startswith(PERSONAL_API_KEY_PREFIX):
        return _confine_personal_api_key(token, team_id, issued_here_required=True)
    if looks_like_legacy_personal_api_key(token):
        # A bare 43-character secret may just as well be a third-party token.
        return _confine_personal_api_key(token, team_id, issued_here_required=False)
    return None


def _confine_oauth_token(token: str, team_id: int) -> str:
    original = find_oauth_access_token(token)
    if original is None:
        # Another PostHog instance issued it, so nothing here can narrow it.
        raise BorrowedCredentialRefused("This connection's PostHog credential can only be used by its owner.")
    if original.user is None or not original.user.is_active or original.application is None or original.is_expired():
        raise BorrowedCredentialRefused("This connection's PostHog credential is no longer valid.")
    _require_team_in_scope(original.scoped_teams, original.scoped_organizations, team_id)
    if list(original.scoped_teams or []) == [team_id]:
        return token

    reusable = (
        OAuthAccessToken.objects.filter(
            application=original.application,
            user=original.user,
            scope=original.scope,
            scoped_teams=[team_id],
            expires__gt=timezone.now() + CONFINED_TOKEN_MIN_REMAINING,
        )
        .order_by("-expires")
        .first()
    )
    if reusable is not None:
        return reusable.token
    return mint_oauth_access_token(
        application=original.application,
        user=original.user,
        scope=original.scope,
        lifetime=min(CONFINED_TOKEN_LIFETIME, original.expires - timezone.now()),
        scoped_teams=[team_id],
    ).token


def _confine_personal_api_key(token: str, team_id: int, *, issued_here_required: bool) -> str | None:
    found = find_personal_api_key(token)
    if found is None:
        if not issued_here_required:
            return None
        raise BorrowedCredentialRefused("This connection's PostHog credential can only be used by its owner.")
    key, _ = found
    if list(key.scoped_teams or []) != [team_id]:
        raise BorrowedCredentialRefused(
            "This connection's personal API key must be limited to this project before teammates or agents can use it."
        )
    return token


def _require_team_in_scope(
    scoped_teams: list[int] | None, scoped_organizations: list[str] | None, team_id: int
) -> None:
    if scoped_teams and team_id not in scoped_teams:
        raise BorrowedCredentialRefused("This connection's PostHog credential has no access to this project.")
    if scoped_organizations:
        organization_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
        if str(organization_id) not in scoped_organizations:
            raise BorrowedCredentialRefused("This connection's PostHog credential has no access to this project.")
