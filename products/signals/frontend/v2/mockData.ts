import { REPORT_CONTENT } from './mockReportContent'
import { DemoReport, DemoScout, DemoToggleRow } from './types'

/** The report the inbox and focus surfaces treat as the flagship fix-flow demo. */
export const DEMO_REPORT_ID = 'RPT-1042'

export const DEMO_REPORTS: DemoReport[] = [
    {
        id: 'RPT-1042',
        headline: 'Creating an API key does nothing when validation fails',
        area: 'SETTINGS · AUTH',
        impact: '1,410 users',
        trend: 'up',
        impactWeight: 100,
        ageHours: 28,
        created: 'Aug 19, 07:42',
        status: 'New',
        unread: true,
        forYou: true,
        verdict:
            'Clicking Create key computes a validation error and throws it away before render. About 340 people a day click the dead button, retry, and leave settings without a key.',
        proof: '182 session replays · 3,912 dead clicks',
        sparkline: [12, 18, 25, 34, 52, 71, 100],
        sources: ['Autocapture', 'Session replay', 'GitHub'],
        content: REPORT_CONTENT['RPT-1042'],
        focus: {
            age: 'detected 28h ago',
            trendLabel: 'growing ~60/hr',
            actionLabel: 'Fix & monitor',
            flagKey: 'api-key-error-surfacing',
            fixToast: 'Fix PR opening: fix/rpt-1042-api-key-errors · monitoring armed',
            story: [
                {
                    label: 'PROBLEM',
                    body: 'When the key form fails validation, the click handler returns before the error state reaches the form. Nothing renders, the button stays enabled, and the only path forward is retrying the same dead click. Started 17 minutes after deploy f3a1c72 (Aug 19, 07:41).',
                },
                {
                    label: 'IMPACT',
                    body: '1,410 people in 28 hours, 3,912 dead clicks, key creation completion down 71% to 34%. These are people mid-setup wiring an SDK or a CI job, so each failure stalls an integration.',
                },
                {
                    label: 'HOW WE KNOW',
                    body: 'First dead-click cluster 17 minutes post-deploy; the diff moves the early return above the line that stores the error. All 182 matching replays show submit, no change, retry. Zero exceptions captured, because the failure is silent by construction.',
                },
                {
                    label: 'FIX · +6 LINES',
                    body: 'Store the form errors before the early return so the existing error rendering works again, and wire the in-flight state into the button. Behind flag api-key-error-surfacing.',
                    code: '   const errors = validateKeyForm(values)\n-  if (Object.keys(errors).length > 0) {\n-      return\n-  }\n   setFormErrors(errors)\n   if (Object.keys(errors).length > 0) {\n       return\n   }',
                },
            ],
        },
    },
    {
        id: 'RPT-1044',
        headline: 'Scanner setup wizard keeps bouncing people back to the list',
        area: 'REPLAY VISION',
        impact: '41% bounce',
        trend: 'flat',
        impactWeight: 55,
        ageHours: 0.5,
        created: 'Aug 20, 09:48',
        status: 'Investigating',
        live: true,
        verdict: 'Investigation in progress. Completed chapters are readable as they land.',
        proof: 'Watch the storyboard assemble in the live view',
        sparkline: [20, 22, 20, 24, 60, 58, 62],
        sources: ['Product analytics', 'Session replay'],
        content: REPORT_CONTENT['RPT-1044'],
    },
    {
        id: 'RPT-1031',
        headline: 'Failed dashboard tiles give viewers nothing to act on',
        area: 'DASHBOARDS',
        impact: '1,708 users',
        trend: 'up',
        impactWeight: 85,
        ageHours: 12,
        created: 'Aug 19, 22:31',
        forYou: true,
        status: 'New',
        unread: true,
        verdict:
            'Failed tiles show a generic message with no error code and no query id, and Try again re-runs a query that cannot succeed. Support cannot trace a single report about it.',
        proof: '1,708 users in one day · 6 tickets',
        sparkline: [8, 10, 14, 30, 52, 80, 100],
        sources: ['Product analytics', 'Support tickets'],
        content: REPORT_CONTENT['RPT-1031'],
        focus: {
            age: 'detected 12h ago',
            trendLabel: 'growing ~80/hr',
            actionLabel: 'Fix & monitor',
            flagKey: 'tile-error-details',
            fixToast: 'Fix PR opening: fix/rpt-1031-tile-error-details · monitoring armed',
            story: [
                {
                    label: 'PROBLEM',
                    body: 'Failed tiles say there was a problem completing the query and stop there. No error code, no query id. Try again re-runs the identical query with identical inputs, so deterministic failures fail identically, and the viewer cannot know that.',
                },
                {
                    label: 'IMPACT',
                    body: '1,708 people saw a failed tile in one day, concentrated on shared dashboards where the viewer cannot debug the query. All 6 tickets about it are dead ends, because there is nothing to search for.',
                },
                {
                    label: 'FIX',
                    body: 'Render the short error code and query id on the tile, and disable Try again with a reason when the failure is deterministic. One search then resolves any future ticket.',
                },
            ],
        },
    },
    {
        id: 'RPT-1039',
        headline: 'Usage limit banner asks for an action it does not offer',
        area: 'BILLING',
        impact: '612 users',
        trend: 'up',
        impactWeight: 70,
        ageHours: 47,
        created: 'Aug 18, 11:05',
        status: 'Assigned',
        forYou: true,
        verdict:
            'The banner tells people to upgrade or raise the limit, then renders that sentence as plain text. Non-admins get no button anywhere on it. People click the instruction itself, about 63 times a day.',
        proof: '1,900 dead clicks in 30 days · 4 tickets',
        sparkline: [40, 44, 48, 55, 60, 66, 72],
        sources: ['Autocapture', 'Support tickets'],
        content: REPORT_CONTENT['RPT-1039'],
        focus: {
            age: 'detected 2d ago',
            trendLabel: 'growing slowly',
            actionLabel: 'Fix & monitor',
            flagKey: 'usage-banner-actionable',
            fixToast: 'Fix PR opening: fix/rpt-1039-usage-banner-link · monitoring armed',
            story: [
                {
                    label: 'PROBLEM',
                    body: 'The usage limit banner renders its call to action as plain text. Admins get a button beside it; non-admins get nothing clickable at all. These are people trying to pay us or stop losing data, at the exact moment the product asks them to act.',
                },
                {
                    label: 'IMPACT',
                    body: '612 people and 1,900 dead clicks in 30 days, split across the admin and non-admin banner variants. Two of the four tickets came from orgs where data loss had already started.',
                },
                {
                    label: 'FIX',
                    body: 'Link the action phrase to billing for anyone with access. Give non-admins a one-click way to notify an org admin instead of a sentence about a page they cannot open.',
                },
            ],
        },
    },
    {
        id: 'RPT-1037',
        headline: 'AI chart answers show a red error instead of retrying',
        area: 'POSTHOG AI',
        impact: '184 users/wk',
        trend: 'flat',
        impactWeight: 60,
        ageHours: 67,
        created: 'Aug 17, 15:20',
        status: 'Viewed',
        forYou: true,
        verdict:
            'When the insight query behind an AI answer fails, the answer renders a dead-end error card. The query log shows 9 of 10 failures succeeding on a re-run, so people are doing the retry loop by hand.',
        proof: '97 error traces · 41 replays',
        sparkline: [40, 42, 38, 40, 41, 39, 40],
        sources: ['Error tracking', 'Session replay'],
        content: REPORT_CONTENT['RPT-1037'],
        focus: {
            age: 'detected 3d ago',
            trendLabel: 'stable ~4/hr',
            actionLabel: 'Fix & monitor',
            flagKey: 'ai-answer-query-retry',
            fixToast: 'Fix PR opening: fix/rpt-1037-ai-chart-retry · monitoring armed',
            story: [
                {
                    label: 'PROBLEM',
                    body: 'An AI answer whose insight query fails renders a red error card where the chart should be, with no retry. Most failures are timeouts or transient locks that recover within a minute.',
                },
                {
                    label: 'IMPACT',
                    body: '184 people a week see the error card. Replays show them rephrasing the question to force a re-run, which usually works: a human doing what the client could do itself.',
                },
                {
                    label: 'FIX',
                    body: 'Retry recoverable failures once with backoff before showing the card, and put a Run again button on the card for the rest.',
                },
            ],
        },
    },
    {
        id: 'RPT-1035',
        headline: 'A failed Slack connect looks like the user changed their mind',
        area: 'INTEGRATIONS',
        impact: '88 users',
        trend: 'flat',
        impactWeight: 40,
        ageHours: 73,
        created: 'Aug 17, 09:12',
        forYou: true,
        status: 'Viewed',
        verdict:
            'Workspaces that gate Slack installs behind admin approval bounce the user back with a toast that assumes they clicked cancel. The denial branch captures nothing, so the funnel is blind here.',
        proof: '214 denied callbacks in 60 days',
        sparkline: [30, 31, 30, 32, 31, 30, 31],
        sources: ['Logs', 'Product analytics'],
        content: REPORT_CONTENT['RPT-1035'],
        focus: {
            age: 'detected 3d ago',
            trendLabel: 'stable',
            actionLabel: 'Fix & monitor',
            flagKey: 'slack-connect-denial-path',
            fixToast: 'Fix PR opening: fix/rpt-1035-slack-denial-path · monitoring armed',
            story: [
                {
                    label: 'PROBLEM',
                    body: 'Slack returns access_denied both for a real cancel and for approval-gated workspaces. Our callback treats every denial as a cancel: transient toast, redirect to the starting page, nothing captured, no mention that requesting admin approval is the actual next step.',
                },
                {
                    label: 'IMPACT',
                    body: '88 people bounced across 214 denied callbacks in 60 days. Connect completion for approval-gated workspaces is near zero while other workspaces complete normally.',
                },
                {
                    label: 'FIX',
                    body: 'Explain the admin-approval path in the failure copy, capture an event on every failure branch, and keep the user on a page that says what happens next.',
                },
            ],
        },
    },
    {
        id: 'RPT-1046',
        headline: 'Saved insights open with the wrong date range after a refresh',
        area: 'PRODUCT ANALYTICS',
        impact: '932 users',
        trend: 'up',
        impactWeight: 65,
        ageHours: 9,
        created: 'Aug 20, 01:14',
        status: 'New',
        unread: true,
        forYou: true,
        verdict:
            'Insights saved with a relative date range reload with the absolute dates from the day they were saved. People re-pick the range on almost every open, and 1 in 5 give up before the query finishes.',
        proof: '2,140 range re-picks · 38 replays',
        sparkline: [10, 14, 22, 31, 48, 70, 100],
        sources: ['Product analytics', 'Session replay'],
        content: REPORT_CONTENT['RPT-1046'],
    },
    {
        id: 'RPT-1045',
        headline: 'Survey thank-you step shows for people who skipped every question',
        area: 'SURVEYS',
        impact: '510 users',
        trend: 'flat',
        impactWeight: 35,
        ageHours: 31,
        created: 'Aug 19, 03:51',
        forYou: true,
        status: 'Viewed',
        verdict:
            'Dismissing a multi-question survey from the last step still fires the completion event and the thank-you screen. Response rates read 12 points higher than the answers support.',
        proof: '1,380 empty completions in 14 days',
        sparkline: [40, 42, 44, 41, 43, 45, 44],
        sources: ['Surveys', 'Product analytics'],
        content: REPORT_CONTENT['RPT-1045'],
    },
    {
        id: 'RPT-1043',
        headline: 'Cohort edits save silently when a property filter has no value',
        area: 'COHORTS',
        impact: '146 users',
        trend: 'up',
        impactWeight: 30,
        ageHours: 54,
        created: 'Aug 18, 04:30',
        forYou: true,
        status: 'New',
        unread: true,
        verdict:
            'An empty property filter passes validation and saves as a condition that matches nobody. The cohort shows 0 people with no explanation, and most people rebuild it from scratch.',
        proof: '146 affected cohorts · 19 support tickets',
        sparkline: [5, 8, 12, 15, 21, 28, 36],
        sources: ['Support tickets', 'Product analytics'],
        content: REPORT_CONTENT['RPT-1043'],
    },
    {
        id: 'RPT-1028',
        headline: 'Stackless Firefox errors were collapsing into one giant issue',
        area: 'ERROR TRACKING',
        impact: '3,412 events',
        trend: 'down',
        impactWeight: 45,
        ageHours: 122,
        created: 'Aug 15, 08:40',
        status: 'Verifying',
        forYou: true,
        verdict:
            'Captures without a stack all grouped into one untriageable issue. A synthetic-stack fallback shipped 9 hours ago; grouping quality is being watched for 7 days before this resolves.',
        proof: 'stackless captures 4/hr, was ~60/hr',
        sparkline: [70, 80, 74, 60, 30, 10, 4],
        sources: ['Error tracking'],
        content: REPORT_CONTENT['RPT-1028'],
        focus: {
            age: 'fix shipped 9h ago',
            trendLabel: 'declining',
            actionLabel: 'View verification',
            fixToast: 'Verification dashboard opened: 7-day watch, day 1 of 7',
            story: [
                {
                    label: 'WHAT HAPPENED',
                    body: 'Firefox reports network failures without a stack, and grouping needs one. Everything stackless collapsed into a single issue mixing dozens of unrelated pages, drowning real regressions in noise.',
                },
                {
                    label: 'FIX SHIPPED',
                    body: 'Captures without a stack now get one synthesized from the capture site before grouping. Shipped 9 hours ago behind synthetic-stack-fallback.',
                },
                {
                    label: 'VERIFICATION PLAN',
                    body: 'Watching for 7 days. Pass criteria: stackless captures under 5 per hour and no regrouping churn on existing issues. A resolution epilogue is appended automatically if it holds.',
                },
            ],
        },
    },
    {
        id: 'RPT-1019',
        headline: 'GeoIP overwrote person properties sent by server SDKs',
        area: 'FEATURE FLAGS',
        impact: '0 in 7 days',
        trend: 'down',
        impactWeight: 20,
        ageHours: 270,
        created: 'Aug 9, 06:20',
        status: 'Resolved',
        forYou: true,
        verdict:
            'Server-side flag calls that passed their own person properties could get the wrong variant because GeoIP overwrote them. Fixed: 0 wrong evaluations in 7 days, 1,930 users recovered. An epilogue was appended to the report.',
        proof: 'closing stat verified against flag calls + replays',
        sparkline: [60, 45, 20, 5, 0, 0, 0],
        sources: ['Feature flags', 'Session replay'],
        content: REPORT_CONTENT['RPT-1019'],
    },
    {
        id: 'RPT-1023',
        headline: 'Project settings load-time step pinned on the wrong cause',
        area: 'WEB PERF',
        impact: 'disputed',
        trend: 'flat',
        impactWeight: 15,
        ageHours: 96,
        created: 'Aug 16, 10:12',
        status: 'Disputed',
        verdict:
            'Marked disputed by J. Doe: the p75 step tracks one enterprise org with an unusually large config payload, not the settings rework. The engine is re-running the analysis with that correction.',
        proof: 'dispute registered · re-analysis queued',
        sparkline: [20, 20, 20, 80, 20, 20, 22],
        sources: ['Web vitals'],
        content: REPORT_CONTENT['RPT-1023'],
    },
    {
        id: 'RPT-1015',
        headline: "Replays show Chrome's video controls over custom players",
        area: 'SESSION REPLAY',
        impact: '0 blocked',
        trend: 'flat',
        impactWeight: 10,
        ageHours: 175,
        created: 'Aug 13, 04:33',
        status: 'Dismissed',
        verdict:
            'Dismissed by A. Roe: the doubled controls are cosmetic, playback is unaffected, and a general fix risks hiding controls recorded sites genuinely use. Kept for audit.',
        proof: 'dismissed with reason · ~7 affected replays/day',
        sparkline: [50, 50, 52, 48, 50, 51, 50],
        sources: ['Session replay'],
        content: REPORT_CONTENT['RPT-1015'],
    },
]

