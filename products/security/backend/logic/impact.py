"""What a draft rule would reach, shown before the admin confirms it."""

import re
import ipaddress

from django.db.models import Q

from posthog.dataclasses import frozen
from posthog.models import OrganizationMembership, Team, User

from ..facade.enums import Scope, TargetType
from .guards import RuleDraft
from .targets import DOT_INSENSITIVE_DOMAINS


@frozen
class Impact:
    address_count: int | None = None
    # Set for account targets whose scope reaches existing accounts. A signup rule
    # touches no existing account, so it leaves this unset.
    matched_active_accounts: int | None = None


def preview(draft: RuleDraft) -> Impact:
    if draft.target_type == TargetType.IP:
        return Impact(address_count=ipaddress.ip_network(draft.target_value).num_addresses)
    if draft.scope == Scope.SIGNUP:
        return Impact()
    return Impact(matched_active_accounts=_count_matched_active_accounts(draft))


def _count_matched_active_accounts(draft: RuleDraft) -> int:
    value = draft.target_value
    match draft.target_type:
        case TargetType.ORGANIZATION_ID:
            return OrganizationMembership.objects.filter(organization_id=value, user__is_active=True).count()
        case TargetType.TEAM_ID:
            organization_id = Team.objects.filter(id=int(value)).values_list("organization_id", flat=True).first()
            if organization_id is None:
                return 0
            return OrganizationMembership.objects.filter(organization_id=organization_id, user__is_active=True).count()
        case _:
            return User.objects.filter(_user_filter(draft.target_type, value), is_active=True).count()


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
