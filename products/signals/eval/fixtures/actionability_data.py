"""Fixtures for the pre-emit actionability eval.

Every case is invented: no customer, company, or person in it is real, and every address uses example.com.
The set is held out from prompt tuning, so do not edit a prompt to make one of these cases pass.
Labels come only from the written policy below, not from any classifier output.

ACTIONABLE: a bug, error, or unexpected behavior; a feature request or improvement idea; a usability issue or a
misreading of how a feature works; a performance problem; a how-to question about the product or its integrations;
a request for help with the product; a self-hosted deployment or configuration problem. A rude message still counts
when it names a specific feature, behavior, or error.

NOT_ACTIONABLE: spam, abuse, or profanity with no feedback; a request for a manual human action rather than a product
change (refund, billing email or card update, pricing or plan question, invoice copy); a generic thank-you or close
request; an auto-reply or out-of-office message; an internal test message; a GitHub bot or tracking issue; a bare
duplicate with nothing new; dissatisfaction that names no specific feature, behavior, or error; a report that
contradicts itself so no single problem can be identified.

Each `description` follows the layout its emitter builds: `subject\\nbody` for Zendesk, `title\\nbody` for GitHub,
Linear, and Jira, and `subject\\n` plus `C:`/`T:`-tagged message lines for Conversations.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionabilityCase:
    name: str
    source_product: str
    source_type: str
    actionable: bool
    category: str
    description: str


_ZENDESK = ("zendesk", "ticket")
_CONVERSATIONS = ("conversations", "ticket")
_GITHUB = ("github", "issue")
_LINEAR = ("linear", "issue")
_JIRA = ("jira", "issue")


def _titled(title: str, body: str) -> str:
    return f"{title}\n{body}"


def _conversation(subject: str, messages: list[tuple[str, str]]) -> str:
    tags = {"customer": "C", "team": "T"}
    return "\n".join([subject, *(f"{tags[author]}: {content}" for author, content in messages)])


def _case(name: str, source: tuple[str, str], actionable: bool, category: str, description: str) -> ActionabilityCase:
    source_product, source_type = source
    return ActionabilityCase(
        name=name,
        source_product=source_product,
        source_type=source_type,
        actionable=actionable,
        category=category,
        description=description,
    )


# --- NOT_ACTIONABLE: vague dissatisfaction (no feature, behavior, or error named) -----------------

_VAGUE = [
    _case(
        "vague_terrible_product",
        _ZENDESK,
        False,
        "vague_dissatisfaction",
        _titled("Terrible", "Your product is terrible. Honestly expected better."),
    ),
    _case(
        "vague_switching_vendor",
        _CONVERSATIONS,
        False,
        "vague_dissatisfaction",
        _conversation(
            "Done with this",
            [
                ("customer", "Nothing works. We are switching to another tool next month."),
                ("team", "Sorry to hear that! Could you tell us what went wrong so we can look into it?"),
                ("customer", "Everything. I don't have time for this."),
            ],
        ),
    ),
    _case(
        "vague_long_emotional_rant",
        _ZENDESK,
        False,
        "vague_dissatisfaction",
        _titled(
            "I am so disappointed",
            "I have been a loyal user for almost three years. I recommended you to every team I worked with. "
            "I defended you in meetings when people asked why we were paying for this. And now I feel like a fool.\n\n"
            "It used to feel like you cared. It used to feel like someone on the other side was listening. "
            "Now every week is a new frustration and I am tired of explaining to my manager why things are the way "
            "they are. I do not even know where to start anymore. It is just not the product I fell in love with.\n\n"
            "I am not asking for anything specific. I just wanted someone to know how let down I feel.",
        ),
    ),
    _case(
        "vague_quality_went_downhill",
        _CONVERSATIONS,
        False,
        "vague_dissatisfaction",
        _conversation(
            "Feedback",
            [("customer", "Quality has really gone downhill lately. Not great.")],
        ),
    ),
    _case(
        "vague_github_complaint",
        _GITHUB,
        False,
        "vague_dissatisfaction",
        _titled(
            "This project has lost its way",
            "Every release makes things worse. I don't understand who is making decisions here. "
            "Please get it together.",
        ),
    ),
    _case(
        "vague_ceo_escalation_tone",
        _ZENDESK,
        False,
        "vague_dissatisfaction",
        _titled(
            "Unacceptable experience",
            "Our leadership team is extremely unhappy with the overall experience we have had with your platform "
            "this quarter. It has not met our expectations in any way, and frankly it has been a waste of our "
            "team's energy. We expect a significant improvement or we will reconsider the relationship at renewal.",
        ),
    ),
    _case(
        "vague_why_so_hard",
        _CONVERSATIONS,
        False,
        "vague_dissatisfaction",
        _conversation(
            "why",
            [("customer", "why is everything with you guys so hard?? seriously. so frustrating")],
        ),
    ),
    _case(
        "vague_linear_customer_sentiment",
        _LINEAR,
        False,
        "vague_dissatisfaction",
        _titled(
            "Customer unhappy (relayed from call)",
            "Relaying from a call today: the customer said they are generally unhappy and the product "
            '"doesn\'t feel reliable". They could not give an example when asked.',
        ),
    ),
]

# --- NOT_ACTIONABLE: self-contradictory reports ----------------------------------------------------

_CONTRADICTORY = [
    _case(
        "contradictory_export_empty_and_too_many_rows",
        _ZENDESK,
        False,
        "contradictory",
        _titled(
            "CSV export broken",
            "When I export the events table the CSV file is completely empty, there is nothing in it. "
            "Also the export has way too many rows, it includes events I never asked for. Please fix the export.",
        ),
    ),
    _case(
        "contradictory_flag_on_and_off",
        _CONVERSATIONS,
        False,
        "contradictory",
        _conversation(
            "Flag issue",
            [
                (
                    "customer",
                    "Our feature flag is returning true for every user even though rollout is 0%. "
                    "Actually it returns false for every user even at 100%. Both are happening, it's the same flag "
                    "and the same users.",
                ),
                ("team", "Thanks! Which one do you see right now when you call it?"),
                (
                    "customer",
                    "Yes.",
                ),
            ],
        ),
    ),
    _case(
        "contradictory_replay_missing_and_duplicated",
        _GITHUB,
        False,
        "contradictory",
        _titled(
            "Session replay recordings wrong",
            "No recordings are being captured at all since yesterday, the list is empty. "
            "At the same time every session shows up twice in the list with identical recordings. "
            "SDK version is the latest one.",
        ),
    ),
    _case(
        "contradictory_funnel_numbers",
        _JIRA,
        False,
        "contradictory",
        _titled(
            "Funnel conversion number is wrong",
            "The signup funnel shows 0% conversion but our database shows conversions. "
            "The funnel shows 100% conversion, which can't be right either. "
            "It's the same funnel and the same date range, no filters changed.",
        ),
    ),
    _case(
        "contradictory_survey_shown_never_and_always",
        _ZENDESK,
        False,
        "contradictory",
        _titled(
            "Survey display",
            "Our survey never appears for anyone. It also keeps appearing on every single page load and users are "
            "annoyed by it. I only have one survey.",
        ),
    ),
]

# --- NOT_ACTIONABLE: manual billing asks -----------------------------------------------------------

_MANUAL_BILLING = [
    _case(
        "billing_refund_request",
        _ZENDESK,
        False,
        "manual_billing",
        _titled(
            "Refund for last month",
            "Hi, we forgot to cancel before our renewal date. Could you refund last month's charge? Thanks.",
        ),
    ),
    _case(
        "billing_update_email",
        _CONVERSATIONS,
        False,
        "manual_billing",
        _conversation(
            "Billing contact change",
            [
                (
                    "customer",
                    "Please change our billing email to finance@example.com and send future invoices there.",
                )
            ],
        ),
    ),
    _case(
        "billing_invoice_copy_and_plan_question",
        _ZENDESK,
        False,
        "manual_billing",
        _titled(
            "Invoice copy + plan",
            "Can you send me a PDF copy of the March invoice? Also, is there a discount if we pay annually instead "
            "of monthly?",
        ),
    ),
]

# --- NOT_ACTIONABLE: thank-you / close ------------------------------------------------------------

_THANKS = [
    _case(
        "thanks_resolved_close",
        _CONVERSATIONS,
        False,
        "thank_you_close",
        _conversation(
            "Re: Help with setup",
            [
                ("team", "Glad that worked! Anything else we can help with?"),
                ("customer", "All good now, thanks so much. You can close this."),
            ],
        ),
    ),
    _case(
        "thanks_generic",
        _ZENDESK,
        False,
        "thank_you_close",
        _titled("Thank you!", "Just wanted to say thanks to the team, you have been great."),
    ),
]

# --- NOT_ACTIONABLE: auto-replies ------------------------------------------------------------------

_AUTO_REPLIES = [
    _case(
        "auto_reply_out_of_office",
        _ZENDESK,
        False,
        "auto_reply",
        _titled(
            "Automatic reply: Your request has been updated",
            "I am out of the office until Monday with limited access to email. "
            "For urgent matters please contact ops@example.com.",
        ),
    ),
    _case(
        "auto_reply_ticket_received",
        _CONVERSATIONS,
        False,
        "auto_reply",
        _conversation(
            "Re: Your weekly digest",
            [
                (
                    "customer",
                    "This is an automated message. Your email has been received and a ticket has been created in our "
                    "helpdesk. Reference number: REF-000000. Please do not reply to this message.",
                )
            ],
        ),
    ),
]

# --- NOT_ACTIONABLE: spam and abuse ---------------------------------------------------------------

_SPAM = [
    _case(
        "spam_seo_offer",
        _ZENDESK,
        False,
        "spam",
        _titled(
            "Boost your website ranking today",
            "Dear sir/madam, we offer guaranteed first page ranking and 10,000 backlinks for a low price. "
            "Reply to this email for a free audit. Visit seo-offers.example.com.",
        ),
    ),
    _case(
        "spam_abuse_no_feedback",
        _CONVERSATIONS,
        False,
        "spam",
        _conversation(
            "!!!!",
            [("customer", "you are all useless idiots. go to hell")],
        ),
    ),
]

# --- NOT_ACTIONABLE: internal test messages -------------------------------------------------------

_INTERNAL_TEST = [
    _case(
        "internal_test_message",
        _CONVERSATIONS,
        False,
        "internal_test",
        _conversation(
            "test",
            [("customer", "testing the widget, please ignore. asdf 123")],
        ),
    ),
]

# --- NOT_ACTIONABLE: GitHub bot and tracking issues -----------------------------------------------

_BOTS = [
    _case(
        "github_dependency_bump",
        _GITHUB,
        False,
        "github_bot",
        _titled(
            "chore(deps): bump example-http-lib from 2.4.1 to 2.4.2",
            "Bumps example-http-lib from 2.4.1 to 2.4.2.\n\nRelease notes\nSee the changelog for details.\n\n"
            "Dependabot will resolve any conflicts with this PR as long as you don't alter it yourself.",
        ),
    ),
    _case(
        "github_release_checklist",
        _GITHUB,
        False,
        "github_bot",
        _titled(
            "Release 1.42.0 checklist",
            "- [ ] Bump version\n- [ ] Update changelog\n- [ ] Tag release\n- [ ] Publish to package registry\n"
            "- [ ] Announce",
        ),
    ),
    _case(
        "github_bare_title_link",
        _GITHUB,
        False,
        "github_bot",
        _titled("Tracking: Q3 SDK work", "https://tracker.example.com/board/12"),
    ),
]

# --- NOT_ACTIONABLE: bare duplicates ---------------------------------------------------------------

_DUPLICATES = [
    _case(
        "duplicate_same_as_issue",
        _GITHUB,
        False,
        "bare_duplicate",
        _titled("Same problem as #4512", "Same as #4512."),
    ),
    _case(
        "duplicate_plus_one",
        _LINEAR,
        False,
        "bare_duplicate",
        _titled("Duplicate of ENG-2210", "+1, duplicate of ENG-2210."),
    ),
]

# --- ACTIONABLE: angry or rude, but names a specific behavior -------------------------------------

_ANGRY_SPECIFIC = [
    _case(
        "angry_dashboard_filters_reset",
        _ZENDESK,
        True,
        "angry_specific",
        _titled(
            "FIX YOUR DASHBOARDS",
            "This is absolutely ridiculous. Every single time I reload a dashboard the date filter resets to "
            "last 7 days and I lose the custom range I set. I have reported this before. Do your jobs.",
        ),
    ),
    _case(
        "angry_sdk_crash_on_ios",
        _GITHUB,
        True,
        "angry_specific",
        _titled(
            "Your iOS SDK crashes our app, unbelievable",
            "Seriously, who tested this? After upgrading the iOS SDK our app crashes on launch with "
            "EXC_BAD_ACCESS inside the session replay screenshot code. We had to roll back in production. "
            "Pathetic.",
        ),
    ),
    _case(
        "angry_survey_spam_users",
        _CONVERSATIONS,
        True,
        "angry_specific",
        _conversation(
            "Your surveys are harassing my users",
            [
                (
                    "customer",
                    "What the hell. I set the survey to show once per user and it shows on every page view. "
                    "Our users are furious. Garbage.",
                )
            ],
        ),
    ),
    _case(
        "angry_warehouse_sync_timeout",
        _JIRA,
        True,
        "angry_specific",
        _titled(
            "Customer furious: data warehouse sync keeps timing out",
            "Customer was very rude on the call but the issue is real: their Postgres source sync fails every night "
            'with "query timeout after 3600s" on the orders table, and they have had no fresh data for four days.',
        ),
    ),
    _case(
        "angry_billing_page_404",
        _ZENDESK,
        True,
        "angry_specific",
        _titled(
            "can't even pay you, great job",
            'Your billing page gives me a 404 when I click "Upgrade plan". I am literally trying to give you money '
            "and you won't let me. Absolute joke of a company.",
        ),
    ),
]

# --- ACTIONABLE: how-to questions -----------------------------------------------------------------

_HOW_TO = [
    _case(
        "howto_flag_local_evaluation",
        _CONVERSATIONS,
        True,
        "how_to",
        _conversation(
            "Local evaluation for flags",
            [
                (
                    "customer",
                    "How do I set up local evaluation for feature flags in the Python SDK? "
                    "I can't find where the key goes.",
                )
            ],
        ),
    ),
    _case(
        "howto_funnel_breakdown_by_cohort",
        _ZENDESK,
        True,
        "how_to",
        _titled(
            "Breakdown a funnel by cohort?",
            "Is it possible to break down a funnel by cohort membership? I want to compare trial users vs paid users "
            "in one chart.",
        ),
    ),
    _case(
        "howto_replay_mask_inputs",
        _CONVERSATIONS,
        True,
        "how_to",
        _conversation(
            "Masking in recordings",
            [("customer", "how do i mask just one text input in session replay but keep the rest visible?")],
        ),
    ),
    _case(
        "howto_warehouse_join",
        _ZENDESK,
        True,
        "how_to",
        _titled(
            "Joining warehouse table to persons",
            "We synced our CRM accounts table into the data warehouse. How do I join it to persons so I can filter "
            "insights by account plan?",
        ),
    ),
    _case(
        "howto_node_queue_worker",
        _GITHUB,
        True,
        "how_to",
        _titled(
            "Question: sending server-side events from a queue worker",
            "What's the recommended way to send events from a background queue worker with the Node SDK? "
            "Should I call shutdown after each job or keep one client alive?",
        ),
    ),
]

# --- ACTIONABLE: working-as-intended confusion ----------------------------------------------------

_WAI_CONFUSION = [
    _case(
        "wai_unique_users_not_additive",
        _ZENDESK,
        True,
        "working_as_intended_confusion",
        _titled(
            "Unique users numbers don't add up",
            "My trend shows 1,200 unique users per day for each of the 7 days, but the weekly total says 3,100. "
            "Shouldn't it be 8,400? Something is broken.",
        ),
    ),
    _case(
        "wai_flag_rollout_sticky",
        _CONVERSATIONS,
        True,
        "working_as_intended_confusion",
        _conversation(
            "Flag rollout not random?",
            [
                (
                    "customer",
                    "I set a flag to 50% rollout but the same users always get it. I expected it to be random each "
                    "time they load the page. Is the randomization broken?",
                )
            ],
        ),
    ),
    _case(
        "wai_timezone_day_boundary",
        _LINEAR,
        True,
        "working_as_intended_confusion",
        _titled(
            "Events showing on the wrong day",
            "Customer reports events from late evening appear on the next day in trends. Their project timezone is "
            "UTC and they are in a UTC-7 timezone; they expected their local day boundaries.",
        ),
    ),
    _case(
        "wai_survey_sampling",
        _ZENDESK,
        True,
        "working_as_intended_confusion",
        _titled(
            "Survey only shown to some users",
            "Our survey is only appearing for some users. I didn't set any targeting, just left the \"percentage of "
            "users\" box at the default. Why isn't everyone seeing it?",
        ),
    ),
]

# --- ACTIONABLE: self-hosted / config problems ----------------------------------------------------

_SELF_HOSTED = [
    _case(
        "selfhost_clickhouse_migration_fails",
        _GITHUB,
        True,
        "self_hosted",
        _titled(
            "Self-hosted upgrade fails on ClickHouse migration",
            "Upgrading our self-hosted install with docker compose, the migrate step exits with "
            '"Code: 60. Table sharded_events doesn\'t exist". Fresh volume, followed the upgrade guide.',
        ),
    ),
    _case(
        "selfhost_reverse_proxy_cors",
        _ZENDESK,
        True,
        "self_hosted",
        _titled(
            "Events blocked behind reverse proxy",
            "We put the ingestion endpoint behind our nginx reverse proxy at analytics.example.com. The browser now "
            "shows CORS errors on /e/ and no events arrive. What headers do we need to forward?",
        ),
    ),
    _case(
        "selfhost_object_storage_config",
        _JIRA,
        True,
        "self_hosted",
        _titled(
            "Self-hosted: recordings not saved to object storage",
            'Customer\'s self-hosted deployment captures replay events but playback shows "recording not found". '
            "Logs show S3 PutObject failing with 403 against their custom bucket endpoint.",
        ),
    ),
    _case(
        "selfhost_env_var_ignored",
        _CONVERSATIONS,
        True,
        "self_hosted",
        _conversation(
            "SITE_URL setting ignored",
            [
                (
                    "customer",
                    "On our self-hosted instance we set SITE_URL to https://analytics.example.com but invite emails "
                    "still link to localhost:8000.",
                ),
                ("team", "Did you restart the worker containers as well as web?"),
                ("customer", "Yes, all containers restarted. Still localhost in the email links."),
            ],
        ),
    ),
]

# --- ACTIONABLE: billing tickets where the product malfunctioned ----------------------------------

_BILLING_MALFUNCTION = [
    _case(
        "billing_coupon_not_applied",
        _ZENDESK,
        True,
        "billing_malfunction",
        _titled(
            "Coupon accepted but not applied",
            'At checkout the coupon code showed "applied" with a green check, but the final charge was the full '
            "price and the invoice shows no discount.",
        ),
    ),
    _case(
        "billing_usage_double_counted",
        _CONVERSATIONS,
        True,
        "billing_malfunction",
        _conversation(
            "Usage on billing page doubled",
            [
                (
                    "customer",
                    "The billing page shows 4M events this month but our event count in insights is about 2M. "
                    "It looks like every event is counted twice on the usage meter.",
                )
            ],
        ),
    ),
    _case(
        "billing_limit_not_enforced",
        _JIRA,
        True,
        "billing_malfunction",
        _titled(
            "Billing limit ignored for session replay",
            "Customer set a $200 billing limit on session replay. Usage kept ingesting and they were charged $640. "
            "The limit shows as saved in settings.",
        ),
    ),
]

# --- ACTIONABLE: short but specific ---------------------------------------------------------------

_SHORT_SPECIFIC = [
    _case(
        "short_heatmap_blank",
        _CONVERSATIONS,
        True,
        "short_specific",
        _conversation("heatmap", [("customer", "heatmap toolbar is blank on safari")]),
    ),
    _case(
        "short_csv_export_500",
        _LINEAR,
        True,
        "short_specific",
        _titled("Cohort CSV export 500s", "Exporting a cohort as CSV returns a 500."),
    ),
]

# --- ACTIONABLE: ordinary bugs --------------------------------------------------------------------

_BUGS = [
    _case(
        "bug_insight_tooltip_wrong_series",
        _LINEAR,
        True,
        "bug",
        _titled(
            "Trend tooltip shows values for the wrong series",
            "With more than 10 series on a line chart, hovering a point shows the value of the series above it. "
            "Reproduces on any trend with a breakdown of 12+ values.",
        ),
    ),
    _case(
        "bug_flag_payload_not_returned",
        _GITHUB,
        True,
        "bug",
        _titled(
            "getFeatureFlagPayload returns undefined for multivariate flag",
            "Steps:\n1. Create a multivariate flag with JSON payloads per variant.\n2. Call getFeatureFlagPayload in "
            "the JS SDK.\n\nExpected: the variant payload. Actual: undefined, although the variant itself is "
            "returned correctly.",
        ),
    ),
    _case(
        "bug_dashboard_duplicate_loses_text",
        _JIRA,
        True,
        "bug",
        _titled(
            "Duplicating a dashboard drops text tiles",
            "When a dashboard is duplicated, all insight tiles are copied but the markdown text tiles are missing.",
        ),
    ),
    _case(
        "bug_survey_rating_scale",
        _ZENDESK,
        True,
        "bug",
        _titled(
            "NPS survey shows 1-10 instead of 0-10",
            "We created an NPS question with a 0-10 scale. In the popup it renders 1 to 10, so we can't record a "
            "zero score.",
        ),
    ),
    _case(
        "bug_replay_playback_stalls",
        _CONVERSATIONS,
        True,
        "bug",
        _conversation(
            "Replay stops halfway",
            [
                (
                    "customer",
                    "Recordings longer than about 20 minutes stop playing at the same point and the spinner never "
                    "goes away. Shorter ones are fine.",
                ),
                ("team", "Thanks, does it happen in more than one browser?"),
                ("customer", "Yes, Chrome and Firefox both."),
            ],
        ),
    ),
    _case(
        "bug_retention_blank_cells",
        _LINEAR,
        True,
        "bug",
        _titled(
            "Retention table shows blank cells for recent cohorts",
            "Cohorts from the last 3 weeks show empty cells instead of 0% in the retention table. "
            "Users read this as missing data.",
        ),
    ),
]

# --- ACTIONABLE: feature requests -----------------------------------------------------------------

_FEATURE_REQUESTS = [
    _case(
        "feature_dashboard_scheduled_pdf",
        _ZENDESK,
        True,
        "feature_request",
        _titled(
            "Scheduled PDF of dashboards",
            "It would be great to email a PDF of a dashboard to stakeholders every Monday morning.",
        ),
    ),
    _case(
        "feature_flag_approval_flow",
        _GITHUB,
        True,
        "feature_request",
        _titled(
            "Feature request: require approval before changing a production flag",
            'We\'d like a setting so that changes to flags tagged "production" need a second person to approve '
            "before they go live.",
        ),
    ),
    _case(
        "feature_survey_branching",
        _CONVERSATIONS,
        True,
        "feature_request",
        _conversation(
            "Idea",
            [("customer", "Would love conditional questions in surveys, like skip Q3 if they answered No to Q2.")],
        ),
    ),
    _case(
        "feature_warehouse_incremental_sync_key",
        _JIRA,
        True,
        "feature_request",
        _titled(
            "Allow choosing the incremental sync column",
            "Customer wants to pick which timestamp column the data warehouse uses for incremental sync instead of "
            "the auto-detected one.",
        ),
    ),
]

# --- ACTIONABLE: performance ----------------------------------------------------------------------

_PERFORMANCE = [
    _case(
        "perf_dashboard_slow_load",
        _ZENDESK,
        True,
        "performance",
        _titled(
            "Dashboard takes over a minute to load",
            "Our main dashboard with 18 insights takes 60-90 seconds to load each morning. It used to be under "
            "10 seconds.",
        ),
    ),
    _case(
        "perf_sdk_main_thread",
        _GITHUB,
        True,
        "performance",
        _titled(
            "Android SDK blocks main thread on init",
            "Profiling shows SDK setup takes ~400ms on the main thread during app start on low-end devices, mostly "
            "reading cached flags from disk.",
        ),
    ),
    _case(
        "perf_person_search_slow",
        _LINEAR,
        True,
        "performance",
        _titled(
            "Persons search slow for email substring",
            "Searching persons by part of an email takes 30s+ on projects with large person counts and often times "
            "out.",
        ),
    ),
]


ACTIONABILITY_CASES: list[ActionabilityCase] = [
    *_VAGUE,
    *_CONTRADICTORY,
    *_MANUAL_BILLING,
    *_THANKS,
    *_AUTO_REPLIES,
    *_SPAM,
    *_INTERNAL_TEST,
    *_BOTS,
    *_DUPLICATES,
    *_ANGRY_SPECIFIC,
    *_HOW_TO,
    *_WAI_CONFUSION,
    *_SELF_HOSTED,
    *_BILLING_MALFUNCTION,
    *_SHORT_SPECIFIC,
    *_BUGS,
    *_FEATURE_REQUESTS,
    *_PERFORMANCE,
]
