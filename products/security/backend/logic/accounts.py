"""What the security hub asks this region about accounts. Every count stops at COUNT_CAP."""

import re
import uuid
from typing import Literal

from django.db.models import Q, QuerySet

from posthog.dataclasses import frozen
from posthog.helpers.email_utils import EmailLookupHandler
from posthog.models import Organization, OrganizationMembership, User

from .decisions import PROTECTED_DOMAIN
from .subjects import DOT_INSENSITIVE_DOMAINS

# An email root or domain count has no index to use, so an uncapped count would scan
# every row of posthog_user while the admin waits.
COUNT_CAP = 500

CountableType = Literal["email", "email_root", "email_domain"]


@frozen
class ResolvedUser:
    uuid: str
    email: str
    is_active: bool


@frozen
class Resolution:
    kind: Literal["user", "organization", "none"]
    user: ResolvedUser | None = None
    organization_ids: tuple[str, ...] = ()


@frozen
class CappedCount:
    count: int
    capped: bool


NOTHING = Resolution(kind="none")


def _parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _user_resolution(user: User) -> Resolution:
    organization_ids = OrganizationMembership.objects.filter(user=user).values_list("organization_id", flat=True)
    return Resolution(
        kind="user",
        user=ResolvedUser(uuid=str(user.uuid), email=user.email, is_active=user.is_active),
        organization_ids=tuple(sorted(str(org_id) for org_id in organization_ids)),
    )


def resolve_subject(query: str) -> Resolution:
    text = query.strip()
    if not text:
        return NOTHING
    if "@" in text:
        user = EmailLookupHandler.get_user_by_email(text, is_active=None)
        return _user_resolution(user) if user else NOTHING
    parsed = _parse_uuid(text)
    if parsed is None:
        return NOTHING
    user = User.objects.filter(uuid=parsed).first()
    if user:
        return _user_resolution(user)
    if Organization.objects.filter(id=parsed).exists():
        return Resolution(kind="organization", organization_ids=(str(parsed),))
    return NOTHING


def _capped(queryset: QuerySet) -> CappedCount:
    # One row over the cap, so a full count and a capped count look different.
    found = queryset.values("pk")[: COUNT_CAP + 1].count()
    return CappedCount(count=min(found, COUNT_CAP), capped=found > COUNT_CAP)


def _email_root_regex(root: str) -> str:
    """Every stored address that folds to this root."""
    local, _, domain = root.rpartition("@")
    suffix = r"(\+[^@]*)?"
    if domain in DOT_INSENSITIVE_DOMAINS:
        dotted_local = r"\.*".join(re.escape(char) for char in local)
        return rf"^{dotted_local}{suffix}@(gmail|googlemail)\.com$"
    return rf"^{re.escape(local)}{suffix}@{re.escape(domain)}$"


def count_active_accounts(target_type: CountableType, value: str) -> CappedCount:
    if target_type == "email":
        # Matches resolve_subject's fold (LOWER via EmailLookupHandler), not `iexact` (UPPER):
        # the two fold Unicode differently, so a count on one fold could disagree with who resolves.
        return _capped(EmailLookupHandler.users_matching_email(value, User.objects.filter(is_active=True)))
    match target_type:
        case "email_root":
            condition = Q(email__iregex=_email_root_regex(value))
        case "email_domain":
            condition = Q(email__iendswith=f"@{value}") | Q(email__iendswith=f".{value}")
    return _capped(User.objects.filter(condition, is_active=True))


def count_active_org_members(organization_id: str) -> tuple[bool, CappedCount]:
    parsed = _parse_uuid(organization_id)
    if parsed is None or not Organization.objects.filter(id=parsed).exists():
        return False, CappedCount(count=0, capped=False)
    members = OrganizationMembership.objects.filter(organization_id=parsed, user__is_active=True)
    return True, _capped(members)


def _is_protected_email(email: str | None) -> bool:
    domain = (email or "").lower().rpartition("@")[2]
    return domain == PROTECTED_DOMAIN or domain.endswith(f".{PROTECTED_DOMAIN}")


def email_for_user(user_uuid: str) -> str | None:
    parsed = _parse_uuid(user_uuid)
    if parsed is None:
        return None
    return User.objects.filter(uuid=parsed).values_list("email", flat=True).first()


def has_posthog_account(*, user_uuid: str | None = None, organization_id: str | None = None) -> bool:
    if user_uuid is not None:
        return _is_protected_email(email_for_user(user_uuid))
    parsed = _parse_uuid(organization_id or "")
    if parsed is None:
        return False
    protected = Q(user__email__iendswith=f"@{PROTECTED_DOMAIN}") | Q(user__email__iendswith=f".{PROTECTED_DOMAIN}")
    return OrganizationMembership.objects.filter(protected, organization_id=parsed).exists()
