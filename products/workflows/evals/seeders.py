"""Seeders for the email domain setup eval cases.

Each case sends from its own subdomain of a reserved example domain, so the records one
case publishes never answer for another. The addresses are module constants because the
prompt, the seeder and the scorers all have to mean the same sender.

PostHog refuses a sending domain that another organization already uses, and every case
runs in a new organization in a database that outlives the run. So each address carries
a label that is new for every run, and a domain from an earlier run never blocks this one.

Seeders that change a policy verify it took effect before returning. A policy that did
not apply would turn its case into a hollow pass, while raising marks the case an infra
error, which the harness keeps out of score averages.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User
from posthog.user_permissions import UserPermissions

from products.tasks.backend.facade.agents import CustomPromptSandboxContext
from products.workflows.evals.simulated_email_domains import (
    SIMULATED_EMAIL_DOMAINS,
    DnsRecord,
    publish_domain_connect_support,
    ses_records,
)

__all__ = [
    "CLAIMED_DOMAIN_SENDER",
    "DOMAIN_CONNECT_SENDER",
    "EXISTING_DMARC_SENDER",
    "EXISTING_DMARC_VALUE",
    "EXISTING_SPF_INCLUDE",
    "EXISTING_SPF_SENDER",
    "FREE_MAILBOX_SENDER",
    "MAIL_FROM_TAKEN_SENDER",
    "MANUAL_SENDER",
    "MEMBER_SENDER",
    "SECOND_SENDER",
    "SHARED_DOMAIN_MAIL_FROM_SUBDOMAIN",
    "SHARED_DOMAIN_SENDER",
    "VERIFIED_SENDER",
    "domain_of",
    "seed_claimed_domain",
    "seed_domain_connect_support",
    "seed_existing_dmarc",
    "seed_existing_spf",
    "seed_helpdesk_mx",
    "seed_member_without_admin",
    "seed_new_sender",
    "seed_shared_domain_sender",
    "seed_verified_sender",
]

RUN_LABEL = uuid.uuid4().hex[:8]

DOMAIN_CONNECT_SENDER = f"hello@mail.connect-{RUN_LABEL}.example.net"
MANUAL_SENDER = f"hello@mail.manual-{RUN_LABEL}.example.com"
VERIFIED_SENDER = f"hello@mail.ready-{RUN_LABEL}.example.com"
SHARED_DOMAIN_SENDER = f"ops@mail.shared-{RUN_LABEL}.example.com"
SHARED_DOMAIN_MAIL_FROM_SUBDOMAIN = "bounce"
SECOND_SENDER = f"newsletter@mail.shared-{RUN_LABEL}.example.com"
FREE_MAILBOX_SENDER = "hedgebox.team@gmail.com"
CLAIMED_DOMAIN_SENDER = f"hello@mail.claimed-{RUN_LABEL}.example.org"
EXISTING_DMARC_SENDER = f"hello@mail.dmarc-{RUN_LABEL}.example.org"
EXISTING_DMARC_VALUE = "v=DMARC1; p=quarantine; rua=mailto:dmarc@example.org"
EXISTING_SPF_SENDER = f"hello@mail.spf-{RUN_LABEL}.example.org"
EXISTING_SPF_INCLUDE = "include:_spf.google.com"
HELPDESK_MX_HOST = "mx.helpdesk.example.com"
MEMBER_SENDER = f"hello@mail.member-{RUN_LABEL}.example.com"
MAIL_FROM_TAKEN_SENDER = f"hello@mail.helpdesk-{RUN_LABEL}.example.com"


def domain_of(address: str) -> str:
    return address.split("@", 1)[1]


def _seeded(context: CustomPromptSandboxContext, sender: str, **extra: Any) -> dict[str, Any]:
    return {"team_id": context.team_id, "sender": sender, **extra}


def seed_new_sender(sender: str) -> Callable[[CustomPromptSandboxContext], dict[str, Any]]:
    """A seeder for a case that starts from an empty project and needs only its team recorded."""

    def seed(context: CustomPromptSandboxContext) -> dict[str, Any]:
        return _seeded(context, sender)

    return seed


def _create_sender(context: CustomPromptSandboxContext, address: str, *, mail_from_subdomain: str) -> Integration:
    domain = domain_of(address)
    return Integration.objects.create(
        team_id=context.team_id,
        kind="email",
        integration_id=address,
        created_by_id=context.user_id,
        config={
            "email": address,
            "domain": domain,
            "mail_from_subdomain": mail_from_subdomain,
            "name": "Hedgebox",
            "provider": "ses",
            "verified": True,
        },
    )


def _publish_verified_domain(context: CustomPromptSandboxContext, domain: str, mail_from_subdomain: str) -> None:
    SIMULATED_EMAIL_DOMAINS.publish(ses_records(domain, mail_from_subdomain))
    SIMULATED_EMAIL_DOMAINS.associate(context.team_id, domain)


def seed_domain_connect_support(context: CustomPromptSandboxContext) -> dict[str, Any]:
    publish_domain_connect_support()
    return _seeded(context, DOMAIN_CONNECT_SENDER)


def seed_verified_sender(context: CustomPromptSandboxContext) -> dict[str, Any]:
    sender = _create_sender(context, VERIFIED_SENDER, mail_from_subdomain="feedback")
    _publish_verified_domain(context, domain_of(VERIFIED_SENDER), "feedback")
    return _seeded(context, VERIFIED_SENDER, integration_id=sender.id)


def seed_shared_domain_sender(context: CustomPromptSandboxContext) -> dict[str, Any]:
    sender = _create_sender(context, SHARED_DOMAIN_SENDER, mail_from_subdomain=SHARED_DOMAIN_MAIL_FROM_SUBDOMAIN)
    _publish_verified_domain(context, domain_of(SHARED_DOMAIN_SENDER), SHARED_DOMAIN_MAIL_FROM_SUBDOMAIN)
    return _seeded(context, SHARED_DOMAIN_SENDER, integration_id=sender.id)


def seed_claimed_domain(context: CustomPromptSandboxContext) -> dict[str, Any]:
    SIMULATED_EMAIL_DOMAINS.claim_for_other_organization(domain_of(CLAIMED_DOMAIN_SENDER))
    return _seeded(context, CLAIMED_DOMAIN_SENDER)


def seed_existing_dmarc(context: CustomPromptSandboxContext) -> dict[str, Any]:
    domain = domain_of(EXISTING_DMARC_SENDER)
    SIMULATED_EMAIL_DOMAINS.publish([DnsRecord(name=f"_dmarc.{domain}", record_type="TXT", value=EXISTING_DMARC_VALUE)])
    return _seeded(context, EXISTING_DMARC_SENDER)


def seed_existing_spf(context: CustomPromptSandboxContext) -> dict[str, Any]:
    domain = domain_of(EXISTING_SPF_SENDER)
    SIMULATED_EMAIL_DOMAINS.publish(
        [DnsRecord(name=domain, record_type="TXT", value=f"v=spf1 {EXISTING_SPF_INCLUDE} ~all")]
    )
    return _seeded(context, EXISTING_SPF_SENDER)


def seed_helpdesk_mx(context: CustomPromptSandboxContext) -> dict[str, Any]:
    domain = domain_of(MAIL_FROM_TAKEN_SENDER)
    SIMULATED_EMAIL_DOMAINS.publish([DnsRecord(name=f"feedback.{domain}", record_type="MX", value=HELPDESK_MX_HOST)])
    return _seeded(context, MAIL_FROM_TAKEN_SENDER)


def seed_member_without_admin(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team = Team.objects.get(id=context.team_id)
    OrganizationMembership.objects.filter(user_id=context.user_id, organization_id=team.organization_id).update(
        level=OrganizationMembership.Level.MEMBER
    )
    user = User.objects.get(id=context.user_id)
    if UserPermissions(user).team(team).effective_membership_level != OrganizationMembership.Level.MEMBER:
        raise RuntimeError("The case user still has admin access to the project, so this case would test nothing")
    return _seeded(context, MEMBER_SENDER)
