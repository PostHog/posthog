import { MCP_VIA, POSTHOG_AGENT } from '@/model/agent'
import type { Accent, Fact, MetricValueFormat, ReportPriority, SourceProduct } from '@/model/types'

export type DemoAgo = { hours: number } | { days: number }

export type DemoKind = 'done' | 'open' | 'decision' | 'pr_ready'

/** `[text with **bold**, when, via?]`. `when` is "Today 9:04 AM" or "Mon 7:21 AM". */
export type DemoActivity = readonly [text: string, when: string, via?: string]

/** The primary metric. */
export interface DemoObservation {
    title: string
    format: MetricValueFormat
    unit?: string
    caption?: string
    /** Daily values in the metric's own unit, oldest first. */
    values: readonly number[]
    filters: number
}

export type DemoSupportingMetric = readonly [title: string, value: number, format: MetricValueFormat, unit?: string]

export interface DemoChart {
    id: string
    title: string
    caption?: string
    format?: MetricValueFormat
    unit?: string
    /** Daily values, oldest first. A chart without values is one the app only links to. */
    values?: readonly number[]
}

/** A signal behind the report. `ago` is the time before the demo anchor. */
export interface DemoSignal {
    source: SourceProduct
    ago: DemoAgo
    content: string
    sessionId?: string
    ticket?: number
}

export interface DemoBriefing {
    id: string
    title: string
    sourceProduct: SourceProduct
    sourceLabel: string
    ago: DemoAgo
    kind: DemoKind
    accent: Accent
    headNum: string
    headRest: string
    lede: string
    /** Markdown blocks of the full summary, joined with blank lines. */
    summary: readonly string[]
    /** Newest first, as the signals API returns them. */
    signals: readonly DemoSignal[]
    trace?: { error: string; frames: readonly (readonly [fn: string, loc: string])[]; footer: string }
    quotes?: readonly (readonly [text: string, who: string])[]
    replay?: { meta: string; count: number }
    facts: readonly (readonly [key: string, title: string, sub: string, tone: Fact['tone']])[]
    observation: DemoObservation
    supporting?: readonly DemoSupportingMetric[]
    charts?: readonly DemoChart[]
    activity: readonly DemoActivity[]
    contextNote: string
    prompt?: string
    handedStage: string
    owner?: { kind: 'user' | 'task'; name: string }
    priority?: ReportPriority
}

export const DEMO_USER_NAME = 'Robin Calloway'
export const DEMO_PROJECT_NAME = 'Hedgebox'
export const DEMO_AGENT = POSTHOG_AGENT

export const DEMO_DECISION_REPORT_ID = 'demo-report-ui-errors'

export const DEMO_DECISION = {
    id: 'demo-decision-chart-legend',
    question: 'Found the cause in ChartLegend. Two ways to fix it. Paused until you pick one.',
    options: [
        { id: 'guard', title: 'Guard the undefined label', meta: 'One-line fix, ships today' },
        {
            id: 'backfill',
            title: 'Backfill labels in the API',
            meta: 'Fixes the root cause · touches the API, needs backend review',
        },
    ],
} as const

export function demoDecisionMeta(answer: string): string {
    if (/backfill|api/i.test(answer)) {
        return 'Backfilling labels in the API · PR against the API first, flagged for backend review'
    }
    if (/sana/i.test(answer)) {
        return 'Asking Sana in the thread · keeps going on the UI side'
    }
    return 'Guarding the undefined label in ChartLegend · PR in about 15 min'
}

