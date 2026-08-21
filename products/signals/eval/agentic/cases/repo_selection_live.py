"""Live repository-selection cases.

In live mode the candidate list comes from the team's actual GitHub integration (not the
case), and the agent queries the real repository cache via ``execute-sql``. These cases use
unambiguous, recognizable repositories from that integration so the expected pick is clear.
Swap the expected full names if your local integration differs (list eligible repos with
``Integration.repository_cache_entries``).
"""

from __future__ import annotations

from products.signals.eval.agentic.datasets import RepoSelectionCase, RepoSelectionExpectation, SignalSpec
from products.signals.eval.agentic.scorers_repo_selection import default_repo_selection_scorers

CASES: list[RepoSelectionCase] = [
    RepoSelectionCase(
        case_id="reposel_live_feedback_board",
        step="repo_selection",
        notes="Product-feedback board → fider (open platform to collect/prioritize feedback).",
        signals=(
            SignalSpec(
                signal_id="sig_fider",
                content=(
                    "On our public feature-request board, customers submit ideas and upvote them, but the "
                    "upvote count double-counts when a user votes, navigates away, and returns."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(expected_repository="joshsny/fider"),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_siwe_starter",
        step="repo_selection",
        notes="Sign-In With Ethereum on the Next.js starter → next-ethereum.",
        signals=(
            SignalSpec(
                signal_id="sig_siwe",
                content=(
                    "The Sign-In With Ethereum flow in our Next.js starter throws 'nonce mismatch' on wallet "
                    "connect after upgrading the wallet library."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(expected_repository="joshsny/next-ethereum"),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_support_inbox",
        step="repo_selection",
        notes="Open-source customer support inbox (Intercom alternative) → chatwoot.",
        signals=(
            SignalSpec(
                signal_id="sig_chatwoot",
                content=(
                    "Our self-hosted open-source customer support inbox (the Intercom/Zendesk alternative) drops "
                    "incoming conversations when an agent is assigned during a reply."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(expected_repository="joshsny/chatwoot"),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_timenavi_webapp",
        step="repo_selection",
        notes="Named product (TimeNavi) — two TimeNavi repos exist (webapp + schedule), both defensible.",
        signals=(
            SignalSpec(
                signal_id="sig_timenavi",
                content=(
                    "In the TimeNavi web app, the calendar view fails to render recurring events after a "
                    "Google Calendar sync; the React component throws on the recurrence rule."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(
            expected_repository=("joshsny/webapp", "joshsny/timenavi-schedule"),
        ),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_billing_null",
        step="repo_selection",
        notes="Pure billing/refund ops request — no candidate repo owns it; correct answer is null.",
        context=(
            "A customer disputes last month's invoice and wants a prorated refund plus the dispute escalated "
            "to their account manager. They are not reporting any product bug."
        ),
        candidate_repos=(),
        expected=RepoSelectionExpectation(expect_null=True),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_scheduling_tool",
        step="repo_selection",
        notes="Open-source scheduling-link tool (Calendly alternative) described by function → calendso.",
        signals=(
            SignalSpec(
                signal_id="sig_calendso",
                content=(
                    "In our open-source booking-link scheduler (the Calendly alternative), an invitee in a "
                    "different timezone who books the host's last slot of the day gets the event created an "
                    "hour off, which double-books the host."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(expected_repository="joshsny/calendso"),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_ses_email_backend",
        step="repo_selection",
        notes="Django email backend for Amazon SES described by function → django-ses.",
        signals=(
            SignalSpec(
                signal_id="sig_django_ses",
                content=(
                    "Our Django app sends transactional email through Amazon SES; the email backend raises a "
                    "ClientError whenever a recipient display name contains non-ASCII characters, and SES "
                    "bounce notifications are no longer marked against the message."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(expected_repository="joshsny/django-ses"),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_wallet_extension",
        step="repo_selection",
        notes="Crypto-wallet browser extension described by symptom → metamask-extension.",
        signals=(
            SignalSpec(
                signal_id="sig_wallet_ext",
                content=(
                    "In our crypto wallet browser extension, the transaction confirmation popup renders blank "
                    "when a dapp requests a signature while the extension is locked; users report having to "
                    "reinstall the extension to recover."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(expected_repository="joshsny/metamask-extension"),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_android_launcher",
        step="repo_selection",
        notes="Minimal open-source Android launcher described by function → mindfullauncher.",
        signals=(
            SignalSpec(
                signal_id="sig_launcher",
                content=(
                    "On our lightweight open-source Android launcher, the app-list search returns no results "
                    "for freshly installed apps until the phone is rebooted; the index seems not to refresh "
                    "on package-added events."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(expected_repository="joshsny/mindfullauncher"),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_mcp_filesystem_server",
        step="repo_selection",
        notes="Bug in a reference MCP server implementation → servers (not the awesome-mcp-servers link list).",
        signals=(
            SignalSpec(
                signal_id="sig_mcp_fs",
                content=(
                    "The filesystem server in our collection of reference Model Context Protocol server "
                    "implementations rejects valid relative paths inside an allowed directory with 'path "
                    "outside allowed directories' after the path-normalization change."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(expected_repository="joshsny/servers"),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_stripe_checkout_starter",
        step="repo_selection",
        notes="Next.js + Stripe starter checkout/webhook bug → nextjs-stripe-starter.",
        signals=(
            SignalSpec(
                signal_id="sig_stripe_starter",
                content=(
                    "In our Next.js + Stripe starter, checkout completes and redirects to the success page, "
                    "but the webhook handler fails Stripe signature verification so the order is never "
                    "marked as paid."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(expected_repository="joshsny/nextjs-stripe-starter"),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_favicon_finder",
        step="repo_selection",
        notes="Domain → logo/favicon lookup service described by function → faviconic.",
        signals=(
            SignalSpec(
                signal_id="sig_faviconic",
                content=(
                    "Our zero-dependency service that finds a website's logo from just its domain returns "
                    "nothing for sites that only declare an SVG favicon via a link tag instead of shipping "
                    "/favicon.ico."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(expected_repository="joshsny/faviconic"),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_web_share_fallback",
        step="repo_selection",
        notes="Tiny web-share wrapper with fallback for unsupported browsers → react-web-share.",
        signals=(
            SignalSpec(
                signal_id="sig_web_share",
                content=(
                    "Our tiny share-button wrapper component is supposed to fall back to a custom share "
                    "modal in browsers without the native share API, but on desktop Firefox clicking share "
                    "does nothing — no modal, no error."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(expected_repository="joshsny/react-web-share"),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_gcal_python_wrapper",
        step="repo_selection",
        notes="Pythonic Google Calendar API wrapper library (not the autoplan app built on it) → google-calendar-simple-api.",
        signals=(
            SignalSpec(
                signal_id="sig_gcal_wrapper",
                content=(
                    "Our Pythonic wrapper library around the Google Calendar API silently drops the "
                    "recurrence rule when serializing an event that also sets reminders, so recurring "
                    "events created through the library come out as one-offs."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(expected_repository="joshsny/google-calendar-simple-api"),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_nextjs_boilerplate_cluster",
        step="repo_selection",
        notes="Generic Next.js starter boilerplate — several boilerplate repos exist, any is defensible.",
        signals=(
            SignalSpec(
                signal_id="sig_next_boilerplate",
                content=(
                    "Fresh projects generated from our general-purpose Next.js starter boilerplate fail "
                    "'next build' out of the box: the PostCSS config the template ships still references "
                    "the pre-Tailwind-4 plugin name."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(
            expected_repository=(
                "joshsny/next-auth-boilerplate",
                "joshsny/next-js-boilerplate",
                "joshsny/nextjs-boilerplate",
                "joshsny/nextjs-template",
            ),
        ),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_llm_framework_pair",
        step="repo_selection",
        notes="LLM composability framework bug, language unstated — Python and JS ports both defensible.",
        signals=(
            SignalSpec(
                signal_id="sig_llm_framework",
                content=(
                    "In our framework for building LLM applications through composable chains, partial "
                    "variables set on a prompt template are silently dropped when that template is composed "
                    "into a sequential chain, so downstream steps see unresolved placeholders."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(
            expected_repository=("joshsny/langchain", "joshsny/langchainjs"),
        ),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_analytics_backend_pair",
        step="repo_selection",
        notes="Home-grown analytics backend, unnamed — the rust analytics backend and pilgrim are both defensible.",
        signals=(
            SignalSpec(
                signal_id="sig_analytics_backend",
                content=(
                    "Our home-grown analytics backend loses events under burst traffic: the ingestion "
                    "endpoint accepts the batch with a 200 but the counts never appear in the stored "
                    "aggregates."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(
            expected_repository=("joshsny/analytics", "joshsny/pilgrim"),
        ),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_hr_onboarding_null",
        step="repo_selection",
        notes="Internal HR/IT provisioning request — no candidate repo owns it; correct answer is null.",
        context=(
            "A manager asks for a laptop, badge, and shared-drive access to be provisioned for a new hire "
            "starting next Monday, and wants IT to expedite the accounts. No product issue is reported."
        ),
        candidate_repos=(),
        expected=RepoSelectionExpectation(expect_null=True),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_legal_dpa_null",
        step="repo_selection",
        notes="Legal/procurement paperwork request — no candidate repo owns it; correct answer is null.",
        context=(
            "A prospect's procurement team requests a countersigned DPA, the latest SOC 2 Type II report, "
            "and a completed security questionnaire before their Friday review. They are not reporting any "
            "product bug or feature gap."
        ),
        candidate_repos=(),
        expected=RepoSelectionExpectation(expect_null=True),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_ios_app_null",
        step="repo_selection",
        notes="Adversarial: plausible product (native iOS app) that no repo in the inventory owns — must not force a match.",
        signals=(
            SignalSpec(
                signal_id="sig_ios_crash",
                content=(
                    "Our iOS companion app crashes on launch for everyone on iOS 19 — the crash log points "
                    "at the Swift widget extension — and App Store reviews are tanking."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(expect_null=True),
        scorers=default_repo_selection_scorers(),
    ),
    RepoSelectionCase(
        case_id="reposel_live_posthog_setup_bait",
        step="repo_selection",
        notes="Adversarial: names PostHog, but the symptom is in the automated setup tool (githog), not the posthog repo.",
        signals=(
            SignalSpec(
                signal_id="sig_setup_tool",
                content=(
                    "Our automated setup tool that installs and configures PostHog in a user's project for "
                    "them fails halfway: it detects the framework correctly, then errors while injecting "
                    "the config snippet, leaving the project half-configured."
                ),
            ),
        ),
        expected=RepoSelectionExpectation(expected_repository="joshsny/githog"),
        scorers=default_repo_selection_scorers(),
    ),
]
