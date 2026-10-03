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

Each case runs once per run. PostHog refuses a sending domain that another organization
uses, and every trial runs in its own organization, so a second trial of a case could
not create its sender.

To run:
    flox activate -- bash -c "hogli evals eval_email_domain_setup"
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.workflows.evals.scorers import (
    AvoidedTool,
    BoundedVerifyPolling,
    FinalMessageJudge,
    FinalMessageMentions,
    MergedSpfRecord,
    RecordsHandoffJudge,
    SendersInProject,
    SharedApplyUrl,
)
from products.workflows.evals.seeders import (
    CLAIMED_DOMAIN_SENDER,
    DOMAIN_CONNECT_SENDER,
    EXISTING_DMARC_SENDER,
    EXISTING_DMARC_VALUE,
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
    seed_existing_spf,
    seed_helpdesk_mx,
    seed_member_without_admin,
    seed_new_sender,
    seed_shared_domain_sender,
    seed_verified_sender,
)
from products.workflows.evals.simulated_email_domains import (
    MX_PRIORITY,
    SES_SPF_VALUE,
    DnsRecord,
    dkim_tokens,
    mail_from_mx_host,
    ses_records,
    simulated_email_domains,
    verification_token,
)

EMAIL_CREATE_TOOL = "integrations-email-create"

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
    "without making sending wait on new DNS records? A reminder to keep the existing SPF records published "
    "is fine."
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
HANDED_OVER_RECORDS = (
    "A user asked an assistant for the DNS records to add so a domain can send email. Does the "
    "message below give the user every record listed in <records>, each with its type, its host name "
    "(fully qualified, relative to the user's DNS zone, or `@` for the domain itself), its exact value, "
    "and the priority of the MX record? Layout and wording do not matter. A missing record, a wrong "
    "type, a host name that points somewhere else, or a changed or shortened value is a no."
)
HANDED_OVER_RECORDS_KEEPING_DMARC = (
    f"{HANDED_OVER_RECORDS} The domain already publishes a DMARC record, `{EXISTING_DMARC_VALUE}`, "
    "which must stay as it is, so it is not in the list. A message that tells the user to add a second "
    "`_dmarc` record, or to replace the existing policy, is a no. Saying the existing record stays is fine."
)
HANDED_OVER_RECORDS_MERGING_SPF = (
    f"{HANDED_OVER_RECORDS} The sending domain already has the SPF record `v=spf1 {EXISTING_SPF_INCLUDE} ~all`, "
    "and a host can publish only one SPF record. The list shows the single merged record that must "
    "replace it at the sending domain. A message that adds a second SPF record at the sending domain, "
    "or that drops the existing include, is a no."
)
MAIL_FROM_AVOIDS_HELPDESK = (
    "A user asked an assistant to set up an email sending domain. The `feedback` subdomain of the sending "
    "domain already has an MX record for the user's helpdesk tool, which must keep working. Does the message "
    "below put the bounce (MAIL FROM) MX and TXT records on a different subdomain, and leave the record at "
    "`feedback` as it is? A message that tells the user to add, change, or replace a record at `feedback` is a no."
)
ADMIN_NEEDED_EXPLAINED = (
    "A user asked an assistant to set up an email sending domain, but the user is a project member "
    "and a step needs project admin access, so the request was refused. Does the message below tell "
    "the user that a project admin has to do that step or grant access, rather than describing a "
    "broken tool or an unexplained failure? A message that says the domain is verified is a no."
)


def _exact_values(domain: str) -> list[str]:
    return [verification_token(domain), *dkim_tokens(domain), mail_from_mx_host()]


def _records_reference(records: list[DnsRecord]) -> str:
    return "\n".join(
        f"{record.record_type} {record.name} {record.value}"
        + (f" (priority {MX_PRIORITY})" if record.record_type == "MX" else "")
        for record in records
    )


def _without_dmarc(domain: str) -> list[DnsRecord]:
    return [record for record in ses_records(domain) if not record.name.startswith("_dmarc.")]


def _with_merged_root_spf(domain: str) -> list[DnsRecord]:
    merged = SES_SPF_VALUE.replace("v=spf1", f"v=spf1 {EXISTING_SPF_INCLUDE}")
    return [
        DnsRecord(name=record.name, record_type="TXT", value=merged)
        if record.name == domain and record.value == SES_SPF_VALUE
        else record
        for record in ses_records(domain)
    ]