export const DEMO_BRIEFINGS: readonly DemoBriefing[] = [
    {
        id: 'demo-guest-404s',
        priority: 'P2',
        title: 'Shared report links returned 404 for guests',
        sourceProduct: 'signals_scout',
        sourceLabel: 'Report',
        ago: { hours: 2 },
        kind: 'done',
        accent: 'resolved',
        headNum: '0',
        headRest: 'guest 404s in the last six hours',
        lede: '1,204 yesterday. Fixed in deploy c71b20 this morning.',
        summary: [
            '## Problem',
            'Shared report links returned 404 for every guest without a session. Commit 9be4f2 moved the share token check behind the session middleware on Sunday night, so `resolveShareToken` never ran for invited viewers. Signed-in members were not affected, which is why nobody on the team saw it.',
            '## Impact',
            '1,204 failed opens on Monday, from 94 guests in 23 orgs. The peak was 310 an hour at 9 AM, when weekly reports go out. No paid seat was locked out, but several customers had forwarded the links to their own clients, who saw an error page with our logo on it.',
            '## Solution',
            'Sana moved the token check back in front of the session middleware and added a test that opens a shared link with no cookies. The fix shipped in deploy c71b20 at 8:10 AM. Guest 404s are back to the baseline of expired tokens, about 20 a day. Nothing else to do unless that baseline moves.',
        ],
        signals: [
            {
                source: 'logs',
                ago: { hours: 1 },
                content:
                    'Guest 404s on /shared/:token are back to baseline after deploy c71b20. 20 in the last 6 hours, all from expired tokens.',
            },
            {
                source: 'session_replay',
                ago: { hours: 26 },
                sessionId: 'demo-guest-404s-session',
                content:
                    'An invited viewer opens a shared report link and lands on a 404 page after 8 seconds. They leave without signing in.',
            },
            {
                source: 'error_tracking',
                ago: { hours: 27 },
                content:
                    'HTTP 404 on GET /shared/:token for requests with no session\n```\nloadSharedReport in src/scenes/SharedReport.tsx line 31\nresolveShareToken in src/server/share.ts line 57\n```',
            },
        ],
        trace: {
            error: 'HTTP 404 · GET /shared/:token · no session',
            frames: [
                ['resolveShareToken', 'share.ts:57'],
                ['loadSharedReport', 'SharedReport.tsx:31'],
            ],
            footer: 'Introduced in 9be4f2 · Sun 11:40 PM · Sana · fixed in c71b20 at 8:10 AM',
        },
        replay: { meta: '404 at 0:08 · 0:15 total', count: 12 },
        facts: [
            ['Where', 'Shared report links', '/shared/:token · invited viewers only', 'default'],
            ['Since', 'Mon 7:15 AM · peak 310 an hour', 'Fixed 8:10 AM by Sana', 'default'],
            ['Impact', '94 guests in 23 orgs', 'All invited viewers. No paid seat was locked out.', 'default'],
            ['Owner', 'Sana', '', 'default'],
        ],
        observation: {
            title: 'Guest 404s on shared links',
            format: 'count',
            values: [20, 20, 360, 840, 1200, 1040, 880, 660, 400, 180, 20, 20, 20, 20],
            filters: 1,
        },
        activity: [
            ['PostHog created the report', 'Mon 7:21 AM'],
            [`${DEMO_USER_NAME} changed assignee to **Sana Patel**`, 'Mon 7:40 AM'],
            [
                'Claude Code linked commit **c71b20** and changed status from **Open** to **Resolved**',
                'Today 8:10 AM',
                MCP_VIA,
            ],
        ],
        contextNote: 'Sends the request log and the c71b20 diff as context',
        handedStage: 'Reading share.ts · a PR will land here to review',
        owner: { kind: 'user', name: 'Sana Patel' },
    },
    {
        id: DEMO_DECISION_REPORT_ID,
        priority: 'P0',
        title: '3,721 errors in the report UI since 9 AM',
        sourceProduct: 'error_tracking',
        sourceLabel: 'Error',
        ago: { hours: 1 },
        kind: 'decision',
        accent: 'alert',
        headNum: '3,721',
        headRest: "errors since this morning's deploy",
        lede: 'One TypeError in ChartLegend.',
        summary: [
            '## Problem',
            'A TypeError in `ChartLegend` breaks every report with a custom legend. Commit a3f9e1, "Refactor legend series mapping", maps legend entries by index. When a series has no label, its entry is undefined and `ChartLegend.tsx:142` reads `label` from it. The chart area stays blank while the rest of the page works, so most people reload once and then leave.',
            '## Impact',
            '3,721 errors since 9:04 AM, 12 minutes after the deploy. 612 users in 51 orgs hit it. Chrome 130 is 94% of the errors, because most report traffic comes from it. Report views with an error went from 0.2% to 4.2%. Acme Corp and Northwind renew this quarter, and both use custom legends on their weekly reports.',
            '[Report views with an error](chart:error-share-21d)',
            '## Solution',
            'There are two ways to fix it. Guard the undefined label in `ChartLegend` and fall back to the series name. That is a one-line change that can ship today. Or backfill labels in the API, so no series reaches the client without one. That fixes the root cause, but it touches the API and needs a backend review. The agent paused until you pick one.',
        ],
        signals: [
            {
                source: 'error_tracking',
                ago: { hours: 0.2 },
                content:
                    "TypeError: Cannot read properties of undefined (reading 'label')\n```\nrenderReport in src/scenes/reports/ReportPage.tsx line 52\nReportChart in src/scenes/reports/ReportChart.tsx line 88\nChartLegend in src/scenes/reports/ChartLegend.tsx line 142\n```\n3,721 occurrences since 9:04 AM. First seen 12 minutes after deploy a3f9e1.",
            },
            {
                source: 'session_replay',
                ago: { hours: 1.5 },
                sessionId: 'demo-report-ui-errors-session',
                content:
                    'Opens the weekly revenue report. The chart area stays blank. The user reloads twice and leaves after 40 seconds.',
            },
            {
                source: 'conversations',
                ago: { hours: 2 },
                ticket: 8840,
                content: 'Our weekly report shows an empty box where the chart used to be. It worked on Friday.',
            },
            {
                source: 'github',
                ago: { hours: 2.8 },
                content:
                    'Commit a3f9e1 "Refactor legend series mapping" by Sana Patel, deployed at 8:52 AM. It changes ChartLegend.tsx and legendSeries.ts.',
            },
        ],
        trace: {
            error: "TypeError: Cannot read properties of undefined (reading 'label')",
            frames: [
                ['ChartLegend', 'ChartLegend.tsx:142'],
                ['ReportChart', 'ReportChart.tsx:88'],
            ],
            footer: 'Introduced in a3f9e1 · 8:52 AM · Sana · "Refactor legend series mapping"',
        },
        facts: [
            ['Where', 'Reports with a custom legend', 'Route /reports/:id · Chrome 130, 94%', 'default'],
            ['Since', '9:04 AM · 12 min after the deploy', 'Report views down 31% by 11:30 AM', 'default'],
            ['Impact', '612 users in 51 orgs', 'Acme Corp and Northwind renew this quarter', 'default'],
            ['Owner', 'Nobody assigned', '', 'alert'],
        ],
        observation: {
            title: 'TypeErrors in ChartLegend',
            format: 'count',
            caption: 'Since the 8:52 AM deploy',
            values: [90, 60, 120, 90, 60, 90, 1440, 2280, 2760, 3120, 2940, 3360, 3600, 3300],
            filters: 1,
        },
        supporting: [
            ['Affected users', 612, 'count'],
            ['Organizations', 51, 'count'],
            ['Report views with an error', 4.2, 'percentage'],
        ],
        charts: [
            {
                id: 'error-share-21d',
                title: 'Report views with an error',
                format: 'percentage',
                values: [
                    0.2, 0.1, 0.3, 0.2, 0.2, 0.1, 0.2, 0.3, 0.2, 0.1, 0.2, 0.2, 0.3, 0.2, 0.1, 0.2, 0.2, 0.3, 0.2, 2.8,
                    4.2,
                ],
            },
            { id: 'errors-by-release', title: 'Errors by release', caption: 'A SQL table the app links to' },
        ],
        activity: [
            ['PostHog created the report', 'Today 9:04 AM'],
            [`${DEMO_USER_NAME} handed off to **Claude Code**`, 'Today 9:12 AM'],
            ['Claude Code changed status from **Open** to **Investigating**', 'Today 9:13 AM', MCP_VIA],
            ['Claude Code asked for a decision and changed status to **Waiting on you**', 'Today 11:38 AM', MCP_VIA],
        ],
        contextNote: 'Sends the trace, the a3f9e1 diff and 38 replays as context',
        prompt: "Fix the TypeError in ChartLegend.tsx:142 (reading 'label' of undefined). Started after deploy a3f9e1 at 8:52 AM; 3,721 errors since 9 AM.",
        handedStage: 'Reading ChartLegend.tsx · a PR will land here to review',
        owner: { kind: 'task', name: 'Claude Code' },
    },
    {
        id: 'demo-report-load-time',
        priority: 'P1',
        title: 'Report load time is up 2.3s for every user',
        sourceProduct: 'pganalyze',
        sourceLabel: 'pganalyze',
        ago: { days: 2 },
        kind: 'open',
        accent: 'alert',
        headNum: '+2.3s',
        headRest: 'slower report loads for every user',
        lede: "p95 is 4.1s since Monday's deploy. Was 1.8s.",
        summary: [
            '## Problem',
            'Report pages wait on a new server call before the first paint. Commit 7d2c04, "Move legend rendering to the server", added `GET /api/report/:id/legend`, and `ReportChart` now calls it once per legend item instead of once per report. Each call runs the same series query again, so a report with 11 series runs it 11 times.',
            '## Impact',
            'p95 load time went from 1.8s to 4.1s on Monday at 3:05 PM and has stayed there. The step lines up with the deploy in the [p95 load time for the last 30 days](chart:load-time-30d). Every user sees it, on about 4,800 report views a day. It is worst for reports with 5 or more series, and Globex averages 11 series per report. Report views are down 12% since Tuesday.',
            '[Load time by browser](chart:load-time-by-browser)',
            '## Solution',
            'Fetch the legend once per report and pass it to each legend item, or cache the series query per request on the server. The first change is smaller and keeps the server rendering in place. Claude Code picked this up at 9:12 AM and is reading `ReportChart.tsx`.',
        ],
        signals: [
            {
                source: 'pganalyze',
                ago: { hours: 1 },
                content:
                    'Query `select_series_for_legend` ran 52,800 times in the last 24 hours, up from 4,800. Mean time 410ms. It is 68% of the total database time on the primary.\n```\nSELECT series.id, series.label, series.color\nFROM report_series series\nWHERE series.report_id = $1\nORDER BY series.position\n```',
            },
            {
                source: 'session_replay',
                ago: { hours: 20 },
                sessionId: 'demo-report-load-time-session',
                content:
                    'A spinner shows on the report page for 4.6 seconds before the chart draws. The user scrolls past the empty chart and opens the next report.',
            },
            {
                source: 'analytics',
                ago: { hours: 30 },
                content:
                    'p95 time from $pageview to report_loaded on /reports/:id crossed 3s on Monday at 3:05 PM. It was under 2s for the 30 days before.',
            },
            {
                source: 'github',
                ago: { days: 2 },
                content:
                    'Commit 7d2c04 "Move legend rendering to the server" by Priya Nair, deployed Monday at 2:30 PM.',
            },
        ],
        trace: {
            error: 'Slow request · GET /api/report/:id/legend · blocks first paint · 1.9s per call',
            frames: [
                ['renderLegend', 'server/legend.ts:88'],
                ['getReport', 'server/report.ts:140'],
                ['ReportPage', 'ReportPage.tsx:52'],
            ],
            footer: 'Introduced in 7d2c04 · Mon 2:30 PM · Priya · "Move legend rendering to the server"',
        },
        replay: { meta: 'spinner for 4.6s · 0:58 total', count: 54 },
        facts: [
            ['Where', 'Every report page', '/reports/:id · worst with 5+ series', 'default'],
            ['Since', 'Mon 3:05 PM · p95 crossed 3s', 'Report views down 12% by Tuesday', 'default'],
            ['Impact', 'Every user · 4,800 views a day', 'Worst for Globex, 11 series on average', 'default'],
            ['Owner', 'Claude Code', 'Picked up 9:12 AM', 'agent'],
        ],
        observation: {
            title: 'p95 report load time',
            format: 'duration',
            unit: 'ms',
            values: [1700, 1768, 1632, 1836, 1700, 1768, 1666, 3264, 3740, 3536, 4012, 3808, 4080, 3944],
            filters: 0,
        },
        supporting: [
            ['Report views a day', 4800, 'count'],
            ['p50 load time', 1900, 'duration', 'ms'],
            ['Series per report', 11, 'number'],
        ],
        charts: [
            {
                id: 'load-time-30d',
                title: 'p95 load time, last 30 days',
                caption: 'The step up is the Monday deploy',
                format: 'duration',
                unit: 'ms',
                values: [
                    1720, 1680, 1750, 1810, 1690, 1740, 1700, 1780, 1730, 1660, 1710, 1800, 1760, 1690, 1740, 1720,
                    1780, 1750, 1700, 1770, 1730, 1690, 1760, 3260, 3740, 3540, 4010, 3810, 4080, 3940,
                ],
            },
            { id: 'load-time-by-browser', title: 'Load time by browser', caption: 'A breakdown the app links to' },
        ],
        activity: [
            ['PostHog created the report', 'Mon 3:05 PM'],
            [`${DEMO_USER_NAME} handed off to **Claude Code**`, 'Today 9:12 AM'],
            ['Claude Code changed status from **Open** to **In progress**', 'Today 9:12 AM', MCP_VIA],
        ],
        contextNote: 'Sends the slow-request trace, the 7d2c04 diff and 54 replays as context',
        prompt: 'Report p95 load time rose from 1.8s to 4.1s after deploy 7d2c04. ReportChart fetches /api/series once per legend item. Fix it.',
        handedStage: 'Reading ReportChart.tsx · a PR will land here to review',
    },
    {
        id: 'demo-resolve-button',
        title: 'PR #4182 removed the Resolve button',
        sourceProduct: 'github',
        sourceLabel: 'GitHub',
        ago: { days: 2 },
        kind: 'open',
        accent: 'alert',
        headNum: '0',
        headRest: "Resolve clicks since Monday's deploy",
        lede: '1,900 a week before. The button is gone from the issue header.',
        summary: [
            '## Problem',
            'PR #4182, "Simplify issue header", removed `ResolveButton` from `IssueHeader`. The PR moved the header actions into an overflow menu, but Resolve was left out of the menu items. There is no way to resolve an issue from its page now. The keyboard shortcut still works, which is why a few resolves still come through.',
            '## Impact',
            "Resolve clicks went from about 1,900 a week to 6 a day since Monday's deploy at 2:30 PM. 340 users in 60 orgs triage issues, and all of them are affected. Three support tickets so far ask where the button went. Open issue counts are going up in the orgs that triage every day.",
            '## Solution',
            'Add Resolve back to the issue header, as its own button or as the first item in the new overflow menu. A button matches what people look for in the replays: they hover where it used to be, then open the menu and close it again. Add a test that the header shows Resolve for an open issue.',
        ],
        signals: [
            {
                source: 'conversations',
                ago: { hours: 20 },
                ticket: 8871,
                content: "Where did the resolve button go? I can't close issues anymore unless I use the shortcut.",
            },
            {
                source: 'session_replay',
                ago: { hours: 26 },
                sessionId: 'demo-resolve-button-session',
                content:
                    'Hovers over the issue header where Resolve used to be, opens the overflow menu, closes it, and leaves the issue open.',
            },
            {
                source: 'analytics',
                ago: { hours: 40 },
                content:
                    'resolve_clicked fell from 270 a day to 6 a day after Monday 2:30 PM. Resolves from the keyboard shortcut are unchanged.',
            },
            {
                source: 'github',
                ago: { hours: 49 },
                content:
                    'PR #4182 "Simplify issue header" by Priya Nair, merged Monday at 2:22 PM. It removes ResolveButton from IssueHeader.tsx.',
            },
        ],
        trace: {
            error: 'Regression · ResolveButton no longer rendered in IssueHeader',
            frames: [
                ['IssueHeader', 'IssueHeader.tsx:40'],
                ['IssuePage', 'IssuePage.tsx:118'],
            ],
            footer: 'Introduced in 7d2c04 · Mon 2:30 PM · Priya · PR #4182 "Simplify issue header"',
        },
        replay: { meta: 'hunts for Resolve · 0:19', count: 21 },
        facts: [
            ['Where', 'Issue header', '/issues/:id · all browsers', 'default'],
            ['Since', 'Mon 2:31 PM', '3 support tickets since: "Where did the resolve button go?"', 'default'],
            ['Impact', '340 users in 60 orgs', 'Everyone who triages issues', 'default'],
            ['Owner', 'Nobody assigned', '', 'alert'],
        ],
        observation: {
            title: 'Resolve clicks',
            format: 'count',
            values: [288, 312, 264, 330, 276, 300, 294, 6, 6, 6, 6, 6, 6, 6],
            filters: 1,
        },
        activity: [
            ['PostHog created the report', 'Mon 2:31 PM'],
            ['PostHog linked **PR #4182** as the likely cause', 'Mon 2:31 PM'],
            ['PostHog attached **3 support tickets**', 'Tue 10:15 AM'],
        ],
        contextNote: 'Sends the #4182 diff, click data and 21 replays as context',
        prompt: 'PR #4182 removed ResolveButton from IssueHeader.tsx. Restore it; it was clicked 1,900 times a week.',
        handedStage: 'Reading IssueHeader.tsx · a PR will land here to review',
    },
    {
        id: 'demo-report-emails',
        title: 'Scheduled report emails stopped on Sunday',
        sourceProduct: 'signals_scout',
        sourceLabel: 'Report',
        ago: { days: 3 },
        kind: 'open',
        accent: 'alert',
        headNum: '0 of 860',
        headRest: 'scheduled report emails delivered since Sunday',
        lede: 'The digest job has been paused for two days. Nobody paused it on purpose.',
        summary: [
            '## Problem',
            'The scheduled report digest has not sent since Saturday. The digest worker restarted on Sunday at 5:58 AM during a node pool upgrade, and the `report_digest` queue was not registered again when it started. Jobs are still added every morning, but no worker picks them up. Nothing fails, so nothing alerts.',
            '## Impact',
            "0 of 860 scheduled emails were delivered since Sunday: 0 of 410 on Sunday and 0 of 450 on Monday. The recipients are in 140 orgs. Northwind's Monday exec digest goes to 40 people, and two of them have already asked their admin where it is. The next run is in 15 hours.",
            '## Solution',
            'Register `report_digest` in `workers/index.ts` with the other queues. Add a startup check that fails the deploy when a scheduled queue has no consumer, so the next restart cannot drop a queue without a warning. After the fix, run the two missed digests once, so recipients get Sunday and Monday before the next scheduled run.',
        ],
        signals: [
            {
                source: 'logs',
                ago: { hours: 10 },
                content:
                    'Queue report_digest has no consumer.\n```\nqueue=report_digest waiting=860 active=0 oldest_job_age=50h\nqueue=alerts_slack waiting=0 active=4\nqueue=export_csv waiting=2 active=3\n```',
            },
            {
                source: 'logs',
                ago: { hours: 60 },
                content:
                    'Worker digest-7f4c restarted at Sun 5:58 AM after the node pool upgrade. Registered queues: alerts_slack, export_csv, insights_refresh.',
            },
            {
                source: 'analytics',
                ago: { hours: 70 },
                content: 'digest_email_sent fell to 0 on Sunday. 410 were expected.',
            },
        ],
        trace: {
            error: 'Job report_digest · last success Sat 6:00 AM · queue not registered',
            frames: [
                ['scheduleDigest', 'workers/digest.ts:22'],
                ['registerQueues', 'workers/index.ts:9'],
            ],
            footer: 'Worker restarted Sun 5:58 AM · node pool upgrade · the digest queue was not re-registered',
        },
        facts: [
            ['Where', 'Digest worker', 'report_digest queue', 'default'],
            ['Since', 'Sun 6:00 AM · 0 of 410', 'Mon 6:00 AM · 0 of 450 · next run in 15 hours', 'default'],
            ['Impact', '860 recipients in 140 orgs', "Northwind's Monday exec digest goes to 40 people", 'default'],
            ['Owner', 'Nobody assigned', '', 'alert'],
        ],
        observation: {
            title: 'Scheduled report emails sent',
            format: 'count',
            values: [88, 92, 90, 94, 86, 96, 90, 92, 2, 2, 2, 2, 2, 2],
            filters: 0,
        },
        activity: [
            ['PostHog created the report', 'Sun 6:14 AM'],
            ['PostHog changed priority from **Medium** to **High**', 'Mon 6:05 AM'],
        ],
        contextNote: 'Sends the worker log and the queue config as context',
        prompt: 'The report_digest queue stopped running after the worker restart on Sunday 5:58 AM. Re-register it in workers/index.ts.',
        handedStage: 'Reading workers/index.ts · a PR will land here to review',
    },
    {
        id: 'demo-rage-clicks',
        title: 'Rage clicks on Apply filter tripled',
        sourceProduct: 'analytics',
        sourceLabel: 'Product Analytics',
        ago: { days: 2 },
        kind: 'pr_ready',
        accent: 'alert',
        headNum: '1,140',
        headRest: 'rage clicks on Apply filter in 24 hours',
        lede: 'Was 380 a day. 82% are Safari.',
        summary: [
            '## Problem',
            'Apply filter does nothing in Safari 17 when a date range is typed instead of picked. The new date picker from commit 9a11f3 passes the typed text to `parseRange`, which calls `new Date()` on a format Safari does not parse. It returns Invalid Date, `applyFilter` drops the range without a message, and people click Apply again.',
            '## Impact',
            '1,140 rage clicks on Apply filter in 24 hours, up from about 380 a day. 82% are in Safari. 410 users in 38 orgs are affected, and 60 of them are at Acme Corp. Filter usage in Safari is down 19% since Monday, so some people have stopped trying.',
            '## Solution',
            'Parse typed ranges with the same date library the picker uses. When a range cannot be parsed, show an inline error under the field instead of ignoring it. Codex opened PR #4190 with the fix and a test for typed ranges, and checked it in Safari 17 on staging. It needs a review before it can merge.',
        ],
        signals: [
            {
                source: 'session_replay',
                ago: { hours: 5 },
                sessionId: 'demo-rage-clicks-session',
                content:
                    'Types "Mar 3 - Mar 9" in the date range field and clicks Apply 6 times. The results do not change.',
            },
            {
                source: 'analytics',
                ago: { hours: 12 },
                content: '$rageclick on the Apply filter button: 1,140 in 24 hours. 82% are in Safari 17.',
            },
            {
                source: 'error_tracking',
                ago: { hours: 30 },
                content:
                    'Console warning: Invalid Date passed to applyFilter\n```\nparseRange in src/components/DateRangeInput.tsx line 31\napplyFilter in src/components/FilterBar.tsx line 77\n```',
            },
        ],
        trace: {
            error: 'Console warning · Invalid Date passed to applyFilter',
            frames: [
                ['applyFilter', 'FilterBar.tsx:77'],
                ['parseRange', 'DateRangeInput.tsx:31'],
            ],
            footer: 'Introduced in 9a11f3 · Mon 1:40 PM · Sana · "New date picker"',
        },
        replay: { meta: 'clicks Apply 6 times · 0:44', count: 60 },
        facts: [
            ['Where', 'Filter bar · Safari 17', 'Typed date ranges, not picked', 'default'],
            ['Since', 'Mon 2:10 PM', 'Filter usage down 19% in Safari', 'default'],
            ['Impact', '410 users in 38 orgs', 'Acme Corp is 60 of them', 'default'],
            ['Owner', 'Codex', 'PR #4190 opened 9:41 AM', 'agent'],
        ],
        observation: {
            title: 'Rage clicks on Apply filter',
            format: 'count',
            caption: 'Mostly Safari 17',
            values: [340, 380, 320, 400, 360, 340, 380, 720, 960, 1040, 1120, 1200, 1080, 1160],
            filters: 2,
        },
        supporting: [
            ['Affected users', 410, 'count'],
            ['Share on Safari', 82, 'percentage'],
        ],
        activity: [
            ['PostHog created the report', 'Mon 2:10 PM'],
            [`${DEMO_USER_NAME} handed off to **Codex**`, 'Today 9:30 AM'],
            ['Codex changed status from **Open** to **In progress**', 'Today 9:31 AM', MCP_VIA],
            ['Codex opened **PR #4190** and changed status to **Ready for review**', 'Today 9:41 AM', MCP_VIA],
        ],
        contextNote: 'Sends the console warnings, the 9a11f3 diff and 60 replays as context',
        prompt: 'Apply filter does nothing in Safari 17 when a date range is typed. parseRange in DateRangeInput.tsx:31 returns Invalid Date. Fix it.',
        handedStage: 'Reading DateRangeInput.tsx · a PR will land here to review',
        owner: { kind: 'task', name: 'Codex' },
    },
    {
        id: 'demo-copy-to-clipboard',
        title: '7 customers asked to copy reports to clipboard',
        sourceProduct: 'dashboard',
        sourceLabel: 'Dashboards',
        ago: { days: 6 },
        kind: 'open',
        accent: 'opportunity',
        headNum: '7',
        headRest: 'customers asked to copy reports to the clipboard',
        lede: '3 support tickets and 4 survey replies, in five days. They are screenshotting reports into Slack and Notion.',
        summary: [
            '## Problem',
            'Customers want to copy a report chart as an image and paste it into Slack, Notion or a standup doc. Today they take screenshots, which crop badly and lose the legend. Export already renders a PNG on the server for scheduled emails, but there is no way to get that image from the report page.',
            '## Impact',
            '7 customers asked in five days: 3 in support tickets and 4 in in-app survey replies. They are in 6 orgs worth $184k ARR, and 2 of the requests came in this morning from Enterprise accounts. Northwind renews in November. Screenshot keypresses on report pages were 1,320 last week, up 40%.',
            '## Solution',
            'Add a Copy image button next to Export on the report page. It can call the existing PNG export and write the result to the clipboard, so no new rendering code is needed. Keep CSV export as it is. The scope fits in one PR, plus a short spec for the clipboard permission prompt in Safari.',
        ],
        signals: [
            {
                source: 'zendesk',
                ago: { hours: 3 },
                ticket: 8857,
                content:
                    'Can we get a copy to clipboard option on reports? We paste charts into Notion every week, and screenshots look blurry on our screens.',
            },
            {
                source: 'analytics',
                ago: { hours: 5 },
                content:
                    'Survey "What would make reports easier to share?": 4 of 31 replies ask to copy a chart as an image.',
            },
            {
                source: 'zendesk',
                ago: { hours: 60 },
                ticket: 8830,
                content: 'We share these charts in Slack every day. A copy button would save us a lot of cropping.',
            },
            {
                source: 'zendesk',
                ago: { hours: 100 },
                ticket: 8812,
                content:
                    'I just want to paste the chart into our Monday standup doc. Right now I screenshot it and it looks terrible.',
            },
        ],
        quotes: [
            [
                '"I just want to paste the chart into our Monday standup doc. Right now I screenshot it and it looks terrible."',
                'Priya K · Northwind · ticket #8812',
            ],
            [
                '"Export to CSV is fine but I need the picture. Copy image would be perfect."',
                'Tom A · Acme Corp · in-app survey',
            ],
        ],
        facts: [
            ['Who', 'Priya K, Tom A and 5 more', 'Northwind, Acme Corp, Globex, Initech', 'default'],
            ['Since', 'Thursday', '2 more this morning, both Enterprise', 'default'],
            ['Worth', '$184k ARR across 6 orgs', 'Northwind renews in November', 'default'],
            ['Workaround', '1,320 screenshot keypresses', 'On report pages last week, up 40%', 'default'],
            ['Owner', 'Nobody assigned', '', 'alert'],
        ],
        observation: {
            title: 'Clipboard requests',
            format: 'count',
            values: [0, 0, 0, 0, 0, 0, 0, 0, 2, 2, 3, 2, 3, 0],
            filters: 0,
        },
        activity: [
            ['PostHog created the report', 'Thu 4:52 PM'],
            ['PostHog attached **2 survey replies**', 'Today 8:20 AM'],
        ],
        contextNote: 'Sends the 7 quotes, the orgs and the Export code path as context',
        prompt: '7 customers asked to copy a report as an image to the clipboard. Export already renders a PNG server-side. Scope a Copy image button on top of it.',
        handedStage: 'Reading the Export code path · a spec will land here to review',
    },
    {
        id: 'demo-checkout-dead-clicks',
        title: 'Upgrade button does nothing on small screens',
        sourceProduct: 'session_replay',
        sourceLabel: 'Session replay',
        ago: { hours: 4 },
        kind: 'open',
        accent: 'alert',
        headNum: '38%',
        headRest: 'of upgrade attempts end in a dead click',
        lede: 'Only below 768px wide. The cookie banner covers the button.',
        summary: [
            '## Problem',
            "On screens narrower than 768px, the new cookie banner sits on top of the Upgrade plan button on the billing page. The banner has a higher z-index than the page footer and spans the full width, so a tap on Upgrade lands on the banner's empty area and does nothing. The banner shipped on Saturday at 10:20 AM.",
            '## Impact',
            '38% of upgrade attempts on small screens now end in a dead click, up from about 2%. 212 users in 180 orgs tried to upgrade and could not, all of them on the free plan. Upgrades from mobile are down 44%. iOS Safari is 71% of the affected sessions.',
            '## Solution',
            'On small screens, give the banner a bottom margin equal to the height of the sticky footer, or move the Upgrade button above the banner. Both keep the banner visible and the button reachable. Check the result against the 87 attached replays, which cover iPhone and Android widths.',
        ],
        signals: [
            {
                source: 'session_replay',
                ago: { hours: 2 },
                sessionId: 'demo-checkout-dead-clicks-session',
                content:
                    'Taps Upgrade plan 4 times on an iPhone and nothing happens. Scrolls down, accepts cookies, and the button works on the next tap.',
            },
            {
                source: 'replay_vision',
                ago: { hours: 6 },
                sessionId: 'demo-checkout-dead-clicks-session-2',
                content:
                    'The cookie banner covers the Upgrade plan button at 390px wide. 87 sessions show the same layout.',
            },
            {
                source: 'analytics',
                ago: { hours: 20 },
                content:
                    'upgrade_clicked with no billing_checkout_started within 10 seconds: 38% on viewports under 768px, 1.6% on wider screens.',
            },
        ],
        replay: { meta: 'taps Upgrade 4 times · 0:31', count: 87 },
        facts: [
            ['Where', 'Billing page · Upgrade plan', 'Viewports under 768px · iOS Safari 71%', 'default'],
            ['Since', 'Sat 10:20 AM · new cookie banner', 'Upgrades from mobile down 44%', 'default'],
            ['Impact', '212 users in 180 orgs', 'All on the free plan, trying to pay', 'default'],
            ['Owner', 'Nobody assigned', '', 'alert'],
        ],
        observation: {
            title: 'Upgrade attempts that end in a dead click',
            format: 'percentage',
            caption: 'Screens below 768px',
            values: [1.9, 1.3, 2.6, 1.9, 1.3, 1.9, 1.6, 2.2, 20.5, 29.4, 25.6, 33.3, 38.4, 30.7],
            filters: 2,
        },
        activity: [
            ['PostHog created the report', 'Sun 9:02 AM'],
            ['PostHog attached **87 replays**', 'Today 6:40 AM'],
        ],
        contextNote: 'Sends 87 replays, the banner component and the billing page layout as context',
        prompt: 'The cookie banner covers the Upgrade plan button on viewports under 768px. Dead clicks on it went from 1% to 38% of upgrade attempts. Fix the stacking so the button stays reachable.',
        handedStage: 'Reading CookieBanner.tsx · a PR will land here to review',
    },
    {
        id: 'demo-ai-summary-cost',
        title: 'AI summaries cost 4x more since Thursday',
        sourceProduct: 'llm_analytics',
        sourceLabel: 'AI observability',
        ago: { days: 1 },
        kind: 'open',
        accent: 'alert',
        headNum: '$1,860',
        headRest: 'spent on report summaries yesterday',
        lede: 'Was $460 a day. Each call now sends the full event list, not the top 50.',
        summary: [
            '## Problem',
            'Report summaries send every event in the report to the model. Commit e40b9d, "Include all events in summary context", removed the top-50 cap in `buildSummaryPrompt`. Input grew from about 9,800 to 41,200 tokens per call, and latency grew with it.',
            '## Impact',
            'Summary spend was $1,860 yesterday, against about $460 a day before Thursday. That is $1,400 a day over budget. p95 latency went from 3.2s to 8.9s, so people wait longer for every summary. Answer quality is unchanged at 4.3, which means the extra context does not make the summaries better. Most of the extra tokens are page views and clicks that the summaries never mention.',
            '## Solution',
            'Restore the top-50 cap, ranked by the same relevance score as before. If the change was meant to fix missing context on long reports, cap by tokens instead of by count, for example at 12,000 input tokens. Mateo owns `ai/summary.ts` and can confirm which of the two was intended.',
        ],
        signals: [
            {
                source: 'llm_analytics',
                ago: { hours: 4 },
                content:
                    'summarize_report input tokens: p50 41,200, up from 9,800. Output tokens are unchanged at 310.',
            },
            {
                source: 'llm_analytics',
                ago: { hours: 20 },
                content: 'Generation cost for summarize_report was $1,860 yesterday, across 3,100 calls.',
            },
            {
                source: 'github',
                ago: { hours: 70 },
                content:
                    'Commit e40b9d "Include all events in summary context" by Mateo Ruiz, deployed Thursday at 3:15 PM.\n```\n- const events = rankEvents(report.events).slice(0, 50)\n+ const events = report.events\n```',
            },
        ],
        trace: {
            error: 'Prompt size · summarize_report · 41,200 input tokens per call (was 9,800)',
            frames: [
                ['buildSummaryPrompt', 'ai/summary.ts:64'],
                ['summarizeReport', 'ai/summary.ts:21'],
            ],
            footer: 'Introduced in e40b9d · Thu 3:15 PM · Mateo · "Include all events in summary context"',
        },
        facts: [
            ['Where', 'Report summaries', 'summarize_report · 9,400 calls a day', 'default'],
            ['Since', 'Thu 3:40 PM', 'Latency p95 up from 3.2s to 8.9s', 'default'],
            ['Impact', '$1,400 a day over budget', 'Answer quality score unchanged at 4.3', 'default'],
            ['Owner', 'Mateo', '', 'default'],
        ],
        observation: {
            title: 'Report summary spend',
            format: 'currency',
            unit: 'USD',
            values: [465, 434, 480.5, 449.5, 465, 418.5, 465, 449.5, 480.5, 1178, 1736, 1612, 1798, 1860],
            filters: 1,
        },
        supporting: [
            ['Summary calls a day', 3100, 'count'],
            ['Cost per call', 0.6, 'currency', 'USD'],
            ['Answer quality score', 4.3, 'number'],
        ],
        charts: [
            {
                id: 'tokens-per-call',
                title: 'Input tokens per summary call',
                caption: 'The full event list goes in since Thursday',
                values: [2100, 2080, 2150, 2120, 2090, 2110, 2060, 2130, 2100, 8350, 8420, 8390, 8460, 8410],
            },
        ],
        activity: [
            ['PostHog created the report', 'Fri 8:10 AM'],
            [`${DEMO_USER_NAME} changed assignee to **Mateo Ruiz**`, 'Fri 9:25 AM'],
            ['PostHog changed priority from **Medium** to **High**', 'Today 7:00 AM'],
        ],
        contextNote: 'Sends 20 traces, the e40b9d diff and the daily cost breakdown as context',
        prompt: 'summarize_report input grew from 9,800 to 41,200 tokens after e40b9d. buildSummaryPrompt in ai/summary.ts:64 now sends every event. Restore the top-50 cap without losing answer quality.',
        handedStage: 'Reading ai/summary.ts · a PR will land here to review',
        owner: { kind: 'user', name: 'Mateo Ruiz' },
    },
    {
        id: 'demo-export-timeouts',
        title: 'CSV exports timed out for large projects',
        sourceProduct: 'logs',
        sourceLabel: 'Logs',
        ago: { hours: 5 },
        kind: 'done',
        accent: 'resolved',
        headNum: '0',
        headRest: 'export timeouts since the fix this morning',
        lede: '640 on Monday. Exports over 200k rows now stream instead of buffering.',
        summary: [
            '## Problem',
            'CSV exports over 200k rows timed out after 300 seconds. The row cap went from 100k to 1M on Monday, but `writeRows` still built the whole file in memory before the upload. Large exports ran out of time while they buffered, and they failed without a partial file. Exports under the old cap finished in less than a minute, so the buffering was never a problem before.',
            '## Impact',
            '640 timeouts on Monday, from 58 users in 31 orgs. 9 of them retried more than five times, and two opened support tickets. Exports under 200k rows were not affected.',
            '## Solution',
            'Marcus changed `writeRows` to stream rows to storage in chunks of 10k, so memory stays flat and the upload starts at once. The fix shipped in 5c8e7a at 7:45 AM, and there have been no timeouts since. The 1M row cap stays. A 1M row export now finishes in about 90 seconds, well under the limit.',
        ],
        signals: [
            {
                source: 'logs',
                ago: { hours: 4 },
                content: 'export_csv finished 1,000,000 rows in 94s. No timeouts in the last 4 hours.',
            },
            {
                source: 'logs',
                ago: { hours: 60 },
                content:
                    'WorkerTimeout in export_csv after 300s\n```\nrunExport in exports/run.ts line 48\nwriteRows in exports/csv.ts line 112\n```',
            },
            {
                source: 'conversations',
                ago: { hours: 70 },
                ticket: 8790,
                content: "Our export of last quarter's events fails every time. Smaller date ranges work.",
            },
        ],
        trace: {
            error: 'WorkerTimeout · export_csv · exceeded 300s',
            frames: [
                ['writeRows', 'exports/csv.ts:112'],
                ['runExport', 'exports/run.ts:48'],
            ],
            footer: 'Started when the row cap went from 100k to 1M · fixed in 5c8e7a at 7:45 AM',
        },
        facts: [
            ['Where', 'CSV exports over 200k rows', 'export_csv worker', 'default'],
            ['Since', 'Mon 11:00 AM', 'Fixed 7:45 AM by Marcus', 'default'],
            ['Impact', '58 users in 31 orgs', '9 retried more than five times', 'default'],
            ['Owner', 'Marcus', '', 'default'],
        ],
        observation: {
            title: 'CSV export timeouts',
            format: 'count',
            values: [10, 200, 440, 600, 480, 360, 420, 300, 220, 60, 10, 10, 10, 10],
            filters: 1,
        },
        activity: [
            ['PostHog created the report', 'Mon 11:24 AM'],
            [`${DEMO_USER_NAME} changed assignee to **Marcus Lee**`, 'Mon 12:05 PM'],
            ['Marcus Lee changed status from **Open** to **Resolved**', 'Today 7:50 AM'],
        ],
        contextNote: 'Sends the worker logs and the 5c8e7a diff as context',
        handedStage: 'Reading exports/csv.ts · a PR will land here to review',
        owner: { kind: 'user', name: 'Marcus Lee' },
    },
    {
        id: 'demo-dark-mode-requests',
        priority: 'P3',
        title: '12 customers asked for dark mode in shared dashboards',
        sourceProduct: 'zendesk',
        sourceLabel: 'Zendesk',
        ago: { days: 4 },
        kind: 'open',
        accent: 'opportunity',
        headNum: '12',
        headRest: 'requests for dark mode on shared dashboards',
        lede: 'Most of them put dashboards on office TVs. The white background is too bright at night.',
        summary: [
            '## Problem',
            "Shared dashboard links always use the light theme. The app has a dark theme, but public links do not read the viewer's preference and have no toggle. Customers who put dashboards on office TVs and ops walls find the white background too bright at night.",
            '## Impact',
            '12 requests in two weeks, 5 of them in the last four days. They come from 9 orgs worth $96k ARR, and 3 of those are in a renewal quarter. 4 tickets mention a dark reader browser extension as the workaround, which breaks the chart colors.',
            '## Solution',
            'Add a theme option to shared links: light, dark, or follow the system. Save it with the share settings, so a link on a TV stays dark. The dark theme tokens already exist, so most of the work is passing the setting to the public page and checking the chart colors on the dark background.',
        ],
        signals: [
            {
                source: 'zendesk',
                ago: { hours: 20 },
                ticket: 9066,
                content:
                    'We run dashboards on a wall display in our network operations room. Please add dark mode to shared links.',
            },
            {
                source: 'zendesk',
                ago: { hours: 50 },
                ticket: 9051,
                content: 'The app has dark mode, so why does the public link ignore it?',
            },
            {
                source: 'zendesk',
                ago: { hours: 80 },
                ticket: 9034,
                content: 'Our ops wall runs 24/7. The shared dashboard is the only bright screen in the room.',
            },
        ],
        quotes: [
            [
                '"Our ops wall runs 24/7. The shared dashboard is the only bright screen in the room."',
                'Dana R · Initech · ticket #9034',
            ],
            ['"The app has dark mode, so why does the public link ignore it?"', 'Lee M · Globex · ticket #9051'],
        ],
        facts: [
            ['Who', 'Dana R, Lee M and 10 more', 'Initech, Globex, Umbrella, Hooli', 'default'],
            ['Since', '2 weeks ago', '5 in the last four days', 'default'],
            ['Worth', '$96k ARR across 9 orgs', '3 are in a renewal quarter', 'default'],
            ['Workaround', 'Browser extensions', '4 tickets mention a dark reader plugin', 'default'],
            ['Owner', 'Nobody assigned', '', 'alert'],
        ],
        observation: {
            title: 'Dark mode requests',
            format: 'count',
            values: [0, 2, 0, 0, 2, 0, 4, 0, 0, 2, 4, 0, 6, 2],
            filters: 0,
        },
        activity: [
            ['PostHog created the report', 'Wed 2:18 PM'],
            ['PostHog attached **3 more tickets**', 'Fri 11:02 AM'],
        ],
        contextNote: 'Sends the 12 tickets, the orgs and the shared dashboard theme code as context',
        prompt: '12 customers asked for dark mode on shared dashboard links. The app already has a dark theme. Scope a theme option for shared links.',
        handedStage: 'Reading the shared dashboard theme · a spec will land here to review',
    },
    {
        id: 'demo-webhook-health',
        title: 'Slack alert webhook failed for 3 hours',
        sourceProduct: 'health_checks',
        sourceLabel: 'Health check',
        ago: { days: 1 },
        kind: 'done',
        accent: 'resolved',
        headNum: '1,312',
        headRest: 'alerts retried and delivered',
        lede: 'The signing secret expired on Saturday. Rotated, and the queue drained in 20 minutes.',
        summary: [
            '## Problem',
            'The Slack alert webhook rejected every delivery for 3 hours, because its signing secret expired on Saturday at 11:00 PM. The secret had a fixed 12 month expiry and no reminder. Each delivery got HTTP 401 `invalid_signature`, and the queue kept retrying. Nobody was paged, because the delivery check only alerted after 6 hours of failures.',
            '## Impact',
            '1,312 alerts were late by up to 3 hours, for 74 orgs that send alerts to Slack. No alerts were dropped, because the retry queue held them until the secret was rotated. Alerts by email and webhook were not affected. Most of them were low priority.',
            '## Solution',
            'Marcus rotated the secret on Sunday at 2:05 AM, and the queue drained in 20 minutes. To stop this from happening again, add a health check that warns 14 days before the secret expires, and page on call when Slack deliveries fail for more than 10 minutes.',
        ],
        signals: [
            {
                source: 'health_checks',
                ago: { hours: 20 },
                content: 'Slack delivery check is passing. The alerts_slack queue is empty.',
            },
            {
                source: 'logs',
                ago: { hours: 24 },
                content:
                    'HTTP 401 from Slack\n```\nPOST https://hooks.slack.example.com/services/T000/B000 status=401 error=invalid_signature\nflushQueue in alerts/queue.ts line 70\ndeliverAlert in alerts/slack.ts line 35\n```',
            },
            {
                source: 'health_checks',
                ago: { hours: 26 },
                content: 'Slack delivery check has failed for 15 minutes. 420 alerts are waiting in alerts_slack.',
            },
        ],
        trace: {
            error: 'HTTP 401 · POST hooks.slack.example.com · invalid_signature',
            frames: [
                ['deliverAlert', 'alerts/slack.ts:35'],
                ['flushQueue', 'alerts/queue.ts:70'],
            ],
            footer: 'Secret expired Sat 11:00 PM · rotated Sun 2:05 AM by Marcus',
        },
        facts: [
            ['Where', 'Slack alert delivery', 'alerts_slack queue', 'default'],
            ['Since', 'Sat 11:00 PM → Sun 2:05 AM', 'No alerts were dropped', 'default'],
            ['Impact', '1,312 alerts late by up to 3 hours', '74 orgs, all on Slack alerts', 'default'],
            ['Owner', 'Marcus', '', 'default'],
        ],
        observation: {
            title: 'Failed Slack deliveries',
            format: 'count',
            values: [12, 12, 12, 12, 420, 720, 624, 48, 12, 12, 12, 12, 12, 12],
            filters: 1,
        },
        activity: [
            ['PostHog created the report', 'Sat 11:06 PM'],
            ['Marcus Lee changed status from **Open** to **Resolved**', 'Sun 2:30 AM'],
        ],
        contextNote: 'Sends the delivery log and the secret rotation history as context',
        handedStage: 'Reading alerts/slack.ts · a PR will land here to review',
        owner: { kind: 'user', name: 'Marcus Lee' },
    },
    {
        id: 'demo-funnel-step-crash',
        title: 'Funnels with 10+ steps crash the editor',
        sourceProduct: 'error_tracking',
        sourceLabel: 'Error',
        ago: { hours: 6 },
        kind: 'open',
        accent: 'alert',
        headNum: '214',
        headRest: 'editor crashes on long funnels since Friday',
        lede: 'One RangeError when the step list renders. Funnels under 10 steps are fine.',
        summary: [
            '## Problem',
            'The funnel editor crashes when a funnel has 10 or more steps. Commit b17d52, "Drag to reorder funnel steps", added `reorderSteps`, which calls itself again when the order changes. With 10 or more steps, the order comparison sorts "10" before "2", so the order never settles and the call stack overflows.',
            '## Impact',
            '214 crashes since Friday at 4:30 PM, from 96 users in 41 orgs. The page goes blank and unsaved changes are lost, so people rebuild long funnels from the start. Saved funnels with 10 or more steps are down 60% since the deploy. Most of them are on growth teams that model long onboarding flows.',
            '## Solution',
            'Compare step positions as numbers, and update the order once per drag instead of during render. Add a test with a 12 step funnel. Drag to reorder must keep working for funnels of every length, so check 2, 9 and 15 steps by hand too.',
        ],
        signals: [
            {
                source: 'error_tracking',
                ago: { hours: 1 },
                content:
                    'RangeError: Maximum call stack size exceeded\n```\nFunnelEditor in src/scenes/funnels/FunnelEditor.tsx line 66\nuseStepOrder in src/scenes/funnels/useStepOrder.ts line 18\nreorderSteps in src/scenes/funnels/FunnelSteps.tsx line 203\nreorderSteps in src/scenes/funnels/FunnelSteps.tsx line 203\n```',
            },
            {
                source: 'session_replay',
                ago: { hours: 3 },
                sessionId: 'demo-funnel-step-crash-session',
                content: 'Adds a tenth step to a funnel. The page goes blank and the unsaved funnel is lost.',
            },
            {
                source: 'github',
                ago: { hours: 70 },
                content: 'Commit b17d52 "Drag to reorder funnel steps" by Priya Nair, deployed Friday at 4:05 PM.',
            },
        ],
        trace: {
            error: 'RangeError: Maximum call stack size exceeded',
            frames: [
                ['reorderSteps', 'FunnelSteps.tsx:203'],
                ['useStepOrder', 'useStepOrder.ts:18'],
                ['FunnelEditor', 'FunnelEditor.tsx:66'],
            ],
            footer: 'Introduced in b17d52 · Fri 4:05 PM · Priya · "Drag to reorder funnel steps"',
        },
        replay: { meta: 'adds step 10, page goes blank · 0:22', count: 33 },
        facts: [
            ['Where', 'Funnel editor', '/insights/new · 10 or more steps', 'default'],
            ['Since', 'Fri 4:30 PM', 'Saved funnels with 10+ steps down 60%', 'default'],
            ['Impact', '96 users in 41 orgs', 'Unsaved changes are lost on crash', 'default'],
            ['Owner', 'Nobody assigned', '', 'alert'],
        ],
        observation: {
            title: 'Editor crashes on long funnels',
            format: 'count',
            values: [2, 2, 2, 2, 30, 56, 40, 24, 36, 80, 104, 96, 120, 88],
            filters: 2,
        },
        activity: [
            ['PostHog created the report', 'Fri 4:30 PM'],
            ['PostHog linked commit **b17d52** as the likely cause', 'Fri 4:31 PM'],
            ['PostHog attached **33 replays**', 'Today 8:45 AM'],
        ],
        contextNote: 'Sends the trace, the b17d52 diff and 33 replays as context',
        prompt: 'reorderSteps in FunnelSteps.tsx:203 recurses without end on funnels with 10 or more steps. Started after b17d52. Fix it and keep drag to reorder working.',
        handedStage: 'Reading FunnelSteps.tsx · a PR will land here to review',
    },
    {
        id: 'demo-onboarding-drop',
        title: 'Fewer new projects finish setup since the new wizard',
        sourceProduct: 'analytics',
        sourceLabel: 'Product Analytics',
        ago: { days: 5 },
        kind: 'open',
        accent: 'alert',
        headNum: '−18%',
        headRest: 'of new projects send a first event',
        lede: 'Was 64%, now 46%. The drop is at the new "Pick your framework" step.',
        summary: [
            '## Problem',
            'Fewer new projects finish setup since the new setup wizard reached 100% on Tuesday at 10:00 AM. The drop is at step 2 of 4, "Pick your framework". The step shows 40 frameworks in one long list with no search, and the most common choices are below the fold on a laptop screen.',
            '## Impact',
            'The share of new projects that send a first event fell from 64% to 46%. That is about 300 projects a week, mostly self-serve signups. Signups are unchanged, so all of the loss is in setup. 61% of the people who leave do it on "Pick your framework".',
            '## Solution',
            'Add search to the framework list and show the 6 most used frameworks first. Add a "Skip for now" link that goes straight to the snippet, so people who do not know their framework can still finish. Ines owns the wizard. The 45 attached replays show people scrolling the list and leaving.',
        ],
        signals: [
            {
                source: 'session_replay',
                ago: { hours: 10 },
                sessionId: 'demo-onboarding-drop-session',
                content:
                    'Scrolls the framework list for 70 seconds, scrolls back up, and closes the tab without picking one.',
            },
            {
                source: 'analytics',
                ago: { hours: 30 },
                content:
                    'Funnel from signup to first event: 46% this week, 64% in the 4 weeks before. Step 2 conversion fell from 91% to 39%.',
            },
            {
                source: 'analytics',
                ago: { hours: 100 },
                content: 'Feature flag new-setup-wizard rolled out to 100% on Tuesday at 10:00 AM.',
            },
        ],
        replay: { meta: 'scrolls the framework list, leaves · 1:12', count: 45 },
        facts: [
            ['Where', 'Setup · Pick your framework', 'Step 2 of 4', 'default'],
            ['Since', 'Tue 10:00 AM · new wizard at 100%', 'Signups unchanged', 'default'],
            ['Impact', 'About 300 projects a week', 'Mostly self-serve signups', 'default'],
            ['Owner', 'Ines', '', 'default'],
        ],
        observation: {
            title: 'New projects that finish setup',
            format: 'percentage',
            caption: 'Projects that send a first event',
            values: [62.4, 64.8, 60, 66, 63.6, 61.2, 64.8, 48, 45.6, 46.8, 44.4, 45.6, 43.2, 45],
            filters: 1,
        },
        supporting: [
            ['New projects a week', 300, 'count'],
            ['Drop-off at Pick your framework', 61, 'percentage'],
        ],
        activity: [
            ['PostHog created the report', 'Wed 9:30 AM'],
            [`${DEMO_USER_NAME} changed assignee to **Ines Moreau**`, 'Wed 10:12 AM'],
        ],
        contextNote: 'Sends the setup funnel, 45 replays and the wizard step config as context',
        prompt: 'Setup completion fell from 64% to 46% after the new wizard. Most drop-off is at "Pick your framework". Find why and propose a fix.',
        handedStage: 'Reading the setup wizard · a proposal will land here to review',
        owner: { kind: 'user', name: 'Ines Moreau' },
    },
]
