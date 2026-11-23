"""The credential that admitted a run, and what it may still do when the worker mints a token for it.

The scopes stored at admission are a ceiling. Before every mint the worker reads the credential again and
narrows to what it grants now: a key or token that lost a scope, a team or an organization, expired, or was
revoked stops the run, and the minted token never outlives the credential.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from posthog.models.oauth import OAuthAccessToken
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.workload_trust_policy import WorkloadTrustPolicy, workload_trust_policy_version
from posthog.scopes.checks import scopes_not_covered
from posthog.user_permissions import UserPermissions

from ..facade.contracts import CallerGrant
from .credentials import CallerUnavailable

# The credential types the worker knows how to re-check. Anything else is refused at admission.
DELEGABLE_GRANTS = frozenset({"session", "personal_api_key", "oauth", "workload"})


@dataclass(frozen=True)
class Authority:
    """What the admitting credential grants now. `scopes` None means the user's full authority, as for a session."""

    user: User
    scopes: frozenset[str] | None
    expires_at: datetime | None

    def narrow(self, admitted: list[str]) -> list[str]:
        """The admitted scopes, refused if the credential no longer covers every one of them."""
        if self.scopes is not None and "*" not in self.scopes:
            if missing := scopes_not_covered(self.scopes, admitted):
                raise CallerUnavailable(
                    f"The key or token that asked for this run no longer has the {', '.join(sorted(missing))} "
                    "scopes. Run it again with a key that has them."
                )
        return admitted


def grant_dict(grant: CallerGrant) -> dict[str, str]:
    stored = {"type": grant.type, "id": grant.id}
    if grant.version:
        stored["version"] = grant.version
    if grant.expires_at:
        stored["expires_at"] = grant.expires_at
    return stored


def _revoked() -> CallerUnavailable:
    return CallerUnavailable("The key or token that asked for this run was revoked. Run it again with a valid one.")


def _expired() -> CallerUnavailable:
    return CallerUnavailable("The key or token that asked for this run expired. Run it again with a valid one.")


def _check_reach(scoped_teams: list[int] | None, scoped_organizations: list[str] | None, team: Team) -> None:
    if scoped_teams and team.id not in scoped_teams:
        raise CallerUnavailable("The key or token that asked for this run can no longer reach this project.")
    if scoped_organizations and str(team.organization_id) not in scoped_organizations:
        raise CallerUnavailable("The key or token that asked for this run can no longer reach this organization.")


def _not_expired(expires_at: datetime | None, now: datetime) -> datetime | None:
    if expires_at is not None and expires_at <= now:
        raise _expired()
    return expires_at


def _authority(grant: dict, user: User, team: Team) -> Authority:
    grant_type, grant_id = grant.get("type"), str(grant.get("id", ""))
    now = timezone.now()
    if grant_type == "session":
        return Authority(user=user, scopes=None, expires_at=None)
    if grant_type == "personal_api_key":
        key = PersonalAPIKey.objects.filter(id=grant_id, user=user).first()
        if key is None:
            raise _revoked()
        _check_reach(key.scoped_teams, key.scoped_organizations, team)
        return Authority(user=user, scopes=frozenset(key.scopes or []), expires_at=_not_expired(key.expires_at, now))
    if grant_type == "oauth":
        token = OAuthAccessToken.objects.filter(id=grant_id, user=user).first()
        if token is None:
            raise _revoked()
        _check_reach(token.scoped_teams, token.scoped_organizations, team)
        return Authority(
            user=user, scopes=frozenset((token.scope or "").split()), expires_at=_not_expired(token.expires, now)
        )
    if grant_type == "workload":
        policy = WorkloadTrustPolicy.objects.for_team(team.id, canonical=True).filter(pk=grant_id, enabled=True).first()
        if policy is None or workload_trust_policy_version(policy) != grant.get("version"):
            raise CallerUnavailable(
                "The workload trust policy that asked for this run was changed, disabled or deleted. Run it again."
            )
        owner = OrganizationMembership.objects.filter(
            organization_id=team.organization_id, user=user, level=OrganizationMembership.Level.OWNER
        ).exists()
        if not owner:
            raise CallerUnavailable("The organization owner this workload acts as is no longer an owner.")
        expires_at = parse_datetime(str(grant.get("expires_at") or ""))
        if expires_at is None:
            raise _expired()
        return Authority(user=user, scopes=frozenset(policy.scopes), expires_at=_not_expired(expires_at, now))
    raise CallerUnavailable("This run was asked for with a credential stacks cannot act for. Run it again.")


def check_grant(*, user_id: int | None, target_team_id: int, grant: dict) -> Authority:
    """What the run may do now, once it is clear the person and the credential that asked may still run it."""
    user = User.objects.filter(id=user_id, is_active=True).first() if user_id is not None else None
    team = Team.objects.filter(id=target_team_id).first()
    if user is None or team is None or UserPermissions(user).team(team).effective_membership_level is None:
        raise CallerUnavailable("The person who asked for this run no longer has access to this project.")
    return _authority(grant, user, team)
