"""Finds the emails of a project's own team, so the internal users check can match them in events."""

import re
from collections import Counter
from functools import cache

from posthog.dataclasses import frozen
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.team import Team
from posthog.models.user import User
from posthog.utils import GenericEmails

from products.access_control.backend.facade.subject_access_control import restricted_visible_membership_ids
from products.product_analytics.backend.facade.contracts import TeamEmailAccess

# A real person's email can contain one of these words, so only a word that stands alone marks a test account.
TEST_ACCOUNT_WORDS = "test|testing|qa|demo|dummy|fake"
# A member on a company domain is found by the domain, so these limits only bound the size of the pattern.
MAX_TEAM_DOMAINS = 20
MAX_TEAM_ADDRESSES = 200


@frozen
class TeamEmails:
    # Company domains, the one with the most members first.
    domains: tuple[str, ...]
    # Members on a public email provider, where the domain says nothing about the team.
    addresses: tuple[str, ...]


@cache
def _generic_emails() -> GenericEmails:
    return GenericEmails()


def _visible_member_emails(team: Team, user: User) -> list[str]:
    memberships = OrganizationMembership.objects.filter(organization_id=team.organization_id)
    # A match on a member `user` may not see would tell them that the address belongs to a member.
    visible_membership_ids = restricted_visible_membership_ids(team.organization, user)
    if visible_membership_ids is not None:
        memberships = memberships.filter(id__in=visible_membership_ids)
    return list(memberships.values_list("user__email", flat=True))


def _verified_domains(team: Team) -> list[str]:
    verified_domains = OrganizationDomain.objects.verified_domains().filter(organization_id=team.organization_id)
    return list(verified_domains.values_list("domain", flat=True))


def team_emails_of(team: Team, user: User, access: TeamEmailAccess) -> TeamEmails:
    """The emails of the organization's members that `user` may see, and the organization's verified domains."""
    domains: Counter[str] = Counter()
    addresses: set[str] = set()
    for member_email in _visible_member_emails(team, user) if access.member_emails else []:
        email = member_email.strip().lower()
        if "@" not in email:
            continue
        if _generic_emails().is_generic(email):
            addresses.add(email)
        else:
            domains[email.rpartition("@")[2]] += 1
    for domain in _verified_domains(team) if access.verified_domains else []:
        domains.setdefault(domain.strip().lower(), 0)

    most_members_first = sorted(
        domains.items(), key=lambda domain_and_members: (-domain_and_members[1], domain_and_members[0])
    )
    return TeamEmails(
        domains=tuple(domain for domain, _ in most_members_first[:MAX_TEAM_DOMAINS]),
        addresses=tuple(sorted(addresses)[:MAX_TEAM_ADDRESSES]),
    )


def team_email_pattern(emails: TeamEmails) -> str:
    """A pattern for a lowercase email that belongs to the team or to a test account."""
    alternatives = [
        rf"^(?:{TEST_ACCOUNT_WORDS})(?:[._+0-9-][^@]*)?@",
        rf"\+(?:{TEST_ACCOUNT_WORDS})(?:[._0-9-][^@]*)?@",
    ]
    if emails.domains:
        # A subdomain of a company domain is the same company. The end anchor keeps acme.com.br out.
        alternatives.append(rf"@(?:[a-z0-9-]+\.)*(?:{'|'.join(map(re.escape, emails.domains))})$")
    if emails.addresses:
        alternatives.append(rf"^(?:{'|'.join(map(re.escape, emails.addresses))})$")
    return "|".join(f"(?:{alternative})" for alternative in alternatives)
