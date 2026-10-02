"""Can an agent set up a Workflows email sending domain with the setting-up-an-email-domain skill?

The agent drives the real email integration API through MCP. SES, DNS and Domain Connect
are simulated (see ``simulated_email_domains.py``), so each case controls which records
are already published and every status follows from that.

The cases cover the three ways records get published, then the rules that keep an
existing setup intact and the errors an agent has to relay instead of working around:

* ``domain_connect_link`` and ``manual_records`` are the two hand-offs on a new domain.
* ``already_verified_sender`` and ``second_sender_on_shared_domain`` must reuse what exists.
* ``existing_dmarc_kept``, ``existing_spf_merged`` and ``mail_from_label_taken`` must not
  break records the domain already uses.
* ``free_mailbox_domain``, ``domain_claimed_by_another_org`` and ``member_cannot_verify``
  must end with the person knowing what to do next.

To run:
    flox activate -- bash -c "hogli evals eval_email_domain_setup"
"""

from __future__ import annotations

from django.conf import settings

from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.workflows.evals.scorers import (
    AvoidedTool,
    BoundedVerifyPolling,
    FinalMessageJudge,
    FinalMessageMentions,
    FinalMessageOmits,
    MergedSpfRecord,
    SendersInProject,
    SharedApplyUrl,
)
from products.workflows.evals.seeders import (
    CLAIMED_DOMAIN_SENDER,
    DOMAIN_CONNECT_SENDER,
    EXISTING_DMARC_SENDER,
    EXISTING_SPF_INCLUDE,
    EXISTING_SPF_SENDER,
    FREE_MAILBOX_SENDER,
    MAIL_FROM_TAKEN_SENDER,
    MANUAL_SENDER,
    MEMBER_SENDER,
    SECOND_SENDER,
    SHARED_DOMAIN_MAIL_FROM_SUBDOMAIN,
    SHARED_DOMAIN_SENDER,
    VERIFIED_SENDER,
    domain_of,
    seed_claimed_domain,
    seed_domain_connect_support,
    seed_existing_dmarc,
    seed_member_without_admin,
    seed_new_sender,
    seed_shared_domain_sender,
    seed_verified_sender,
)
from products.workflows.evals.simulated_email_domains import dkim_tokens, simulated_email_domains, verification_token

GENERIC_CREATE_TOOL = "integrations-create"
EMAIL_CREATE_TOOL = "integrations-email-create"
NO_GENERIC_CREATE = {"tools": [GENERIC_CREATE_TOOL]}

WAITS_FOR_DOMAIN_CONNECT_APPROVAL = (
    "A user asked an assistant to set up a sending domain for email. The assistant can only prepare a "
    "link, and the user has to open it and approve the DNS changes at their DNS provider. Does the "
    "message below give the user that link, and make clear the sender cannot send until they approve "
    "it and the records verify? A message that says the domain is already verified or ready to send "
    "is a no."
)
WAITS_FOR_MANUAL_RECORDS = (
    "A user asked an assistant to set up a sending domain for email, and the user has to add DNS "
    "records at their DNS host. Does the message below ask the user to add the records, and make clear "
    "the sender cannot send until they are published and verified? A message that says the domain is "
    "already verified or ready to send is a no."
)
READY_WITHOUT_DNS_WORK = (
    "A user asked an assistant to set up an email sender on a domain whose DNS records are already in "
    "place and verified. Does the message below tell the user the sender is verified and ready to send, "
    "without asking them to add or change any DNS records?"
)
FREE_MAILBOX_EXPLAINED = (
    "A user asked an assistant to set up email sending from an address at a free mailbox provider such "
    "as Gmail, which the product does not allow. Does the message below say the address cannot be used "
    "because it is on a free mailbox provider, and suggest an address on a domain the user owns? A "
    "message that says the sender was set up is a no."
)
CLAIMED_DOMAIN_EXPLAINED = (
    "A user asked an assistant to set up email sending from a domain that another organization already "
    "uses, so the request was refused. Does the message below tell the user the domain is already in "
    "use elsewhere, and point them to support or to a different domain? A message that says the sender "
    "was set up is a no, and so is one that only reports an unexplained error."
)
ADMIN_NEEDED_EXPLAINED = (
    "A user asked an assistant to set up an email sending domain, but the user is a project member "
    "and a step needs project admin access, so the request was refused. Does the message below tell "
    "the user that a project admin has to do that step or grant access, rather than describing a "
    "broken tool or an unexplained failure? A message that says the domain is verified is a no."
)


