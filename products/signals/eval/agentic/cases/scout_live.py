"""Synthetic live scout decision cases.

These cases were shaped from production scout trace patterns, but every project name,
event, metric, report id, owner, and repository is synthetic. They are for live
model comparison, not replay regression.
"""

from __future__ import annotations

from products.signals.eval.agentic.datasets import ScoutCase, ScoutExpectation
from products.signals.eval.agentic.scorers_scout import default_scout_scorers


def _case(
    case_id: str,
    scout_name: str,
    project_profile: str,
    prior_context: str,
    observations: str,
    candidate_reports: str,
    expected: ScoutExpectation,
) -> ScoutCase:
    return ScoutCase(
        case_id=case_id,
        step="scout",
        scout_name=scout_name,
        project_profile=project_profile,
        prior_context=prior_context,
        observations=observations,
        candidate_reports=candidate_reports,
        expected=expected,
        scorers=default_scout_scorers(),
    )


CASES: list[ScoutCase] = [
    _case(
        "scout_general_exception_burst_edit",
        "signals-scout-general",
        "Project Acme Analytics uses product analytics, error tracking, logs, and feature flags. Emit gate is open.",
        "Memory says malformed QueryEnvelope errors are covered by report rpt_live_query_noise.",
        "A prod exception class rose 7.1x: 2,240 events from 2,210 identities in one hour. "
        "The message and stack match the covered QueryEnvelope malformed-input capture path. Other risers are below bar.",
        "rpt_live_query_noise is live, READY, P4, and covers malformed QueryEnvelope capture noise.",
        ScoutExpectation(
            expected_decision="edit_report",
            expected_actionability="requires_human_input",
            expected_priority=("P3", "P4"),
            expected_existing_report_id="rpt_live_query_noise",
            min_evidence_items=2,
            required_summary_terms=("2,240", "QueryEnvelope"),
            required_scratchpad_keys=("dedupe:general:query-envelope-noise",),
        ),
    ),
    _case(
        "scout_general_quiet_weekend",
        "signals-scout-general",
        "Project Birch is active, with specialist scouts for errors, logs, surveys, and web analytics.",
        "Memory notes weekend traffic is normally 35% below weekday baseline; no open general reports.",
        "Cross-product cheap gates are normal: exceptions within 0.9x baseline, web traffic down 32% with normal "
        "weekend shape, LLM cost down 28%, and no newly-active products.",
        "No matching reports.",
        ScoutExpectation(
            expected_decision="close_quiet",
            expected_priority=(None,),
            required_summary_terms=("quiet", "weekend"),
            forbidden_summary_terms=("report filed",),
        ),
    ),
    _case(
        "scout_product_analytics_conversion_drop_emit",
        "signals-scout-product-analytics",
        "Project Cedar has saved funnel insight fun_activation: signed_up -> invited_teammate -> created_dashboard.",
        "Baseline memory: invite-step conversion normally 54%-58% with 8k-10k signed_up entrants per week.",
        "Latest complete week: signed_up entrants 9,180, invite-step conversion 38%, dashboard-step unchanged. "
        "Drop appears across browser and country segments. No experiment or insight edit in the window.",
        "No live report mentions fun_activation or invited_teammate conversion.",
        ScoutExpectation(
            expected_decision="emit_report",
            expected_actionability="requires_human_input",
            expected_priority=("P2", "P3", None),
            min_evidence_items=2,
            required_summary_terms=("38%", "invited_teammate"),
            required_scratchpad_keys=("report:product_analytics:fun_activation:invite_step",),
        ),
    ),
    _case(
        "scout_product_analytics_denominator_disqualifier",
        "signals-scout-product-analytics",
        "Project Delta has saved funnel fun_checkout: viewed_pricing -> started_checkout -> paid_invoice.",
        "Baseline memory: started_checkout conversion is stable when pricing entrants hold above 4k/day.",
        "Latest complete day shows conversion from viewed_pricing to started_checkout down from 19% to 9%, "
        "but viewed_pricing entrants also collapsed from 5,200/day to 1,050/day after a known campaign ended.",
        "No matching reports.",
        ScoutExpectation(
            expected_decision="remember_only",
            expected_priority=(None,),
            required_summary_terms=("denominator", "campaign"),
            required_scratchpad_keys=("baseline:product_analytics:fun_checkout",),
        ),
    ),
    _case(
        "scout_error_tracking_broad_reach_emit",
        "signals-scout-error-tracking",
        "Project Elm has error tracking enabled and normally sees 80-120 exceptions/hour.",
        "No dedupe entry for err_payment_token_missing. Reviewer memory maps checkout backend to octo-checkout.",
        "New issue err_payment_token_missing fired 1,940 times from 1,870 users in 90 minutes. "
        "Top frame is payments/api/checkout.py and first_seen aligns with deploy dep_42.",
        "No live report covers err_payment_token_missing or checkout token missing.",
        ScoutExpectation(
            expected_decision="emit_report",
            expected_actionability="immediately_actionable",
            expected_priority=("P1", "P2"),
            expected_repository="acme/webapp",
            min_evidence_items=3,
            required_summary_terms=("1,870", "checkout"),
            required_scratchpad_keys=("report:error_tracking:err_payment_token_missing",),
        ),
    ),
    _case(
        "scout_error_tracking_extension_noise_skip",
        "signals-scout-error-tracking",
        "Project Fir has error tracking enabled.",
        "Noise memory says browser extension stack frames with moz-extension:// and no app frames should be skipped.",
        "A TypeError appears 430 times from 12 users. Every frame is moz-extension://reader/inject.js; "
        "there are no application frames, no release correlation, and no affected server endpoint.",
        "No matching reports.",
        ScoutExpectation(
            expected_decision="skip",
            expected_actionability=("not_actionable", None),
            expected_priority=(None, "P4"),
            required_summary_terms=("extension", "skip"),
            forbidden_summary_terms=("P1",),
        ),
    ),
    _case(
        "scout_revenue_failed_invoice_emit",
        "signals-scout-revenue-analytics",
        "Project Grove has revenue analytics and billing warehouse tables connected.",
        "Baseline memory: failed invoice retry rate is 3%-5%; billing owner is octo-billing.",
        "Last 24h failed payment retries reached 18.4% across 312 invoices. The rise is isolated to annual invoices "
        "with coupon migration code coupon_migrate_v2, and expected MRR at risk is about 42k.",
        "No live report covers coupon_migrate_v2 or annual invoice retries.",
        ScoutExpectation(
            expected_decision="emit_report",
            expected_actionability="requires_human_input",
            expected_priority=("P1", "P2"),
            min_evidence_items=3,
            required_summary_terms=("18.4%", "42k"),
            required_scratchpad_keys=("report:revenue:coupon_migrate_v2_failed_retries",),
        ),
    ),
    _case(
        "scout_feature_flags_stale_rollout_emit",
        "signals-scout-feature-flags",
        "Project Hazel has 212 active feature flags.",
        "Memory says stale cleanup reports should route to octo-flags when the flag is still evaluated.",
        "Flag beta-new-nav is active, 100% rolled out, has no targeting conditions, and was evaluated "
        "1.8M times in 7 days. The related experiment ended 41 days ago.",
        "No live report covers beta-new-nav cleanup.",
        ScoutExpectation(
            expected_decision="emit_report",
            expected_actionability="immediately_actionable",
            expected_priority=("P3", "P4"),
            expected_repository="acme/webapp",
            min_evidence_items=2,
            required_summary_terms=("beta-new-nav", "1.8M"),
            required_scratchpad_keys=("report:feature_flags:beta-new-nav",),
        ),
    ),
    _case(
        "scout_web_analytics_bot_spike_skip",
        "signals-scout-web-analytics",
        "Project Iris uses web analytics on marketing pages.",
        "Noise memory: traffic from synthetic-monitor.example is expected during launch rehearsals.",
        "Landing page sessions jumped 260%, but 94% of the increase has user agent SyntheticMonitor/2.0, "
        "country is one data center region, bounce rate is 100%, and conversion traffic is unchanged.",
        "No matching reports.",
        ScoutExpectation(
            expected_decision="skip",
            expected_priority=(None,),
            required_summary_terms=("bot", "SyntheticMonitor"),
            forbidden_summary_terms=("emit"),
        ),
    ),
    _case(
        "scout_ai_observability_cost_spike_edit",
        "signals-scout-ai-observability",
        "Project Juniper captures LLM traces for assistant and batch summarization jobs.",
        "Memory points model-cost regression for assistant_summary to live report rpt_ai_summary_cost.",
        "assistant_summary daily cost is 3.6x baseline: 910 dollars yesterday vs 240-290 typical. "
        "Token volume is flat, but output tokens per generation doubled after prompt version pv_17.",
        "rpt_ai_summary_cost is live and covers assistant_summary cost regressions.",
        ScoutExpectation(
            expected_decision="edit_report",
            expected_actionability="requires_human_input",
            expected_priority=("P2", "P3"),
            expected_existing_report_id="rpt_ai_summary_cost",
            min_evidence_items=2,
            required_summary_terms=("3.6x", "pv_17"),
            required_scratchpad_keys=("dedupe:ai_observability:assistant_summary_cost",),
        ),
    ),
    _case(
        "scout_slo_latency_breach_emit",
        "signals-scout-slo-monitoring",
        "Project Koa has an SLO for /api/query p95 latency under 2.5s.",
        "No open report for /api/query latency; owner memory maps query API to octo-query.",
        "For the last 3 complete hours, /api/query p95 was 6.8s, 7.1s, and 6.5s with normal request volume. "
        "Error rate stayed flat, so this is a latency-only regression.",
        "No matching reports.",
        ScoutExpectation(
            expected_decision="emit_report",
            expected_actionability="requires_human_input",
            expected_priority=("P1", "P2"),
            min_evidence_items=2,
            required_summary_terms=("p95", "6.8s"),
            required_scratchpad_keys=("report:slo:/api/query:p95",),
        ),
    ),
    _case(
        "scout_surveys_negative_theme_emit",
        "signals-scout-surveys",
        "Project Laurel runs an in-app churn survey with free-text responses.",
        "Baseline memory: integration setup complaints are usually 4%-7% of churn responses.",
        "In the last 72h, 29 of 86 churn responses mention OAuth setup loops or redirect mismatch. "
        "That is 34%, and examples span six accounts.",
        "No live report covers OAuth setup loops from surveys.",
        ScoutExpectation(
            expected_decision="emit_report",
            expected_actionability="requires_human_input",
            expected_priority=("P2", "P3"),
            min_evidence_items=2,
            required_summary_terms=("34%", "OAuth"),
            required_scratchpad_keys=("report:surveys:oauth-setup-loops",),
        ),
    ),
    _case(
        "scout_anomaly_known_launch_skip",
        "signals-scout-anomaly-detection",
        "Project Maple has anomaly detection on top events.",
        "Addressed memory says import_completed volume will spike during the planned migration mig_2026_07.",
        "import_completed is 11x baseline for six hours, but the migration window and owner note match mig_2026_07. "
        "No downstream error, latency, or conversion metric moved.",
        "No matching reports.",
        ScoutExpectation(
            expected_decision="skip",
            expected_priority=(None,),
            required_summary_terms=("migration", "skip"),
            forbidden_summary_terms=("report-worthy",),
        ),
    ),
    _case(
        "scout_session_replay_checkout_rage_emit",
        "signals-scout-session-replay",
        "Project Noble has session recording and checkout funnel instrumentation.",
        "No dedupe entry for checkout coupon rage clicks.",
        "38 recordings in 24h show users repeatedly clicking Apply coupon on checkout. "
        "29 of those sessions abandon within two minutes; console shows CouponValidationError in 24 sessions.",
        "No live report covers Apply coupon rage clicks.",
        ScoutExpectation(
            expected_decision="emit_report",
            expected_actionability="requires_human_input",
            expected_priority=("P2", "P3"),
            min_evidence_items=3,
            required_summary_terms=("38", "coupon"),
            required_scratchpad_keys=("report:session_replay:checkout-coupon-rage",),
        ),
    ),
    _case(
        "scout_logs_existing_worker_loop_edit",
        "signals-scout-logs",
        "Project Olive ships structured logs for worker and web services.",
        "Dedupe memory says worker sync loop is covered by report rpt_worker_sync_loop.",
        "worker-sync emitted 18k ERROR logs in 45 minutes from job sync_partner_accounts. "
        "The exception text matches rpt_worker_sync_loop; this is ongoing rather than a new class.",
        "rpt_worker_sync_loop is live and assigned to octo-integrations.",
        ScoutExpectation(
            expected_decision="edit_report",
            expected_actionability="requires_human_input",
            expected_priority=("P2", "P3"),
            expected_existing_report_id="rpt_worker_sync_loop",
            min_evidence_items=2,
            required_summary_terms=("18k", "sync_partner_accounts"),
            required_scratchpad_keys=("dedupe:logs:worker-sync-loop",),
        ),
    ),
    _case(
        "scout_observability_gaps_not_in_use_close",
        "signals-scout-observability-gaps",
        "Project Pine has only pageview and identify events. No session recording, flags, surveys, logs, or errors.",
        "Prior three runs all recorded pre-ingestion state.",
        "Taxonomy still has no business events above 10/day, no saved insights, and no recordings. Emit gate is open, "
        "but there is no behavioral surface to evaluate.",
        "No matching reports.",
        ScoutExpectation(
            expected_decision="close_quiet",
            expected_priority=(None,),
            required_summary_terms=("pre-ingestion", "no business events"),
            required_scratchpad_keys=("not-in-use:observability-gaps:team-synthetic",),
        ),
    ),
    _case(
        "scout_health_checks_integration_emit",
        "signals-scout-health-checks",
        "Project Quartz has five active webhook integrations.",
        "Baseline memory: webhook_delivery_failed is below 20/day.",
        "webhook_delivery_failed reached 1,260 events in 24h across 78 accounts. Failures are isolated to "
        "CRM destination crm_delta and started after secret rotation rot_19.",
        "No live report covers crm_delta delivery failures.",
        ScoutExpectation(
            expected_decision="emit_report",
            expected_actionability="requires_human_input",
            expected_priority=("P2", "P3"),
            min_evidence_items=2,
            required_summary_terms=("1,260", "crm_delta"),
            required_scratchpad_keys=("report:health_checks:crm_delta_delivery_failures",),
        ),
    ),
    _case(
        "scout_mcp_tool_calls_emit",
        "signals-scout-mcp-tool-calls",
        "Project Rowan uses MCP heavily from multiple clients.",
        "No report exists for schema-search failures. Owner memory maps MCP tools to octo-mcp.",
        "mcp_tool_call failures for schema-search rose from 0.4% to 17.8% over 6 hours. "
        "The failures affect 41 distinct clients and return the same validation error.",
        "No matching reports.",
        ScoutExpectation(
            expected_decision="emit_report",
            expected_actionability="immediately_actionable",
            expected_priority=("P1", "P2"),
            expected_repository="acme/mcp-server",
            min_evidence_items=2,
            required_summary_terms=("17.8%", "schema-search"),
            required_scratchpad_keys=("report:mcp:schema-search-validation",),
        ),
    ),
    _case(
        "scout_skill_issues_remember_only",
        "signals-scout-skill-issues",
        "Project Spruce runs 24 scouts. Skill self-improvement entries are enabled.",
        "Prior run noted the revenue scout spends too many calls rediscovering warehouse table names.",
        "This run saw the same pattern twice, but no report should be filed: the skill eventually found the tables, "
        "and the issue is prompt-budget waste rather than a customer-facing product defect.",
        "No matching reports.",
        ScoutExpectation(
            expected_decision="remember_only",
            expected_priority=(None,),
            required_summary_terms=("budget", "warehouse"),
            required_scratchpad_keys=("improve:signals-scout-revenue-analytics:warehouse-table-discovery",),
        ),
    ),
    _case(
        "scout_support_self_driving_backlog_emit",
        "signals-scout-support-self-driving",
        "Project Teak has support automation enabled for inbound tickets.",
        "Baseline memory: auto-triage backlog above 50 tickets for more than 2h is report-worthy.",
        "Auto-triage queue has 143 unprocessed tickets, oldest age 5.4h, while inbound ticket volume is normal. "
        "Worker health shows the triage consumer has zero successful runs since deploy dep_84.",
        "No live report covers auto-triage backlog.",
        ScoutExpectation(
            expected_decision="emit_report",
            expected_actionability="requires_human_input",
            expected_priority=("P1", "P2"),
            min_evidence_items=3,
            required_summary_terms=("143", "5.4h"),
            required_scratchpad_keys=("report:support-self-driving:auto-triage-backlog",),
        ),
    ),
    _case(
        "scout_inbox_validation_duplicate_skip",
        "signals-scout-inbox-validation",
        "Project Umber has 220 open inbox reports.",
        "Memory says duplicate reports on dashboard export failures should be consolidated into rpt_dashboard_export.",
        "A candidate finding describes dashboard export jobs failing for CSV downloads, but the candidate report "
        "has the same title, same entity, and was updated 18 minutes ago with fresher evidence.",
        "rpt_dashboard_export is live, same issue, updated 18 minutes ago.",
        ScoutExpectation(
            expected_decision="skip",
            expected_existing_report_id="rpt_dashboard_export",
            expected_priority=(None,),
            required_summary_terms=("duplicate", "rpt_dashboard_export"),
            forbidden_summary_terms=("emit_report",),
        ),
    ),
    _case(
        "scout_error_tracking_synthetic_load_skip",
        "signals-scout-error-tracking",
        "Project Vale has error tracking and runs a nightly synthetic load test.",
        "Noise memory: load_test_nightly runs 02:00-03:00 UTC from three service accounts and emits SyntheticProbeError.",
        "Between 02:10 and 02:50 UTC, SyntheticProbeError fired 5,300 times, but only from the three load-test "
        "service accounts, with no real user identities and no other error class moving. The window matches load_test_nightly.",
        "No matching reports.",
        ScoutExpectation(
            expected_decision="skip",
            expected_priority=(None,),
            required_summary_terms=("5,300", "SyntheticProbeError"),
            forbidden_summary_terms=("emit_report",),
            required_scratchpad_keys=("dedupe:error_tracking:synthetic-load-test",),
        ),
    ),
    _case(
        "scout_product_analytics_composition_rise_remember",
        "signals-scout-product-analytics",
        "Project Willow has saved funnel fun_trial: started_trial -> activated -> converted.",
        "Baseline memory: activated-to-converted holds 22%-26% with 3k-4k activated users per week.",
        "Latest week activated-to-converted jumped to 41%, but activated users collapsed from 3,400 to 900 after a "
        "hard paywall now blocks low-intent users upstream. The rate rose only because the remaining denominator is high-intent.",
        "No matching reports.",
        ScoutExpectation(
            expected_decision="remember_only",
            expected_priority=(None,),
            required_summary_terms=("41%", "paywall"),
            required_scratchpad_keys=("baseline:product_analytics:fun_trial",),
        ),
    ),
    _case(
        "scout_slo_latency_blip_recovered_close",
        "signals-scout-slo-monitoring",
        "Project Yarrow has an SLO for /api/export p95 latency under 3s.",
        "No open report for /api/export latency.",
        "Six hours ago /api/export p95 hit 9s for a single 5-minute window during a one-off backup job, but the "
        "last 5 complete hours are back to 1.9s with no error-rate change and no user complaints.",
        "No matching reports.",
        ScoutExpectation(
            expected_decision="close_quiet",
            expected_priority=(None,),
            required_summary_terms=("1.9s", "backup"),
            forbidden_summary_terms=("P1",),
        ),
    ),
    _case(
        "scout_error_tracking_covered_no_new_evidence_skip",
        "signals-scout-error-tracking",
        "Project Zinc has error tracking enabled.",
        "Dedupe memory: DatabaseTimeout on the reporting service is covered by report rpt_db_timeout.",
        "DatabaseTimeout is still firing at its usual ~600/hour with the same stack, same endpoint, and the same "
        "affected-user count as when rpt_db_timeout was filed. There is no new deploy correlation or reach change.",
        "rpt_db_timeout is live, READY, and covers reporting-service DatabaseTimeout.",
        ScoutExpectation(
            expected_decision="skip",
            expected_existing_report_id="rpt_db_timeout",
            expected_priority=(None,),
            required_summary_terms=("rpt_db_timeout", "DatabaseTimeout"),
            forbidden_summary_terms=("emit_report",),
        ),
    ),
]
