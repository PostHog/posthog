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