def _manual_record_values(domain: str) -> list[str]:
    return [
        verification_token(domain),
        *dkim_tokens(domain),
        f"feedback-smtp.{settings.SES_REGION}.amazonses.com",
        "include:amazonses.com",
    ]


def _cases() -> list[SandboxedEvalCase]:
    return [
        SandboxedEvalCase(
            name="domain_connect_link",
            prompt=f"Set up {DOMAIN_CONNECT_SENDER} as our Workflows email sender, with Hedgebox as the display name.",
            setup=seed_domain_connect_support,
            expected={
                "senders_in_project": {"senders": {DOMAIN_CONNECT_SENDER: {}}},
                "shared_apply_url": {},
                "avoided_tool": NO_GENERIC_CREATE,
                "bounded_verify_polling": {"max_calls": 3},
                "waits_for_domain_connect_approval": {},
            },
        ),
        SandboxedEvalCase(
            name="manual_records",
            prompt=(
                f"We want to send Workflows emails from {MANUAL_SENDER} (display name Hedgebox). "
                "I'll add the DNS records myself, just tell me what to add."
            ),
            setup=seed_new_sender(MANUAL_SENDER),
            expected={
                "senders_in_project": {"senders": {MANUAL_SENDER: {}}},
                "final_message_mentions": {"values": _manual_record_values(domain_of(MANUAL_SENDER))},
                "avoided_tool": NO_GENERIC_CREATE,
                "bounded_verify_polling": {"max_calls": 3},
                "waits_for_manual_records": {},
            },
        ),
        SandboxedEvalCase(
            name="already_verified_sender",
            prompt=f"Can you set up {VERIFIED_SENDER} so our workflows can send email from it?",
            setup=seed_verified_sender,
            expected={
                "senders_in_project": {"senders": {VERIFIED_SENDER: {}}},
                "avoided_tool": {"tools": [GENERIC_CREATE_TOOL, EMAIL_CREATE_TOOL]},
                "bounded_verify_polling": {"max_calls": 3},
                "ready_without_dns_work": {},
            },
        ),
        SandboxedEvalCase(
            name="second_sender_on_shared_domain",
            prompt=f"Add {SECOND_SENDER} as another Workflows email sender, display name Hedgebox News.",
            setup=seed_shared_domain_sender,
            expected={
                "senders_in_project": {
                    "senders": {
                        SHARED_DOMAIN_SENDER: {"mail_from_subdomain": SHARED_DOMAIN_MAIL_FROM_SUBDOMAIN},
                        SECOND_SENDER: {"mail_from_subdomain": SHARED_DOMAIN_MAIL_FROM_SUBDOMAIN},
                    }
                },
                "avoided_tool": NO_GENERIC_CREATE,
                "bounded_verify_polling": {"max_calls": 3},
                "ready_without_dns_work": {},
            },
        ),
        SandboxedEvalCase(
            name="existing_dmarc_kept",
            prompt=(
                f"Set up {EXISTING_DMARC_SENDER} for Workflows email, display name Hedgebox. "
                "I manage our DNS by hand, so list the records I need to add."
            ),
            setup=seed_existing_dmarc,
            expected={
                "senders_in_project": {"senders": {EXISTING_DMARC_SENDER: {}}},
                "final_message_omits": {"values": ["p=none"]},
                "avoided_tool": NO_GENERIC_CREATE,
                "bounded_verify_polling": {"max_calls": 3},
            },
        ),
        SandboxedEvalCase(
            name="existing_spf_merged",
            prompt=(
                f"Set up {EXISTING_SPF_SENDER} for Workflows email, display name Hedgebox. "
                f"That domain already has an SPF record, `v=spf1 {EXISTING_SPF_INCLUDE} ~all`, for our "
                "Google Workspace mail. I'll update DNS myself, so give me the exact records."
            ),
            setup=seed_new_sender(EXISTING_SPF_SENDER),
            expected={
                "senders_in_project": {"senders": {EXISTING_SPF_SENDER: {}}},
                "merged_spf_record": {"includes": [EXISTING_SPF_INCLUDE, "include:amazonses.com"]},
                "avoided_tool": NO_GENERIC_CREATE,
                "bounded_verify_polling": {"max_calls": 3},
            },
        ),
        SandboxedEvalCase(
            name="mail_from_label_taken",
            prompt=(
                f"Set up {MAIL_FROM_TAKEN_SENDER} as a Workflows sender, display name Hedgebox. Heads up: "
                f"feedback.{domain_of(MAIL_FROM_TAKEN_SENDER)} already has an MX record for our helpdesk "
                "tool, and that has to keep working."
            ),
            setup=seed_new_sender(MAIL_FROM_TAKEN_SENDER),
            expected={
                "senders_in_project": {"senders": {MAIL_FROM_TAKEN_SENDER: {"mail_from_subdomain_not": "feedback"}}},
                "avoided_tool": NO_GENERIC_CREATE,
                "bounded_verify_polling": {"max_calls": 3},
            },
        ),
        SandboxedEvalCase(
            name="free_mailbox_domain",
            prompt=f"Set up {FREE_MAILBOX_SENDER} as the sender for our Workflows emails.",
            setup=seed_new_sender(FREE_MAILBOX_SENDER),
            expected={
                "senders_in_project": {"senders": {}},
                "avoided_tool": NO_GENERIC_CREATE,
                "free_mailbox_explained": {},
            },
        ),
        SandboxedEvalCase(
            name="domain_claimed_by_another_org",
            prompt=f"Set up {CLAIMED_DOMAIN_SENDER} as our Workflows email sender, display name Hedgebox.",
            setup=seed_claimed_domain,
            expected={
                "senders_in_project": {"senders": {}},
                "avoided_tool": NO_GENERIC_CREATE,
                "claimed_domain_explained": {},
            },
        ),
        SandboxedEvalCase(
            name="member_cannot_verify",
            prompt=f"Set up {MEMBER_SENDER} as our Workflows email sender, display name Hedgebox.",
            setup=seed_member_without_admin,
            expected={
                "avoided_tool": NO_GENERIC_CREATE,
                "bounded_verify_polling": {"max_calls": 2},
                "admin_needed_explained": {},
            },
        ),
    ]


async def eval_email_domain_setup(ctx: EvalContext) -> None:
    with simulated_email_domains():
        await SandboxedPrivateEval(
            experiment_name="sandboxed-email-domain-setup-cli",
            cases=_cases(),
            scorers=[
                SendersInProject(),
                AvoidedTool(),
                FinalMessageMentions(),
                FinalMessageOmits(),
                MergedSpfRecord(),
                SharedApplyUrl(),
                BoundedVerifyPolling(),
                FinalMessageJudge(name="waits_for_domain_connect_approval", question=WAITS_FOR_DOMAIN_CONNECT_APPROVAL),
                FinalMessageJudge(name="waits_for_manual_records", question=WAITS_FOR_MANUAL_RECORDS),
                FinalMessageJudge(name="ready_without_dns_work", question=READY_WITHOUT_DNS_WORK),
                FinalMessageJudge(name="free_mailbox_explained", question=FREE_MAILBOX_EXPLAINED),
                FinalMessageJudge(name="claimed_domain_explained", question=CLAIMED_DOMAIN_EXPLAINED),
                FinalMessageJudge(name="admin_needed_explained", question=ADMIN_NEEDED_EXPLAINED),
            ],
            ctx=ctx,
        )
