import { MCP_VIA, POSTHOG_AGENT } from '@/model/agent'
import type { Accent, Fact, SourceProduct } from '@/model/types'

export type DemoAgo = { hours: number } | { days: number }

export type DemoKind = 'done' | 'open' | 'decision' | 'pr_ready'

/** `[text with **bold**, when, via?]`. `when` is "Today 9:04 AM" or "Mon 7:21 AM". */
export type DemoActivity = readonly [text: string, when: string, via?: string]

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
    metric: { label: string; range: string; bars: readonly (readonly [value: number, hot: 0 | 1])[] }
    activity: readonly DemoActivity[]
    contextNote: string
    prompt?: string
    handedStage: string
    owner?: { kind: 'user' | 'task'; name: string }
}

export const DEMO_USER_NAME = 'Alex Kim'
export const DEMO_PROJECT_NAME = 'posthog'
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
    if (/chris/i.test(answer)) {
        return 'Asking Chris in the thread · keeps going on the UI side'
    }
    return 'Guarding the undefined label in ChartLegend · PR in about 15 min'
}

export const DEMO_BRIEFINGS: readonly DemoBriefing[] = [
    {
        id: 'demo-guest-404s',
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
        metric: {
            label: 'GUEST 404S',
            range: 'Sun → now',
            bars: [
                [2, 0],
                [2, 0],
                [36, 1],
                [84, 1],
                [120, 1],
                [104, 1],
                [88, 1],
                [66, 1],
                [40, 1],
                [18, 1],
                [2, 0],
                [2, 0],
                [2, 0],
                [2, 0],
            ],
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
            footer: 'Introduced in a3f9e1 · 8:52 AM · Chris · "Refactor legend series mapping"',
        },
        facts: [
            ['Where', 'Reports with a custom legend', 'Route /reports/:id · Chrome 130, 94%', 'default'],
            ['Since', '9:04 AM · 12 min after the deploy', 'Report views down 31% by 11:30 AM', 'default'],
            ['Impact', '612 users in 51 orgs', 'Acme Corp and Northwind renew this quarter', 'default'],
            ['Owner', 'Nobody assigned', '', 'alert'],
        ],
        metric: {
            label: 'ERRORS TODAY',
            range: '6 AM → now',
            bars: [
                [3, 0],
                [2, 0],
                [4, 0],
                [3, 0],
                [2, 0],
                [3, 0],
                [48, 1],
                [76, 1],
                [92, 1],
                [104, 1],
                [98, 1],
                [112, 1],
                [120, 1],
                [110, 1],
            ],
        },
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
        metric: {
            label: 'P95 LOAD TIME',
            range: 'Fri → now',
            bars: [
                [50, 0],
                [52, 0],
                [48, 0],
                [54, 0],
                [50, 0],
                [52, 0],
                [49, 0],
                [96, 1],
                [110, 1],
                [104, 1],
                [118, 1],
                [112, 1],
                [120, 1],
                [116, 1],
            ],
        },
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
            footer: 'Introduced in 7d2c04 · Mon 2:30 PM · Chris · PR #4182 "Simplify issue header"',
        },
        replay: { meta: 'hunts for Resolve · 0:19', count: 21 },
        facts: [
            ['Where', 'Issue header', '/issues/:id · all browsers', 'default'],
            ['Since', 'Mon 2:31 PM', '3 support tickets since: "Where did the resolve button go?"', 'default'],
            ['Impact', '340 users in 60 orgs', 'Everyone who triages issues', 'default'],
            ['Owner', 'Nobody assigned', '', 'alert'],
        ],
        metric: {
            label: 'RESOLVE CLICKS',
            range: 'Last week → now',
            bars: [
                [96, 0],
                [104, 0],
                [88, 0],
                [110, 0],
                [92, 0],
                [100, 0],
                [98, 0],
                [2, 1],
                [2, 1],
                [2, 1],
                [2, 1],
                [2, 1],
                [2, 1],
                [2, 1],
            ],
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
        metric: {
            label: 'EMAILS SENT',
            range: 'Last week → now',
            bars: [
                [88, 0],
                [92, 0],
                [90, 0],
                [94, 0],
                [86, 0],
                [96, 0],
                [90, 0],
                [92, 0],
                [2, 1],
                [2, 1],
                [2, 1],
                [2, 1],
                [2, 1],
                [2, 1],
            ],
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
        metric: {
            label: 'RAGE CLICKS',
            range: 'Fri → now',
            bars: [
                [34, 0],
                [38, 0],
                [32, 0],
                [40, 0],
                [36, 0],
                [34, 0],
                [38, 0],
                [72, 1],
                [96, 1],
                [104, 1],
                [112, 1],
                [120, 1],
                [108, 1],
                [116, 1],
            ],
        },
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
            ['Owner', 'Unscoped', '', 'agent'],
        ],
        metric: {
            label: 'REQUESTS',
            range: 'Thu → now',
            bars: [
                [2, 0],
                [2, 0],
                [2, 0],
                [2, 0],
                [2, 0],
                [2, 0],
                [2, 0],
                [2, 0],
                [34, 1],
                [34, 1],
                [68, 1],
                [34, 1],
                [68, 1],
                [2, 1],
            ],
        },
        activity: [
            ['PostHog created the report', 'Thu 4:52 PM'],
            ['PostHog attached **2 survey replies**', 'Today 8:20 AM'],
        ],
        contextNote: 'Sends the 7 quotes, the orgs and the Export code path as context',
        prompt: '7 customers asked to copy a report as an image to the clipboard. Export already renders a PNG server-side. Scope a Copy image button on top of it.',
        handedStage: 'Reading the Export code path · a spec will land here to review',
    },
]