def _cases() -> list[SandboxedEvalCase]:
    return [
        SandboxedEvalCase(
            name="domain_connect_link",
            prompt=f"Set up {DOMAIN_CONNECT_SENDER} as our Workflows email sender, with Hedgebox as the display name.",
            setup=seed_domain_connect_support,
            expected={
                "senders_in_project": {"senders": {DOMAIN_CONNECT_SENDER: {"name": "Hedgebox"}}},
                "shared_apply_url": {},
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
                "senders_in_project": {"senders": {MANUAL_SENDER: {"name": "Hedgebox"}}},
                "final_message_mentions": {"values": _exact_values(domain_of(MANUAL_SENDER))},
                "handed_over_records": {"records": _records_reference(ses_records(domain_of(MANUAL_SENDER)))},
                "bounded_verify_polling": {"max_calls": 3},
                "waits_for_manual_records": {},
            },
        ),
        SandboxedEvalCase(
            name="already_verified_sender",
            prompt=f"Can you set up {VERIFIED_SENDER} so our workflows can send email from it?",
            setup=seed_verified_sender,
            expected={
                "senders_in_project": {"senders": {VERIFIED_SENDER: {"verified": True}}},
                "avoided_tool": {"tools": [EMAIL_CREATE_TOOL]},
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
                        SHARED_DOMAIN_SENDER: {
                            "mail_from_subdomain": SHARED_DOMAIN_MAIL_FROM_SUBDOMAIN,
                            "verified": True,
                        },
                        SECOND_SENDER: {
                            "mail_from_subdomain": SHARED_DOMAIN_MAIL_FROM_SUBDOMAIN,
                            "name": "Hedgebox News",
                            "verified": True,
                        },
                    }
                },
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
                "senders_in_project": {"senders": {EXISTING_DMARC_SENDER: {"name": "Hedgebox"}}},
                "final_message_mentions": {"values": _exact_values(domain_of(EXISTING_DMARC_SENDER))},
                "handed_over_records_keeping_dmarc": {
                    "records": _records_reference(_without_dmarc(domain_of(EXISTING_DMARC_SENDER)))
                },
                "waits_for_manual_records": {},
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
            setup=seed_existing_spf,
            expected={
                "senders_in_project": {"senders": {EXISTING_SPF_SENDER: {"name": "Hedgebox"}}},
                "merged_spf_record": {"includes": [EXISTING_SPF_INCLUDE, "include:amazonses.com"]},
                "final_message_mentions": {"values": _exact_values(domain_of(EXISTING_SPF_SENDER))},
                "handed_over_records_merging_spf": {
                    "records": _records_reference(_with_merged_root_spf(domain_of(EXISTING_SPF_SENDER)))
                },
                "waits_for_manual_records": {},
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
            setup=seed_helpdesk_mx,
            expected={
                "senders_in_project": {"senders": {MAIL_FROM_TAKEN_SENDER: {"mail_from_subdomain_not": "feedback"}}},
                "final_message_mentions": {"values": _exact_values(domain_of(MAIL_FROM_TAKEN_SENDER))},
                "mail_from_avoids_helpdesk": {},
                "waits_for_manual_records": {},
                "bounded_verify_polling": {"max_calls": 3},
            },
        ),
        SandboxedEvalCase(
            name="free_mailbox_domain",
            prompt=f"Set up {FREE_MAILBOX_SENDER} as the sender for our Workflows emails.",
            setup=seed_new_sender(FREE_MAILBOX_SENDER),
            expected={
                "senders_in_project": {"senders": {}},
                "free_mailbox_explained": {},
            },
        ),
        SandboxedEvalCase(
            name="domain_claimed_by_another_org",
            prompt=f"Set up {CLAIMED_DOMAIN_SENDER} as our Workflows email sender, display name Hedgebox.",
            setup=seed_claimed_domain,
            expected={
                "senders_in_project": {"senders": {}},
                "claimed_domain_explained": {},
            },
        ),
        SandboxedEvalCase(
            name="member_cannot_verify",
            prompt=f"Set up {MEMBER_SENDER} as our Workflows email sender, display name Hedgebox.",
            setup=seed_member_without_admin,
            expected={
                "senders_in_project": {"senders": {MEMBER_SENDER: {"name": "Hedgebox"}}},
                "bounded_verify_polling": {"max_calls": 2},
                "admin_needed_explained": {},
            },
        ),
    ]


async def eval_email_domain_setup(ctx: EvalContext) -> None:
    if ctx.trials > 1:
        raise ValueError("eval_email_domain_setup runs one trial per case, because trials of a case share its domain")
    with simulated_email_domains():
        await SandboxedPrivateEval(
            experiment_name="sandboxed-email-domain-setup-cli",
            cases=_cases(),
            scorers=[
                SendersInProject(),
                AvoidedTool(),
                FinalMessageMentions(),
                MergedSpfRecord(),
                SharedApplyUrl(),
                BoundedVerifyPolling(),
                FinalMessageJudge(name="waits_for_domain_connect_approval", question=WAITS_FOR_DOMAIN_CONNECT_APPROVAL),
                FinalMessageJudge(name="waits_for_manual_records", question=WAITS_FOR_MANUAL_RECORDS),
                FinalMessageJudge(name="ready_without_dns_work", question=READY_WITHOUT_DNS_WORK),
                FinalMessageJudge(name="free_mailbox_explained", question=FREE_MAILBOX_EXPLAINED),
                FinalMessageJudge(name="claimed_domain_explained", question=CLAIMED_DOMAIN_EXPLAINED),
                FinalMessageJudge(name="admin_needed_explained", question=ADMIN_NEEDED_EXPLAINED),
                RecordsHandoffJudge(name="handed_over_records", question=HANDED_OVER_RECORDS),
                RecordsHandoffJudge(
                    name="handed_over_records_keeping_dmarc", question=HANDED_OVER_RECORDS_KEEPING_DMARC
                ),
                RecordsHandoffJudge(name="handed_over_records_merging_spf", question=HANDED_OVER_RECORDS_MERGING_SPF),
                FinalMessageJudge(name="mail_from_avoids_helpdesk", question=MAIL_FROM_AVOIDS_HELPDESK),
            ],
            ctx=ctx,
        )