/** Reports that appear in focus mode, in triage order. */
export const FOCUS_REPORTS: DemoReport[] = DEMO_REPORTS.filter((r) => r.focus)

export function getDemoReport(id: string): DemoReport | null {
    return DEMO_REPORTS.find((r) => r.id === id) ?? null
}

export const DEMO_SCOUTS: DemoScout[] = [
    {
        id: 'dead-clicks',
        name: 'Dead clicks scout',
        watches: 'Watches autocapture for dead and rage clicks on interactive elements.',
        cadence: 'every 30m',
        lastRun: '14m ago',
        openReports: 2,
        enabled: true,
    },
    {
        id: 'replay-vision',
        name: 'Replay vision scout',
        watches: 'Watches new session replays for broken flows and confused navigation.',
        cadence: 'every hour',
        lastRun: '22m ago',
        openReports: 1,
        enabled: true,
    },
    {
        id: 'error-tracking',
        name: 'Error tracking scout',
        watches: 'Clusters new exceptions and flags grouping problems.',
        cadence: 'every 15m',
        lastRun: '6m ago',
        openReports: 1,
        enabled: true,
    },
    {
        id: 'support',
        name: 'Support scout',
        watches: 'Reads support tickets for friction the product caused.',
        cadence: 'every 6h',
        lastRun: '3h ago',
        openReports: 2,
        enabled: true,
    },
    {
        id: 'web-vitals',
        name: 'Web vitals scout',
        watches: 'Watches page performance for regressions after deploys.',
        cadence: 'every hour',
        lastRun: '41m ago',
        openReports: 1,
        enabled: true,
    },
    {
        id: 'release',
        name: 'Release scout',
        watches: 'Compares each deploy against behavior changes in the hours after it.',
        cadence: 'on every deploy',
        lastRun: '1h ago',
        openReports: 0,
        enabled: true,
    },
    {
        id: 'surveys',
        name: 'Survey scout',
        watches: 'Reads open-ended survey answers for recurring complaints.',
        cadence: 'daily',
        lastRun: '2d ago',
        openReports: 0,
        enabled: false,
    },
]

