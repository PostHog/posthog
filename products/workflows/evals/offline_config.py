from uuid import UUID

from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite, OfflineScorer

_SCORERS: dict[str, OfflineScorer] = {
    "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a1be92-6004-7dd6-b218-ee3e41258425")),
    "senders_in_project": OfflineScorer(kind="boolean", version=UUID("01a1be92-67c2-7e31-b1f4-a353831172ce")),
    "avoided_tool": OfflineScorer(kind="boolean", version=UUID("01a1be92-700b-7c6b-a3df-e943cc3e8afb")),
    "final_message_mentions": OfflineScorer(kind="boolean", version=UUID("01a1be92-769e-7753-899e-ae20d59ae8c9")),
    "merged_spf_record": OfflineScorer(kind="boolean", version=UUID("01a1be92-7ee2-7e5b-bc52-808381d0d5c0")),
    "shared_apply_url": OfflineScorer(kind="boolean", version=UUID("01a1be92-8638-7fa2-8fc3-686742703f98")),
    "bounded_verify_polling": OfflineScorer(kind="boolean", version=UUID("01a1be92-8e4b-715d-ace7-74ddc8217c97")),
    "waits_for_domain_connect_approval": OfflineScorer(
        kind="boolean", version=UUID("01a1be92-96e7-7dbc-82d8-e135b6de278f")
    ),
    "waits_for_manual_records": OfflineScorer(kind="boolean", version=UUID("01a1be92-9f5a-71c2-9f60-dacd8984d5d7")),
    "ready_without_dns_work": OfflineScorer(kind="boolean", version=UUID("01a1be92-a77e-7640-8e28-e2683dd37a72")),
    "free_mailbox_explained": OfflineScorer(kind="boolean", version=UUID("01a1be92-afdd-799a-bcbf-8878bf77f1d2")),
    "claimed_domain_explained": OfflineScorer(kind="boolean", version=UUID("01a1be92-b812-777b-9b7d-4b28702c6da9")),
    "admin_needed_explained": OfflineScorer(kind="boolean", version=UUID("01a1be92-bff0-7a9d-bbaa-ce6cf46c22fd")),
    "handed_over_records": OfflineScorer(kind="boolean", version=UUID("01a1be92-c820-7388-950a-a9c1fb503981")),
    "handed_over_records_keeping_dmarc": OfflineScorer(
        kind="boolean", version=UUID("01a1be92-d107-711f-a5cc-8923fce3b629")
    ),
    "handed_over_records_merging_spf": OfflineScorer(
        kind="boolean", version=UUID("01a1be92-d9b9-79e2-9c30-c9adb7e806a2")
    ),
    "mail_from_avoids_helpdesk": OfflineScorer(kind="boolean", version=UUID("01a1be92-e13a-7bb0-9aab-bfc746d58d47")),
}


def email_domain_setup_suite() -> OfflineEvalSuite:
    return OfflineEvalSuite.from_scorers(
        key="workflows/eval_email_domain_setup::eval_email_domain_setup",
        project_id=2,
        scorers=_SCORERS,
        tags=("team:workflows", "component:workflows/email-domain-setup"),
    )
