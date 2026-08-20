import { REPORT_CONTENT } from './mockReportContent'
import { DemoReport } from './types'

/** The report the inbox and focus surfaces treat as the flagship fix-flow demo. */
export const DEMO_REPORT_ID = 'RPT-1042'

/** Rotating activity phrases for live (still-investigating) rows. */
export const LIVE_ACTIVITY_PHRASES = [
    'querying error tracking…',
    'clustering wizard bounce paths…',
    'watching session replays…',
    'diffing the Aug 14 rework…',
    'checking the list-page URL writes…',
]

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
        state: 'worsening',
        verdict:
            'Clicking Create key computes a validation error and throws it away before render. About 340 people a day click the dead button, retry, and leave settings without a key.',
        proof: '182 session replays · 3,912 dead clicks',
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
        state: 'measuring',
        verdict: 'Investigation in progress. Completed chapters are readable as they land.',
        proof: 'Watch the storyboard assemble in the live view',
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
        status: 'New',
        unread: true,
        state: 'worsening',
        verdict:
            'Failed tiles show a generic message with no error code and no query id, and Try again re-runs a query that cannot succeed. Support cannot trace a single report about it.',
        proof: '1,708 users in one day · 6 tickets',
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
        state: 'worsening',
        verdict:
            'The banner tells people to upgrade or raise the limit, then renders that sentence as plain text. Non-admins get no button anywhere on it. People click the instruction itself, about 63 times a day.',
        proof: '1,900 dead clicks in 30 days · 4 tickets',
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
        state: 'holding',
        verdict:
            'When the insight query behind an AI answer fails, the answer renders a dead-end error card. The query log shows 9 of 10 failures succeeding on a re-run, so people are doing the retry loop by hand.',
        proof: '97 error traces · 41 replays',
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
        status: 'Viewed',
        state: 'holding',
        verdict:
            'Workspaces that gate Slack installs behind admin approval bounce the user back with a toast that assumes they clicked cancel. The denial branch captures nothing, so the funnel is blind here.',
        proof: '214 denied callbacks in 60 days',
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
        id: 'RPT-1028',
        headline: 'Stackless Firefox errors were collapsing into one giant issue',
        area: 'ERROR TRACKING',
        impact: '3,412 events',
        trend: 'down',
        impactWeight: 45,
        ageHours: 122,
        created: 'Aug 15, 08:40',
        status: 'Verifying',
        state: 'recovering',
        verdict:
            'Captures without a stack all grouped into one untriageable issue. A synthetic-stack fallback shipped 9 hours ago; grouping quality is being watched for 7 days before this resolves.',
        proof: 'stackless captures 4/hr, was ~60/hr',
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
        state: 'resolved',
        verdict:
            'Server-side flag calls that passed their own person properties could get the wrong variant because GeoIP overwrote them. Fixed: 0 wrong evaluations in 7 days, 1,930 users recovered. An epilogue was appended to the report.',
        proof: 'closing stat verified against flag calls + replays',
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
        state: 'disputed',
        verdict:
            'Marked disputed by S. Alvarez: the p75 step tracks one enterprise org with an unusually large config payload, not the settings rework. The engine is re-running the analysis with that correction.',
        proof: 'dispute registered · re-analysis queued',
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
        state: 'dismissed',
        verdict:
            'Dismissed by M. Chen: the doubled controls are cosmetic, playback is unaffected, and a general fix risks hiding controls recorded sites genuinely use. Kept for audit.',
        proof: 'dismissed with reason · ~7 affected replays/day',
        content: REPORT_CONTENT['RPT-1015'],
    },
]

/** Reports that appear in focus mode, in triage order. */
export const FOCUS_REPORTS: DemoReport[] = DEMO_REPORTS.filter((r) => r.focus)

export function getDemoReport(id: string): DemoReport | null {
    return DEMO_REPORTS.find((r) => r.id === id) ?? null
}