/** Areas the demo user owns by default; the "For you" scope only shows reports from these. */
export const DEFAULT_ASSIGNED_PRODUCTS: string[] = Array.from(
    new Set(DEMO_REPORTS.filter((report) => report.forYou).map((report) => report.area))
)

/** Areas the GitHub app would attribute to the demo user from recent diffs. */
export const GITHUB_DETECTED_PRODUCTS: string[] = ['BILLING', 'FEATURE FLAGS', 'SETTINGS · AUTH']

export const FOR_YOU_SETTINGS: DemoToggleRow[] = [
    {
        key: 'for-you:github-auto-detect',
        label: 'Detect products from GitHub',
        detail: 'Assigns products based on the code you change in pull requests',
        enabled: true,
    },
]

export const SIGNAL_SOURCE_SETTINGS: DemoToggleRow[] = [
    {
        key: 'source:product-analytics',
        label: 'Product analytics',
        detail: 'Events, funnels, and trends',
        enabled: true,
    },
    { key: 'source:session-replay', label: 'Session replay', detail: 'Recordings of real sessions', enabled: true },
    { key: 'source:autocapture', label: 'Autocapture', detail: 'Clicks, dead clicks, and rage clicks', enabled: true },
    { key: 'source:error-tracking', label: 'Error tracking', detail: 'Exceptions and issues', enabled: true },
    {
        key: 'source:support-tickets',
        label: 'Support tickets',
        detail: 'Conversations from the support inbox',
        enabled: true,
    },
    { key: 'source:logs', label: 'Logs', detail: 'Server and edge logs', enabled: true },
    { key: 'source:web-vitals', label: 'Web vitals', detail: 'Page performance metrics', enabled: true },
    { key: 'source:surveys', label: 'Surveys', detail: 'Open-ended survey answers', enabled: false },
]

