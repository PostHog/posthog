"""The guards every enrichment entry point applies before it reaches the provider."""

import datetime as dt
from email.utils import parseaddr
from typing import Literal

from posthog.dataclasses import frozen
from posthog.models.instance_setting import get_instance_setting
from posthog.models.organization import Organization, OrganizationMembership
from posthog.utils import GenericEmails, get_instance_region

KILL_SWITCH_SETTING = "GROWTH_SIGNUP_ENRICHMENT_ENABLED"
CLOUD_REGIONS = ("US", "EU")

# The signup creator's membership is written in the signup transaction, so an earliest
# membership older than this means that user left and nobody can stand in for them.
SIGNUP_MEMBERSHIP_WINDOW = dt.timedelta(minutes=5)

_generic_emails = GenericEmails()

# These domains identify no company. They stay out of GenericEmails because the internal-users
# cohort also uses that list, and a test team needs its own test domain in that cohort.
_NON_COMPANY_DOMAINS = frozenset({"example.com", "example.net", "example.org", "test.com"})


def enrichment_enabled() -> bool:
    return bool(get_instance_setting(KILL_SWITCH_SETTING))


def region_allowed() -> bool:
    return get_instance_region() in CLOUD_REGIONS


def organization_exists(organization_id: str) -> bool:
    return Organization.objects.filter(id=organization_id).exists()


def domain_from_email(email: str) -> str | None:
    _, address = parseaddr(email or "")
    if "@" not in address:
        return None
    domain = address.rsplit("@", 1)[1].strip().lower()
    return domain or None


def is_company_email(email: str) -> bool:
    domain = domain_from_email(email)
    return domain is not None and domain not in _NON_COMPANY_DOMAINS and not _generic_emails.is_generic(email)


SignupIdentitySkipReason = Literal["signup_user_left", "no_usable_member", "not_company_email"]


@frozen
class SignupIdentity:
    distinct_id: str
    domain: str


@frozen
class SignupIdentitySkip:
    reason: SignupIdentitySkipReason


def resolve_signup_identity(organization_id: str) -> SignupIdentity | SignupIdentitySkip:
    membership = (
        OrganizationMembership.objects.filter(organization_id=organization_id)
        .select_related("user", "organization")
        .order_by("joined_at")
        .first()
    )
    if membership is None:
        return SignupIdentitySkip(reason="no_usable_member")
    if membership.joined_at - membership.organization.created_at > SIGNUP_MEMBERSHIP_WINDOW:
        return SignupIdentitySkip(reason="signup_user_left")
    user = membership.user
    domain = domain_from_email(user.email) if user and user.email else None
    if user is None or not user.distinct_id or not domain:
        return SignupIdentitySkip(reason="no_usable_member")
    # The signup user's email can have changed since signup, so re-check it's a work email.
    if not is_company_email(user.email):
        return SignupIdentitySkip(reason="not_company_email")
    return SignupIdentity(distinct_id=user.distinct_id, domain=domain)
