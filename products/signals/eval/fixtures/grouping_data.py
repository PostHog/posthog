from products.signals.eval.data_spec import GroupSpec, SignalSpec, SourceProducts, SourceTypes

GROUP_DATA = [
    # --- Group 0: Date picker timezone bug (3 signals, mixed sources) ---
    GroupSpec(
        scenario="Date picker shows wrong dates for users in non-UTC timezones, affecting insights and dashboards",
        signals=[
            SignalSpec(
                source_product=SourceProducts.ZENDESK,
                source_type=SourceTypes.TICKET,
                style="bug",
                description=(
                    "Date picker shows wrong day in insights\n"
                    "When I select 'Last 7 days' in an insight, the date range shown is off by one day. "
                    "I'm in PST (UTC-8). The start date says Jan 14 but it should be Jan 15. "
                    "This happens on every insight — trends, funnels, retention. "
                    "If I switch my computer clock to UTC it shows the correct dates."
                ),
            ),
            SignalSpec(
                source_product=SourceProducts.GITHUB,
                source_type=SourceTypes.ISSUE,
                style="bug",
                description=(
                    "Date filter off by one day for negative UTC offsets\n"
                    "## Bug description\n"
                    "The date picker component uses `new Date()` which returns local midnight, "
                    "but the backend interprets it as UTC midnight. For users west of UTC this means "
                    "the query window shifts back by one day.\n\n"
                    "## Steps to reproduce\n"
                    "1. Set system timezone to America/Los_Angeles\n"
                    "2. Create a trends insight with 'Last 7 days'\n"
                    "3. Observe the date range in the request payload\n\n"
                    "Expected: date_from=2026-01-15, Actual: date_from=2026-01-14"
                ),
            ),
            SignalSpec(
                source_product=SourceProducts.ZENDESK,
                source_type=SourceTypes.TICKET,
                style="support",
                description=(
                    "Dashboard date range incorrect for Australian timezone\n"
                    "Our team is in AEST (UTC+10). When we set a dashboard filter to 'This month', "
                    "it includes events from the last day of the previous month. Multiple team members "
                    "have confirmed. This only started happening after the recent UI update. "
                    "The API response shows date_from is one day behind what we selected."
                ),
            ),
        ],
    ),
    # --- Group 1: Funnel conversion calculation bug (4 signals, mixed sources) ---
    GroupSpec(
        scenario="Funnel conversion rates are calculated incorrectly when using time-based breakdown bins",
        signals=[
            SignalSpec(
                source_product=SourceProducts.ZENDESK,
                source_type=SourceTypes.TICKET,
                style="bug",
                description=(
                    "Funnel conversion rates don't add up with time breakdown\n"
                    "I have a 3-step funnel and when I enable 'breakdown by day', the per-day conversion "
                    "rates don't match the overall rate. For example, each day shows ~40% conversion but "
                    "the total says 25%. We're using this for investor reporting and the numbers need to be right."
                ),
            ),
            SignalSpec(
                source_product=SourceProducts.GITHUB,
                source_type=SourceTypes.ISSUE,
                style="bug",
                description=(
                    "Incorrect funnel conversion with time-to-convert bins\n"
                    "## Description\n"
                    "When using `funnel_viz_type: time_to_convert` with custom bin sizes, the conversion "
                    "percentages are wrong. The issue is in `get_funnel_time_to_convert` — it divides by "
                    "total entering users instead of users who completed the previous step.\n\n"
                    "## Impact\n"
                    "All time-to-convert funnel visualizations show inflated drop-off rates.\n\n"
                    "## Expected\n"
                    "Each bin's percentage should be relative to users entering that step, "
                    "not the total funnel entrants."
                ),
            ),
            SignalSpec(
                source_product=SourceProducts.LINEAR,
                source_type=SourceTypes.ISSUE,
                style="bug",
                description=(
                    "Funnel time breakdown denominator bug\n"
                    "The time-binned funnel breakdown uses the wrong denominator for conversion rate "
                    "calculation. When breaking down by time period, each bin should divide conversions "
                    "by entries to that specific step, but it's dividing by total step-1 entries. "
                    "Repro: any multi-step funnel with time-to-convert viz type. Priority: high — "
                    "customer-facing numbers are wrong."
                ),
            ),
            SignalSpec(
                source_product=SourceProducts.ZENDESK,
                source_type=SourceTypes.TICKET,
                style="support",
                description=(
                    "Funnel percentages wrong when broken down by week\n"
                    "Hi, our weekly funnel breakdown shows different total conversion than the "
                    "non-broken-down version. We have signup -> activation -> purchase funnel. "
                    "Without breakdown: 32% conversion. With weekly breakdown: each week shows "
                    "45-50%. These can't both be right. Can you help us understand which is correct?"
                ),
            ),
        ],
    ),
    # --- Group 2: Feature flag evaluation slow for large orgs (2 signals, single source) ---
    GroupSpec(
        scenario="Feature flag evaluation is extremely slow for organizations with many flags and large cohorts",
        signals=[
            SignalSpec(
                source_product=SourceProducts.ZENDESK,
                source_type=SourceTypes.TICKET,
                style="support",
                description=(
                    "Feature flag API response time over 2 seconds\n"
                    "Our /decide endpoint calls are taking 2-3 seconds to respond. We have about 200 "
                    "feature flags and some use cohort-based targeting with cohorts of 500k+ users. "
                    "This is causing our app startup to be really slow. We're on the Teams plan. "
                    "Is there a way to speed this up? We've already tried local evaluation but "
                    "the initial payload download is 15MB."
                ),
            ),
            SignalSpec(
                source_product=SourceProducts.ZENDESK,
                source_type=SourceTypes.TICKET,
                style="bug",
                description=(
                    "Slow feature flag loading causing timeout errors\n"
                    "We're seeing timeout errors in our backend when evaluating feature flags. "
                    "The PostHog SDK times out after 3 seconds and we get fallback values. "
                    "This started when we added more cohort-based flags — we now have 180 flags "
                    "total, 40 of which use cohort targeting. Our cohorts range from 100k to 1M users. "
                    "Local evaluation mode downloads take over 30 seconds."
                ),
            ),
        ],
    ),
    # --- Group 3: Session replay click detection (3 signals, mixed sources) ---
    GroupSpec(
        scenario="Session replay fails to detect and highlight rage clicks and dead clicks accurately",
        signals=[
            SignalSpec(
                source_product=SourceProducts.GITHUB,
                source_type=SourceTypes.ISSUE,
                style="bug",
                description=(
                    "Rage click detection triggers on normal scrolling\n"
                    "## Problem\n"
                    "The rage click detector fires when users scroll quickly on mobile. Touch events "
                    "during momentum scrolling are being counted as clicks. This causes the 'rage click' "
                    "filter in session replay to return mostly false positives on mobile sessions.\n\n"
                    "## Suggestion\n"
                    "Filter out touch events where the delta between touchstart and touchend positions "
                    "exceeds a threshold (indicating a scroll, not a tap)."
                ),
            ),
            SignalSpec(
                source_product=SourceProducts.ZENDESK,
                source_type=SourceTypes.TICKET,
                style="bug",
                description=(
                    "Dead click detection not working on shadow DOM elements\n"
                    "We use Web Components extensively and the dead click detection doesn't work "
                    "at all for elements inside shadow DOM. The click events are captured but they're "
                    "attributed to the shadow host element, not the actual button inside. This means "
                    "we miss all dead clicks happening inside our custom components, which is most of our UI."
                ),
            ),
            SignalSpec(
                source_product=SourceProducts.LINEAR,
                source_type=SourceTypes.ISSUE,
                style="bug",
                description=(
                    "Session replay rage/dead click accuracy issues\n"
                    "Multiple reports from customers about click detection accuracy in session replay. "
                    "Two main problems: (1) mobile scroll events counted as rage clicks, inflating "
                    "the count, (2) clicks inside shadow DOM not properly attributed, causing dead "
                    "clicks to be missed. Need to fix both to make the click analysis filters reliable."
                ),
            ),
        ],
    ),
    # --- Group 4: Singleton — HogQL array function missing ---
    GroupSpec(
        scenario="HogQL is missing the arrayDistinct function that users expect from ClickHouse SQL",
        signals=[
            SignalSpec(
                source_product=SourceProducts.GITHUB,
                source_type=SourceTypes.ISSUE,
                style="feature",
                description=(
                    "Add arrayDistinct to HogQL\n"
                    "## Feature request\n"
                    "HogQL doesn't support `arrayDistinct()` which is a standard ClickHouse function. "
                    "I'm trying to get unique values from an array property and have to use a workaround "
                    "with arrayReduce('groupUniqArrayArray', ...) which is ugly and slow.\n\n"
                    "## Use case\n"
                    "We store multiple tag values in an array property and need to count distinct tags "
                    "across events. `SELECT arrayDistinct(groupArray(properties.$tags)) FROM events` "
                    "fails with 'Unknown function: arrayDistinct'."
                ),
            ),
        ],
    ),
    # --- Group 5: Export to CSV/PDF broken (3 signals, single source) ---
    GroupSpec(
        scenario="Exporting insights and dashboards to CSV and PDF produces empty or corrupted files",
        signals=[
            SignalSpec(
                source_product=SourceProducts.ZENDESK,
                source_type=SourceTypes.TICKET,
                style="bug",
                description=(
                    "CSV export from trends insight is empty\n"
                    "When I export a trends insight to CSV, the downloaded file has headers but no data rows. "
                    "This happens for all trends insights. Funnel exports work fine. "
                    "I need this for our weekly reporting — we pull data into Google Sheets via CSV."
                ),
            ),
            SignalSpec(
                source_product=SourceProducts.ZENDESK,
                source_type=SourceTypes.TICKET,
                style="bug",
                description=(
                    "Dashboard PDF export produces blank pages\n"
                    "Trying to export a dashboard as PDF. The PDF downloads but every page is blank — "
                    "no charts, no text, just empty white pages. This used to work last month. "
                    "The dashboard has 8 insights (mix of trends and tables). I've tried Chrome and Firefox, "
                    "same result."
                ),
            ),
            SignalSpec(
                source_product=SourceProducts.ZENDESK,
                source_type=SourceTypes.TICKET,
                style="support",
                description=(
                    "Cannot export insight data — CSV file is corrupted\n"
                    "I'm trying to download my retention insight as CSV but the file is garbled. "
                    "Opening in Excel shows encoding errors and the columns are all shifted. "
                    "Other export formats (like the image export) work but I specifically need the raw data. "
                    "Using PostHog Cloud, latest Chrome on Mac."
                ),
            ),
        ],
    ),
    # --- Group 6: Singleton — webhook delivery unreliable ---
    GroupSpec(
        scenario="Action-triggered webhooks are not firing reliably, with deliveries silently dropped",
        signals=[
            SignalSpec(
                source_product=SourceProducts.ZENDESK,
                source_type=SourceTypes.TICKET,
                style="bug",
                description=(
                    "Webhooks not firing for action triggers\n"
                    "We have an action set up to trigger a webhook to our Slack when a user completes "
                    "onboarding. It worked for about a week and then stopped. No errors in the PostHog UI, "
                    "the action still shows as active, but our Slack endpoint receives nothing. "
                    "We verified our endpoint works with curl. Other actions (non-webhook) fire correctly. "
                    "This is blocking our customer success workflow."
                ),
            ),
        ],
    ),
    # --- Group 7: Cohort calculation stuck/stale (3 signals, mixed sources) ---
    GroupSpec(
        scenario="Dynamic cohorts get stuck in 'calculating' state and never finish updating",
        signals=[
            SignalSpec(
                source_product=SourceProducts.ZENDESK,
                source_type=SourceTypes.TICKET,
                style="bug",
                description=(
                    "Cohort stuck on 'calculating' for 3 days\n"
                    "I created a behavioral cohort of users who performed 'purchase' event in the last 30 days. "
                    "It's been showing 'Calculating...' for 3 days now. I tried duplicating and deleting the "
                    "original — the new one also gets stuck. We need this cohort for a feature flag rollout "
                    "and we're blocked."
                ),
            ),
            SignalSpec(
                source_product=SourceProducts.GITHUB,
                source_type=SourceTypes.ISSUE,
                style="bug",
                description=(
                    "Dynamic cohorts never finish recalculating\n"
                    "## Bug\n"
                    "Several dynamic cohorts in our project are permanently stuck in 'calculating' state. "
                    "These are cohorts with behavioral filters (performed event X in last N days). "
                    "Static cohorts work fine. The issue seems related to cohort size — our smaller cohorts "
                    "(<10k users) calculate fine, but larger ones (50k+) never complete.\n\n"
                    "## Environment\n"
                    "Self-hosted, PostHog 1.43.0, Kubernetes deployment with 3 worker pods."
                ),
            ),
            SignalSpec(
                source_product=SourceProducts.ZENDESK,
                source_type=SourceTypes.TICKET,
                style="support",
                description=(
                    "Feature flag using stale cohort data\n"
                    "Our feature flag targets a dynamic cohort but the cohort hasn't updated in 5 days. "
                    "The cohort page just shows 'Calculating' with a spinner. This means our flag is "
                    "targeting based on week-old data. New users who should be in the cohort aren't getting "
                    "the feature. Is there a way to force recalculation?"
                ),
            ),
        ],
    ),
    # --- Group 8: Singleton — group analytics property filter broken ---
    GroupSpec(
        scenario="Filtering by group properties in insights returns no results even when data exists",
        signals=[
            SignalSpec(
                source_product=SourceProducts.LINEAR,
                source_type=SourceTypes.ISSUE,
                style="bug",
                description=(
                    "Group analytics property filter returns empty results\n"
                    "When adding a filter on group properties (e.g. company.plan = 'enterprise') to a "
                    "trends insight, the query returns 0 results even though we have events with those "
                    "group properties set. The same filter works correctly in the persons & groups page. "
                    "Suspected issue: the property filter is being applied as a person property filter "
                    "instead of a group property filter in the HogQL query generation."
                ),
            ),
        ],
    ),
    # --- Group 9: Data warehouse sync failures (2 signals, mixed sources) ---
    GroupSpec(
        scenario="Data warehouse Stripe source sync fails with permission errors after initial setup",
        signals=[
            SignalSpec(
                source_product=SourceProducts.ZENDESK,
                source_type=SourceTypes.TICKET,
                style="bug",
                description=(
                    "Stripe data warehouse sync failing after first successful sync\n"
                    "We set up the Stripe data warehouse source and the first sync completed fine. "
                    "But every sync since then fails with 'Permission denied: insufficient_permissions'. "
                    "Nothing changed on our Stripe end — same API key, same permissions. "
                    "The error happens about 2 minutes into the sync, always on the invoices table. "
                    "Charges and customers tables sync fine."
                ),
            ),
            SignalSpec(
                source_product=SourceProducts.GITHUB,
                source_type=SourceTypes.ISSUE,
                style="bug",
                description=(
                    "Data warehouse Stripe sync permission error on incremental sync\n"
                    "## Problem\n"
                    "After a successful initial full sync, subsequent incremental syncs for the Stripe "
                    "source fail with a permission error. The error only affects tables that use cursor-based "
                    "pagination (invoices, subscriptions). Tables using simple offset pagination work.\n\n"
                    "## Investigation\n"
                    "The incremental sync passes `starting_after` parameter which requires "
                    "`read` scope on the specific object. The API key has `read` scope but the "
                    "cursor value from the previous sync might be expired or invalid."
                ),
            ),
        ],
    ),
]