export const PR_GENERATION_SETTINGS: DemoToggleRow[] = [
    {
        key: 'pr:autostart',
        label: 'Generate fix PRs automatically',
        detail: 'Open a draft PR as soon as a fix plan is ready',
        enabled: true,
    },
    {
        key: 'pr:require-review',
        label: 'Hold PRs as drafts until a person approves',
        detail: 'Nothing merges without a human review',
        enabled: true,
    },
    {
        key: 'pr:launch-behind-flag',
        label: 'Launch every fix behind a feature flag',
        detail: 'A failing monitor reverts the flag automatically',
        enabled: true,
    },
]

export const CODE_ACCESS_SETTINGS: DemoToggleRow[] = [
    {
        key: 'code:fix-branches-only',
        label: 'Limit writes to fix branches',
        detail: 'The agent can only push to branches prefixed with fix/',
        enabled: true,
    },
]

export const NOTIFICATION_SETTINGS: DemoToggleRow[] = [
    { key: 'notify:slack', label: 'Send new reports to Slack', detail: '#signals-feed', enabled: true },
    {
        key: 'notify:digest',
        label: 'Weekly email digest',
        detail: 'A summary of new and resolved reports every Monday',
        enabled: true,
    },
    {
        key: 'notify:worsening',
        label: 'Alert on worsening reports',
        detail: 'Ping the on-call channel when impact keeps growing',
        enabled: false,
    },
]

export const USAGE_STATS: { label: string; value: string }[] = [
    { label: 'Reports generated', value: '14' },
    { label: 'Fix PRs opened', value: '6' },
    { label: 'Reports resolved', value: '4' },
    { label: 'Scout runs', value: '1,240' },
]

/** Initial state for every demo toggle, keyed the way the settings and scouts tabs read them. */
export const DEFAULT_DEMO_TOGGLES: Record<string, boolean> = Object.fromEntries([
    ...DEMO_SCOUTS.map((scout): [string, boolean] => [`scout:${scout.id}`, scout.enabled]),
    ...[
        ...FOR_YOU_SETTINGS,
        ...SIGNAL_SOURCE_SETTINGS,
        ...PR_GENERATION_SETTINGS,
        ...CODE_ACCESS_SETTINGS,
        ...NOTIFICATION_SETTINGS,
    ].map((row): [string, boolean] => [row.key, row.enabled]),
])
