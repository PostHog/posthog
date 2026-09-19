"""Accounts that no rule may reach. A rule that blocked PostHog staff could lock the
company out of its own product, so these are refused on save and ignored on decide."""

from django.db.models import Q

from posthog.models import OrganizationMembership, Team, User

from ..facade.enums import TargetType
from .guards import RuleDraft

PROTECTED_DOMAIN = "posthog.com"

_REFUSAL = f"Rules can't reach {PROTECTED_DOMAIN} accounts."


def is_protected_domain(domain: str | None) -> bool:
    return domain is not None and (domain == PROTECTED_DOMAIN or domain.endswith(f".{PROTECTED_DOMAIN}"))


def email_for_user(user_uuid: str | None) -> str | None:
    """The address to judge protection by when a caller names a user but not their email."""
    if user_uuid is None:
        return None
    return User.objects.filter(uuid=user_uuid).values_list("email", flat=True).first()


def check_protected(draft: RuleDraft) -> list[str]:
    value = draft.target_value
    match draft.target_type:
        case TargetType.EMAIL | TargetType.EMAIL_ROOT:
            if is_protected_domain(value.rpartition("@")[2]):
                return [_REFUSAL]
        case TargetType.EMAIL_DOMAIN:
            if is_protected_domain(value):
                return [_REFUSAL]
        case TargetType.USER_UUID:
            email = User.objects.filter(uuid=value).values_list("email", flat=True).first()
            if email and is_protected_domain(email.lower().rpartition("@")[2]):
                return [f"This user has a {PROTECTED_DOMAIN} address. {_REFUSAL}"]
        case TargetType.ORGANIZATION_ID:
            if _has_protected_member(value):
                return [f"This organization has {PROTECTED_DOMAIN} members. {_REFUSAL}"]
        case TargetType.TEAM_ID:
            organization_id = Team.objects.filter(id=int(value)).values_list("organization_id", flat=True).first()
            if organization_id is not None and _has_protected_member(str(organization_id)):
                return [f"This project's organization has {PROTECTED_DOMAIN} members. {_REFUSAL}"]
    return []


def _has_protected_member(organization_id: str) -> bool:
    protected = Q(user__email__iendswith=f"@{PROTECTED_DOMAIN}") | Q(user__email__iendswith=f".{PROTECTED_DOMAIN}")
    return OrganizationMembership.objects.filter(protected, organization_id=organization_id).exists()
