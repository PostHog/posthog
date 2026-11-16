import type { ReportArtefactApi, SignalNodeApi } from '@/api/reports'
import type { ReportPageApi, SignalViewApi } from '@/api/today'

import { reportTaskId, reportView } from './report'
import { reportFixture } from './testFixtures'

// Local-time constructor arguments so the cases hold in any time zone.
const local = (m: number, d: number, h: number, min = 0): string => new Date(2026, m - 1, d, h, min).toISOString()
const NOW = new Date(2026, 9, 9, 12, 0)
const SCOPE = { host: 'https://us.example.com', projectId: 2 }
const ALEX = { uuid: 'u-alex', first_name: 'Alex', last_name: 'Kim', email: 'alex@example.com' }
const SANA = { uuid: 'u-sana', first_name: 'Sana', last_name: 'Patel', email: 'sana@example.com' }

function artefact(overrides: Partial<ReportArtefactApi> & Pick<ReportArtefactApi, 'id' | 'type'>): ReportArtefactApi {
    return {
        content: {},
        created_at: local(10, 9, 9),
        actor_kind: 'system',
        actor_agent: null,
        created_by: null,
        task_id: null,
        ...overrides,
    }
}

function signalView(overrides: Partial<SignalViewApi>): SignalViewApi {
    return {
        signal_id: 's',
        source_product: 'error_tracking',
        source_type: 'issue_spiking',
        content: '',
        timestamp: local(10, 9, 8),
        extra: {},
        headline: '',
        lead: '',
        meta: '',
        recording: null,
        preview: null,
        ...overrides,
    }
}

const PAGE: ReportPageApi = {
    lead: '**3,721 errors** in the report UI since 9 AM. The legend label is undefined.',
    impact_sentence: '612 users in 51 organizations saw a blank chart.',
    evidence: [
        signalView({
            headline: "TypeError: Cannot read 'label' of undefined",
            preview: {
                block: [
                    { text: "TypeError: Cannot read 'label' of undefined", quiet: false },
                    { text: '  ChartLegend.tsx:142  renderLegend', quiet: true },
                ],
                facts: [],
            },
        }),
        signalView({ source_product: 'conversations', lead: 'The chart is empty for me.', meta: 'Ticket #12' }),
        signalView({
            source_product: 'session_replay',
            headline: 'Blank chart after load',
            recording: { session_id: 'sess-1', offset: '0:08', seek_seconds: 3 },
        }),
    ],
    impact_numbers: [],
    last_seen: local(10, 9, 11, 40),
}

