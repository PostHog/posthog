"""What a draft rule would reach, shown before the admin confirms it."""

import re
import ipaddress
from enum import StrEnum

from django.db.models import Q, QuerySet

from posthog.dataclasses import frozen
from posthog.models import OrganizationMembership, Team, User

from ..facade.enums import Scope, TargetType
from .guards import RuleDraft
from .targets import DOT_INSENSITIVE_DOMAINS

# The count stops here. An email root or domain count has no index to read, so an
# uncapped count scans every row of posthog_user while the admin waits.
COUNT_CAP = 500


class CountBasis(StrEnum):
    """What the count in an Impact counts, so the admin reads the right number."""

    ACCOUNTS = "accounts"
    ORGANIZATION = "organization"
    PROJECT_ORGANIZATION = "project_organization"


@frozen
class Impact:
    address_count: int | None = None
    # Set for account targets whose scope reaches existing accounts. A signup rule
    # touches no existing account, so it leaves this unset.
    matched_active_accounts: int | None = None
    # True when the real number is higher than the count, which stopped at COUNT_CAP.
    count_capped: bool = False
    count_basis: CountBasis = CountBasis.ACCOUNTS


def preview(draft: RuleDraft) -> Impact:
    if draft.target_type == TargetType.IP:
        return Impact(address_count=ipaddress.ip_network(draft.target_value).num_addresses)
    if draft.scope == Scope.SIGNUP:
        return Impact()
    matched, basis = _count_matched_active_accounts(draft)
    return Impact(
        matched_active_accounts=min(matched, COUNT_CAP),
        count_capped=matched > COUNT_CAP,
        count_basis=basis,
    )


def _count_matched_active_accounts(draft: RuleDraft) -> tuple[int, CountBasis]:
    value = draft.target_value
    match draft.target_type:
        case TargetType.ORGANIZATION_ID:
            members = OrganizationMembership.objects.filter(organization_id=value, user__is_active=True)
            return _capped_count(members), CountBasis.ORGANIZATION
        case TargetType.TEAM_ID:
            organization_id = Team.objects.filter(id=int(value)).values_list("organization_id", flat=True).first()
            if organization_id is None:
                return 0, CountBasis.PROJECT_ORGANIZATION
            members = OrganizationMembership.objects.filter(organization_id=organization_id, user__is_active=True)
            return _capped_count(members), CountBasis.PROJECT_ORGANIZATION
        case _:
            users = User.objects.filter(_user_filter(draft.target_type, value), is_active=True)
            return _capped_count(users), CountBasis.ACCOUNTS


def _capped_count(queryset: QuerySet) -> int:
    # One row over the cap, so the caller can tell a full count from a capped one.
    return queryset.values("pk")[: COUNT_CAP + 1].count()


def _user_filter(target_type: TargetType, value: str) -> Q:
    match target_type:
        case TargetType.USER_UUID:
            return Q(uuid=value)
        case TargetType.EMAIL:
            return Q(email__iexact=value)
        case TargetType.EMAIL_DOMAIN:
            return Q(email__iendswith=f"@{value}") | Q(email__iendswith=f".{value}")
        case TargetType.EMAIL_ROOT:
            return Q(email__iregex=_email_root_regex(value))
    raise ValueError(f"{target_type} names no user")


def _email_root_regex(root: str) -> str:
    """Every stored address that folds to this root, matched in the database."""
    local, _, domain = root.rpartition("@")
    suffix = r"(\+[^@]*)?"
    if domain in DOT_INSENSITIVE_DOMAINS:
        dotted_local = r"\.*".join(re.escape(char) for char in local)
        return rf"^{dotted_local}{suffix}@(gmail|googlemail)\.com$"
    return rf"^{re.escape(local)}{suffix}@{re.escape(domain)}$"