describe('report view adapter', () => {
    test('external handoffs use only the latest repository selection, including a cleared selection', () => {
        const input = {
            report: reportFixture(),
            artefacts: [
                artefact({ id: 'new', type: 'repo_selection', content: { repository: 'example/new-app' } }),
                artefact({ id: 'old', type: 'repo_selection', content: { repository: 'example/old-app' } }),
            ],
            ...SCOPE,
            now: NOW,
        }
        expect(reportView(input).repository).toBe('example/new-app')
        input.artefacts[0] = artefact({ id: 'cleared', type: 'repo_selection', content: {} })
        expect(reportView(input).repository).toBeUndefined()
    })

    test('an unidentified external claimant is not named PostHog', () => {
        const view = reportView({
            report: reportFixture({
                assignee: { kind: 'agent', agent: null, user: null, task_id: null, claimed_at: NOW.toISOString() },
            }),
            artefacts: [],
            ...SCOPE,
            now: NOW,
        })
        expect(view.work.assignee?.name).toBe('External agent')
    })

    test('all PRs keep their canonical states, including unknown', () => {
        const pull_requests = ['draft', 'unknown', 'merged'].map((state, index) => ({
            url: `https://github.com/example/app/pull/${index + 1}`,
            id: `pr-${index + 1}`,
            state: state as 'draft' | 'unknown' | 'merged',
            merged: state === 'merged',
            review_decision: null,
        }))
        const view = reportView({
            report: reportFixture({ pull_requests, implementation_pr_url: pull_requests[1]?.url }),
            artefacts: [],
            ...SCOPE,
            now: NOW,
        })
        expect(view.work.pullRequests?.map((pr) => pr.state)).toEqual(['draft', 'unknown', 'merged'])
        expect(view.work.pullRequest).toMatchObject({ id: 'pr-2', state: 'unknown' })
    })

    test('a current external owner prevents following a historical task', () => {
        const history = [
            artefact({
                id: 'old-run',
                type: 'task_run',
                task_id: 'old-task',
                content: { type: 'implementation', task_id: 'old-task' },
            }),
        ]
        const external = reportFixture({
            assignee: { kind: 'agent', agent: 'codex', user: null, task_id: null, claimed_at: NOW.toISOString() },
        })
        expect(reportTaskId(external, history)).toBeUndefined()
        expect(reportTaskId(reportFixture(), history)).toBe('old-task')
    })

    test('builds a claimed report with a Today page, an open PR and a work log', () => {
        const report = reportFixture({
            scout_name: 'signals-scout-error-tracking',
            source_products: ['signals_scout', 'error_tracking', 'session_replay'],
            created_at: local(10, 5, 7, 21),
            work_state: 'in_review',
            assignee: { kind: 'task', user: null, task_id: 'task-1', agent: null, claimed_at: local(10, 9, 9, 12) },
            pull_requests: [
                {
                    url: 'https://github.com/example/app/pull/4190',
                    state: 'open',
                    merged: false,
                    review_decision: 'review_required',
                },
            ],
            implementation_pr_url: 'https://github.com/example/app/pull/4190',
            metrics: [
                {
                    metric_id: 'users',
                    title: 'Affected users',
                    kind: 'affected_users',
                    role: 'primary',
                    value: 612,
                    value_at: local(10, 9, 11),
                    series: [3, 2, 4, 50, 80],
                    value_format: 'count',
                    unit: null,
                    caption: 'Across 51 organizations',
                },
                {
                    metric_id: 'orgs',
                    title: 'Organizations',
                    kind: 'custom',
                    role: 'supporting',
                    value: 51,
                    value_at: local(10, 9, 11),
                    series: null,
                    value_format: 'count',
                    unit: null,
                    caption: null,
                    query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [] } },
                },
            ],
            charts: [
                {
                    chart_id: 'by-browser',
                    title: 'Errors by browser',
                    query: { kind: 'SavedInsightNode', shortId: 'abc123' },
                    caption: null,
                },
            ],
        })
        const artefacts = [
            artefact({
                id: 'a5',
                type: 'suggested_reviewers',
                actor_kind: 'user',
                created_by: ALEX,
                created_at: local(10, 9, 11),
                content: [
                    { user_uuid: 'u-sana', user: SANA, github_login: 'sana', github_name: null },
                    { user_uuid: null, user: null, github_login: 'octo-dev', github_name: null },
                ],
            }),
            artefact({
                id: 'a4',
                type: 'pull_request',
                actor_kind: 'task',
                task_id: 'task-1',
                created_at: local(10, 9, 10),
                content: { url: 'https://github.com/example/app/pull/4190' },
            }),
            artefact({
                id: 'a3',
                type: 'priority_judgment',
                created_at: local(10, 9, 9, 30),
                content: { priority: 'P1' },
            }),
            artefact({
                id: 'a2',
                type: 'work_claim',
                actor_kind: 'task',
                task_id: 'task-1',
                created_at: local(10, 9, 9, 12),
            }),
            artefact({
                id: 'a1',
                type: 'task_run',
                created_at: local(10, 9, 9, 11),
                content: { task_id: 'task-1', product: 'signals', type: 'implementation' },
            }),
        ]
        const view = reportView({
            report,
            artefacts,
            page: PAGE,
            task: {
                id: 'task-1',
                latest_run: { id: 'run-1', status: 'completed', stage: 'PR ready' },
                created_by: { first_name: 'Alex', last_name: 'Kim', email: 'alex@example.com' },
            },
            ...SCOPE,
            now: NOW,
        })

        expect(view.headline).toEqual({ number: '3,721', rest: 'errors in the report UI since 9 AM' })
        expect(view.lede).toBe('612 users in 51 organizations saw a blank chart.')
        expect(view.evidence).toEqual([
            {
                kind: 'trace',
                error: "TypeError: Cannot read 'label' of undefined",
                frames: [{ fn: 'renderLegend', loc: 'ChartLegend.tsx:142' }],
            },
            { kind: 'quotes', quotes: [{ text: 'The chart is empty for me.', who: 'Support · Ticket #12' }] },
            {
                kind: 'replay',
                sessionId: 'sess-1',
                t: 3,
                meta: 'at 0:08 · Blank chart after load',
                count: 1,
                url: 'https://us.example.com/project/2/replay/sess-1?t=3',
            },
        ])
        expect(view.since).toBe('Mon 7:21 AM')
        expect(view.owner).toEqual({ kind: 'agent', name: 'PostHog' })
        expect(view.facts).toEqual([
            { key: 'Impact', title: '612 affected users', sub: 'Across 51 organizations', tone: 'default' },
        ])
        expect(view.activity.map((event) => event.text)).toEqual([
            'PostHog created the report',
            'PostHog started working',
            'Alex Kim handed off to **PostHog**',
            'PostHog opened **PR #4190**',
            'Alex Kim changed reviewers to **Sana Patel, octo-dev**',
        ])
        expect(view.work).toMatchObject({
            state: 'in_review',
            assignee: { kind: 'task', name: 'PostHog', taskId: 'task-1' },
            pullRequest: {
                url: 'https://github.com/example/app/pull/4190',
                number: 4190,
                state: 'open',
                reviewDecision: 'review_required',
            },
        })
        expect(view.task).toEqual({ taskId: 'task-1', runId: 'run-1', status: 'completed', stage: 'PR ready' })
        expect(view.reviewers).toEqual([{ uuid: 'u-sana', name: 'Sana Patel', email: 'sana@example.com' }])
        expect(view).toMatchObject({
            canAct: false,
            accent: 'alert',
            webUrl: 'https://us.example.com/project/2/inbox/reports/00000000-0000-0000-0000-0000000000aa',
            observation: { metricId: 'users', role: 'primary', data: { kind: 'none' } },
            supportingMetrics: [{ metricId: 'orgs', role: 'supporting', data: { kind: 'query' } }],
            charts: [
                {
                    chartId: 'by-browser',
                    title: 'Errors by browser',
                    openUrl: 'https://us.example.com/project/2/insights/abc123',
                },
            ],
        })
        expect(view.charts[0]?.data).toBeUndefined()
    })

    test('falls back to signals for evidence when there is no Today page', () => {
        const signals: SignalNodeApi[] = [
            {
                signal_id: 's1',
                content:
                    'Export crashed for guests.\n```\nexportCsv in posthog/api/export.py line 40\nrender in posthog/api/views.py line 12\n```',
                source_product: 'error_tracking',
                source_type: 'issue_created',
                source_id: 'issue-1',
                timestamp: local(10, 9, 8),
                extra: { fingerprint: 'fp' },
            },
            {
                signal_id: 's2',
                content: 'I cannot download my report. Please help.',
                source_product: 'zendesk',
                source_type: 'ticket',
                source_id: 'ticket-9',
                timestamp: local(10, 9, 8),
                extra: { url: 'https://example.com/ticket/9' },
            },
            {
                signal_id: 's3',
                content: 'User clicked export three times.',
                source_product: 'session_replay',
                source_type: 'session_problem',
                source_id: 'sess-9',
                timestamp: local(10, 9, 8),
                extra: { session_id: 'sess-9' },
            },
        ]
        const view = reportView({ report: reportFixture(), artefacts: [], signals, ...SCOPE, now: NOW })

        expect(view.headline).toEqual({ rest: 'Exports fail for guests' })
        expect(view.lede).toBe('Guests cannot export.')
        expect(view.evidence).toEqual([
            {
                kind: 'trace',
                error: 'Export crashed for guests.',
                frames: [
                    { fn: 'render', loc: 'views.py:12' },
                    { fn: 'exportCsv', loc: 'export.py:40' },
                ],
            },
            { kind: 'quotes', quotes: [{ text: 'I cannot download my report.', who: 'Zendesk' }] },
            {
                kind: 'replay',
                sessionId: 'sess-9',
                meta: 'User clicked export three times.',
                count: 1,
                url: 'https://us.example.com/project/2/replay/sess-9',
            },
        ])
        expect(view.owner).toEqual({ kind: 'none' })
        expect(view.task).toBeUndefined()
        expect(view.canAct).toBe(true)
    })

    test('lists every signal in API order for the full report, also when the Today page supplies the evidence', () => {
        const signal = (overrides: Partial<SignalNodeApi> & Pick<SignalNodeApi, 'signal_id'>): SignalNodeApi => ({
            content: '',
            source_product: 'error_tracking',
            source_type: 'issue_created',
            source_id: overrides.signal_id,
            timestamp: local(10, 9, 8),
            extra: null,
            ...overrides,
        })
        const signals = [
            signal({
                signal_id: 'newest',
                content: '  Blank chart after load.\n',
                source_product: 'replay_vision',
                timestamp: local(10, 9, 11),
                extra: { session_id: 'sess 1' },
            }),
            signal({
                signal_id: 'ticket',
                content: 'The chart is empty for me.',
                source_product: 'zendesk',
                timestamp: local(10, 9, 10),
                extra: { ticket_number: 8812, session_id: '' },
            }),
            signal({ signal_id: 'oldest', content: 'Unknown source.', source_product: 'new_product' }),
        ]

        const view = reportView({ report: reportFixture(), artefacts: [], signals, page: PAGE, ...SCOPE, now: NOW })

        expect(view.signals).toEqual([
            {
                id: 'newest',
                sourceProduct: 'replay_vision',
                sourceLabel: 'Session replay',
                content: 'Blank chart after load.',
                at: local(10, 9, 11),
                sessionId: 'sess 1',
                replayUrl: 'https://us.example.com/project/2/replay/sess%201',
            },
            {
                id: 'ticket',
                sourceProduct: 'zendesk',
                sourceLabel: 'Zendesk',
                content: 'The chart is empty for me.',
                at: local(10, 9, 10),
                ticketNumber: 8812,
            },
            {
                id: 'oldest',
                sourceProduct: 'other',
                sourceLabel: 'Report',
                content: 'Unknown source.',
                at: local(10, 9, 8),
            },
        ])
    })
})
