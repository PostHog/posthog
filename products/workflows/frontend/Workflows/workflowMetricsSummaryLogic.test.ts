import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { AppMetricsTimeSeriesResponse, appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'

import { silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { HogFlow, HogFlowAction } from './hogflows/types'
import { workflowLogic } from './workflowLogic'
import {
    type EmailMetric,
    type EmailMetricName,
    type WorkflowMetricsSummaryLogicProps,
    buildEmailMetricInvocationSearchParams,
    buildEmailMetricRows,
    buildPushMetricRows,
    channelSentLabel,
    detectMessagingChannels,
    parseEmailLinkTotals,
    subtractSeries,
    withDisplayName,
    workflowMetricsSummaryLogic,
} from './workflowMetricsSummaryLogic'

const series = (labels: string[], ...namedValues: [string, number[]][]): AppMetricsTimeSeriesResponse => ({
    labels,
    interval: 'day',
    timezone: 'UTC',
    series: namedValues.map(([name, values]) => ({ name, values })),
})

describe('withDisplayName', () => {
    it.each([
        {
            name: 'returns null for null input',
            input: null,
            displayName: 'Custom',
            expected: null,
        },
        {
            name: 'replaces name on single series',
            input: series(['day1', 'day2'], ['original', [1, 2]]),
            displayName: 'Renamed',
            expected: series(['day1', 'day2'], ['Renamed', [1, 2]]),
        },
        {
            name: 'replaces name on multiple series',
            input: series(['day1'], ['a', [1]], ['b', [2]]),
            displayName: 'All same',
            expected: series(['day1'], ['All same', [1]], ['All same', [2]]),
        },
    ])('$name', ({ input, displayName, expected }) => {
        expect(withDisplayName(input, displayName)).toEqual(expected)
    })
})

describe('subtractSeries', () => {
    it.each([
        {
            name: 'both null returns null',
            minuend: null,
            subtrahend: null,
            displayName: 'Result',
            expected: null,
        },
        {
            name: 'null subtrahend uses zeros',
            minuend: series(['d1', 'd2'], ['sent', [5, 10]]),
            subtrahend: null,
            displayName: 'Delivered',
            expected: series(['d1', 'd2'], ['Delivered', [5, 10]]),
        },
        {
            name: 'null minuend uses zeros',
            minuend: null,
            subtrahend: series(['d1', 'd2'], ['failed', [3, 7]]),
            displayName: 'Delivered',
            expected: series(['d1', 'd2'], ['Delivered', [0, 0]]),
        },
        {
            name: 'subtracts values element-wise',
            minuend: series(['d1', 'd2', 'd3'], ['sent', [10, 20, 30]]),
            subtrahend: series(['d1', 'd2', 'd3'], ['failed', [2, 5, 10]]),
            displayName: 'Delivered',
            expected: series(['d1', 'd2', 'd3'], ['Delivered', [8, 15, 20]]),
        },
        {
            name: 'clamps negative results to zero',
            minuend: series(['d1', 'd2'], ['sent', [1, 0]]),
            subtrahend: series(['d1', 'd2'], ['failed', [5, 3]]),
            displayName: 'Delivered',
            expected: series(['d1', 'd2'], ['Delivered', [0, 0]]),
        },
    ])('$name', ({ minuend, subtrahend, displayName, expected }) => {
        expect(subtractSeries(minuend, subtrahend, displayName)).toEqual(expected)
    })
})

describe('buildEmailMetricInvocationSearchParams', () => {
    const dateFrom = '2026-07-01T00:00:00.000Z'
    const dateTo = '2026-07-13T00:00:00.000Z'

    // Each metric drills into the Invocations tab via the unified search box (`inv_search`), narrowed
    // to the level that distinguishes it: bounced/marked-as-spam at WARN/ERROR, bounce prevented
    // ("Skipping send") at INFO.
    it.each<[EmailMetricName, Record<string, string>]>([
        [
            'email_bounced',
            { inv_date_from: dateFrom, inv_date_to: dateTo, inv_search: 'bounce', inv_log_levels: 'WARN,ERROR' },
        ],
        [
            'email_bounced_hard',
            { inv_date_from: dateFrom, inv_date_to: dateTo, inv_search: 'Permanent bounce', inv_log_levels: 'ERROR' },
        ],
        [
            'email_bounced_transient',
            { inv_date_from: dateFrom, inv_date_to: dateTo, inv_search: 'Transient bounce', inv_log_levels: 'WARN' },
        ],
        [
            'email_bounced_undetermined',
            { inv_date_from: dateFrom, inv_date_to: dateTo, inv_search: 'Undetermined bounce', inv_log_levels: 'WARN' },
        ],
        [
            'email_blocked',
            { inv_date_from: dateFrom, inv_date_to: dateTo, inv_search: 'Complaint', inv_log_levels: 'WARN,ERROR' },
        ],
        [
            'email_bounce_prevented',
            { inv_date_from: dateFrom, inv_date_to: dateTo, inv_search: 'Skipping send', inv_log_levels: 'INFO' },
        ],
        [
            'email_missing_recipient',
            {
                inv_date_from: dateFrom,
                inv_date_to: dateTo,
                inv_search: 'has no email address',
                inv_log_levels: 'WARN',
            },
        ],
        [
            'email_suspended',
            { inv_date_from: dateFrom, inv_date_to: dateTo, inv_search: 'for this project', inv_log_levels: 'WARN' },
        ],
        [
            'message_frequency_capped',
            {
                inv_date_from: dateFrom,
                inv_date_to: dateTo,
                inv_search: 'reached the frequency cap',
                inv_log_levels: 'INFO',
            },
        ],
    ])('maps %s to the expected Invocations-tab params', (metricKey, expected) => {
        expect(buildEmailMetricInvocationSearchParams(metricKey, dateFrom, dateTo)).toEqual(expected)
    })

    it.each<EmailMetric>(['email_sent', 'email_delivered', 'email_opened', 'email_failed'])(
        'returns null for the non-drillable metric %s',
        (metricKey) => {
            expect(buildEmailMetricInvocationSearchParams(metricKey, dateFrom, dateTo)).toBeNull()
        }
    )
})

describe('detectMessagingChannels', () => {
    // Only the `*_sent` series flip a channel on — this guards the exact metric names the tile keys off.
    it.each([
        { name: 'no trends', input: null, expected: { hasEmail: false, hasPush: false } },
        {
            name: 'email only',
            input: series(['d1'], ['email_sent', [3]]),
            expected: { hasEmail: true, hasPush: false },
        },
        { name: 'push only', input: series(['d1'], ['push_sent', [2]]), expected: { hasEmail: false, hasPush: true } },
        {
            name: 'both channels',
            input: series(['d1'], ['email_sent', [3]], ['push_sent', [2]]),
            expected: { hasEmail: true, hasPush: true },
        },
        {
            name: 'ignores non-sent series',
            input: series(['d1'], ['email_delivered', [3]], ['push_skipped', [1]]),
            expected: { hasEmail: false, hasPush: false },
        },
    ])('$name', ({ input, expected }) => {
        expect(detectMessagingChannels(input)).toEqual(expected)
    })
})

describe('channelSentLabel', () => {
    it.each([
        [{ hasEmail: true, hasPush: true }, 'Messages sent'],
        [{ hasEmail: false, hasPush: true }, 'Push notifications sent'],
        [{ hasEmail: true, hasPush: false }, 'Emails sent'],
        [{ hasEmail: false, hasPush: false }, 'Emails sent'],
    ])('%o -> %s', (channels, expected) => {
        expect(channelSentLabel(channels)).toBe(expected)
    })
})

describe('buildEmailMetricRows', () => {
    it('maps each metric key onto the row, preferring the reported email_delivered', () => {
        const rows = buildEmailMetricRows([{ id: 'a1', name: 'Welcome email' }], {
            a1: {
                email_sent: 100,
                email_delivered: 85, // reported value wins over the derived sent - bounced (= 94)
                email_opened: 40,
                email_link_clicked: 12,
                email_bounced: 6,
                email_bounced_hard: 4,
                email_bounced_transient: 2,
                email_bounce_prevented: 2,
                email_missing_recipient: 5,
                message_frequency_capped: 3,
                email_blocked: 4,
                email_untracked: 7,
            },
        })
        expect(rows).toEqual([
            {
                id: 'a1',
                email: 'Welcome email',
                sent: 100,
                delivered: 85,
                opened: 40,
                linkClicked: 12,
                bounced: 6,
                bouncedHard: 4,
                bouncedSoft: 2,
                bouncedUnknown: 0,
                bouncePrevented: 2,
                missingRecipient: 5,
                frequencyCapped: 3,
                markedAsSpam: 4,
                untracked: 7,
                trackedSends: 93,
            },
        ])
    })

    it('keeps tracked sends positive when untracked sends outnumber deliveries', () => {
        const [row] = buildEmailMetricRows([{ id: 'a1', name: 'E' }], {
            a1: { email_sent: 100, email_delivered: 60, email_untracked: 90, email_bounced: 40 },
        })
        expect(row.trackedSends).toBe(10)
    })

    // delivered falls back to sent - bounced (clamped at 0) when it wasn't collected. Spam
    // complaints (email_blocked) are post-delivery reports, so they must not reduce delivered.
    it.each<{ totals: Partial<Record<EmailMetric, number>>; delivered: number }>([
        { totals: { email_sent: 10, email_bounced: 3, email_blocked: 2 }, delivered: 7 },
        { totals: { email_sent: 1, email_bounced: 5 }, delivered: 0 },
        { totals: {}, delivered: 0 },
    ])('derives delivered=$delivered when email_delivered is absent', ({ totals, delivered }) => {
        expect(buildEmailMetricRows([{ id: 'a1', name: 'E' }], { a1: totals })[0].delivered).toBe(delivered)
    })
})

describe('buildPushMetricRows', () => {
    it('maps sent/skipped/failed/opened per action and defaults missing totals to 0', () => {
        const rows = buildPushMetricRows(
            [
                { id: 'p1', name: 'Reminder' },
                { id: 'p2', name: 'Promo' },
            ],
            { p1: { push_sent: 50, push_skipped: 20, push_failed: 3, push_opened: 12 } }
        )
        expect(rows).toEqual([
            { id: 'p1', push: 'Reminder', sent: 50, skipped: 20, failed: 3, opened: 12 },
            { id: 'p2', push: 'Promo', sent: 0, skipped: 0, failed: 0, opened: 0 },
        ])
    })
})

describe('parseEmailLinkTotals', () => {
    const totals = (...instanceIds: [string, number][]): Record<string, { total: number; breakdowns: string[] }> =>
        Object.fromEntries(instanceIds.map(([id, total]) => [id, { total, breakdowns: [id] }]))

    it('groups links under their action, most clicked first', () => {
        expect(
            parseEmailLinkTotals(
                totals(
                    ['act-1|0|https://example.com/a', 3],
                    ['act-1|1|https://example.com/b', 9],
                    ['act-2|0|https://example.com/c', 1]
                )
            )
        ).toEqual({
            'act-1': [
                { linkIndex: '1', url: 'https://example.com/b', clicks: 9, truncated: false, duplicateUrl: false },
                { linkIndex: '0', url: 'https://example.com/a', clicks: 3, truncated: false, duplicateUrl: false },
            ],
            'act-2': [
                { linkIndex: '0', url: 'https://example.com/c', clicks: 1, truncated: false, duplicateUrl: false },
            ],
        })
    })

    it('keeps a url containing the field separator intact', () => {
        expect(parseEmailLinkTotals(totals(['act-1|0|https://example.com/a|b', 2]))['act-1']).toEqual([
            { linkIndex: '0', url: 'https://example.com/a|b', clicks: 2, truncated: false, duplicateUrl: false },
        ])
    })

    it('flags links that share a url within a step, so position can tell them apart', () => {
        const rows = parseEmailLinkTotals(
            totals(
                ['act-1|0|https://example.com/a', 4],
                ['act-1|7|https://example.com/a', 1],
                ['act-1|2|https://example.com/b', 2]
            )
        )['act-1']
        expect(rows.map((r) => [r.linkIndex, r.duplicateUrl])).toEqual([
            ['0', true],
            ['2', false],
            ['7', true],
        ])
    })

    it('flags a url stored at the length cap as truncated', () => {
        const longUrl = `https://example.com/${'x'.repeat(200)}`.slice(0, 200)
        expect(parseEmailLinkTotals(totals([`act-1|0|${longUrl}`, 1]))['act-1'][0].truncated).toBe(true)
    })

    it.each([
        ['an instance id with no link fields', 'act-1'],
        ['an instance id missing the url field', 'act-1|0'],
        ['an empty url', 'act-1|0|'],
    ])('ignores %s', (_name, instanceId) => {
        expect(parseEmailLinkTotals(totals([instanceId, 5]))).toEqual({})
    })
})

describe('workflowMetricsSummaryLogic', () => {
    const WORKFLOW_ID = 'wf-metrics'
    const LOGIC_KEY = `hog-flow-metrics-${WORKFLOW_ID}`
    const LABELS = ['2026-11-01', '2026-11-02']
    const NEW_RANGE = { dateFrom: '2026-09-01T00:00:00.000Z', dateTo: '2026-09-08T00:00:00.000Z' }

    type MetricRow = { instanceId: string; metricName: string; count: number }

    const step = (id: string, type: 'function_email' | 'function_push'): HogFlowAction =>
        ({ id, type, name: id, description: '', created_at: 0, updated_at: 0, config: { inputs: {} } }) as HogFlowAction

    const makeWorkflow = (actions: HogFlowAction[], overrides: Partial<HogFlow> = {}): HogFlow =>
        ({
            id: WORKFLOW_ID,
            name: 'Metrics',
            actions,
            edges: [],
            conversion: { filters: [] },
            exit_condition: 'exit_only_at_end',
            version: 1,
            status: 'active',
            team_id: 1,
            trigger: { type: 'event', filters: {} },
            ...overrides,
        }) as HogFlow

    let queries: string[]
    let servedWorkflow: HogFlow

    // A stand-in for the app_metrics table: it applies the metric-name and run-level filters the
    // query asks for, then groups by the requested breakdown columns.
    const serveAppMetrics = (rows: MetricRow[], failWhen?: string): void => {
        queries = []
        jest.spyOn(api, 'queryHogQL').mockImplementation(async (query) => {
            const sql = String(query)
            queries.push(sql)
            if (failWhen && sql.includes(failWhen)) {
                throw new Error('query failed')
            }
            const nameList = sql.match(/metric_name IN \[([^\]]*)\]/)?.[1] ?? ''
            const names = [...nameList.matchAll(/'([^']*)'/g)].map((m) => m[1])
            const matching = rows.filter(
                (r) =>
                    (names.length === 0 || names.includes(r.metricName)) &&
                    (!sql.includes("instance_id = ''") || r.instanceId === '')
            )
            const totalsBreakdown = sql.match(/sum\(count\) AS total,\s*([\w, ]+)\n/)?.[1]
            const columns = totalsBreakdown ? totalsBreakdown.split(',').map((c) => c.trim()) : ['metric_name']
            const groups = new Map<string, { keys: string[]; total: number }>()
            matching.forEach((r) => {
                const keys = columns.map((c) => (c === 'instance_id' ? r.instanceId : r.metricName))
                const group = groups.get(keys.join('|')) ?? { keys, total: 0 }
                group.total += r.count
                groups.set(keys.join('|'), group)
            })
            const results = [...groups.values()].map(({ keys, total }) =>
                totalsBreakdown ? [total, ...keys] : [LABELS, keys[0], [total, 0]]
            )
            return { results } as any
        })
    }

    const mountMetrics = async (
        workflow: HogFlow,
        props: Partial<WorkflowMetricsSummaryLogicProps> = {}
    ): Promise<ReturnType<typeof workflowMetricsSummaryLogic.build>> => {
        servedWorkflow = workflow
        const flowLogic = workflowLogic({ id: WORKFLOW_ID })
        flowLogic.mount()
        await expectLogic(flowLogic).toDispatchActions(['loadWorkflowSuccess'])
        const trendsLogic = appMetricsLogic({
            logicKey: LOGIC_KEY,
            loadOnMount: true,
            defaultParams: { dateFrom: '2026-10-01T00:00:00Z', dateTo: '2026-10-08T00:00:00Z' },
            forceParams: { appSource: 'hog_flow', appSourceId: WORKFLOW_ID, breakdownBy: 'metric_name' },
        })
        trendsLogic.mount()
        const logic = workflowMetricsSummaryLogic({ logicKey: LOGIC_KEY, id: WORKFLOW_ID, ...props })
        logic.mount()
        await expectLogic(trendsLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()
        return logic
    }

    beforeEach(() => {
        initKeaTests()
        useMocks({ get: { '/api/environments/:team_id/hog_flows/:id/': () => [200, servedWorkflow] } })
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('totals each email and push step of the workflow', async () => {
        serveAppMetrics([
            { instanceId: 'email-1', metricName: 'email_sent', count: 100 },
            { instanceId: 'email-1', metricName: 'email_bounced', count: 6 },
            { instanceId: 'email-1', metricName: 'email_opened', count: 30 },
            { instanceId: 'email-1|0|https://example.com/a', metricName: 'email_link_clicked_by_link', count: 5 },
            { instanceId: 'push-1', metricName: 'push_sent', count: 40 },
            { instanceId: 'push-1', metricName: 'push_failed', count: 2 },
        ])
        const logic = await mountMetrics(
            makeWorkflow([step('email-1', 'function_email'), step('push-1', 'function_push')])
        )

        expect(logic.values.emailMetricsRows).toEqual([
            expect.objectContaining({ id: 'email-1', sent: 100, delivered: 94, opened: 30, bounced: 6 }),
        ])
        expect(logic.values.pushMetricsRows).toEqual([
            { id: 'push-1', push: 'push-1', sent: 40, skipped: 0, failed: 2, opened: 0 },
        ])
        expect(logic.values.emailLinkTotalsByActionId).toEqual({
            'email-1': [expect.objectContaining({ url: 'https://example.com/a', clicks: 5 })],
        })
        // The per-step queries return one row per (step, metric), past the query's default row cap.
        expect(queries.filter((q) => q.includes("'push_sent'")).join()).toContain('LIMIT 10000')
        expect(queries.filter((q) => q.includes("'email_sent'")).join()).toContain('LIMIT 10000')
        expect(queries.filter((q) => q.includes('email_link_clicked_by_link')).join()).toContain('LIMIT 1000')
    })

    it.each([
        { name: 'divides conversions by runs started', conversions: 3, triggered: 12, rate: 0.25 },
        { name: 'reads 0 when no run started', conversions: 3, triggered: 0, rate: 0 },
    ])('conversion rate $name', async ({ conversions, triggered, rate }) => {
        serveAppMetrics([
            { instanceId: 'exit_node', metricName: 'conversion', count: conversions },
            { instanceId: 'trigger_node', metricName: 'triggered', count: triggered },
        ])
        const logic = await mountMetrics(makeWorkflow([]))

        expect(logic.values.conversionStats).toEqual({ conversions, started: triggered })
        expect(logic.values.conversionRate).toBe(rate)
    })

    it.each([
        { name: 'runs started minus runs finished', triggered: 10, finished: 4, inProgress: 6 },
        { name: 'never below 0', triggered: 2, finished: 5, inProgress: 0 },
    ])('in-progress total is $name', async ({ triggered, finished, inProgress }) => {
        serveAppMetrics([
            { instanceId: 'trigger_node', metricName: 'triggered', count: triggered },
            { instanceId: '', metricName: 'succeeded', count: finished },
            // A step's own success is not a finished run.
            { instanceId: 'email-1', metricName: 'succeeded', count: 50 },
        ])
        const logic = await mountMetrics(makeWorkflow([]))

        expect(logic.values.inProgressTotal).toBe(inProgress)
    })

    it.each([
        { failing: "'email_sent'", flag: 'messageTotalsFailed' as const },
        { failing: "'push_sent'", flag: 'messageTotalsFailed' as const },
        { failing: "['conversion']", flag: 'conversionStatsFailed' as const },
    ])('$flag holds while the $failing query fails and clears on a successful reload', async ({ failing, flag }) => {
        silenceKeaLoadersErrors()
        serveAppMetrics([], failing)
        const logic = await mountMetrics(
            makeWorkflow([step('email-1', 'function_email'), step('push-1', 'function_push')])
        )
        expect(logic.values[flag]).toBe(true)

        serveAppMetrics([
            { instanceId: 'email-1', metricName: 'email_sent', count: 3 },
            { instanceId: 'push-1', metricName: 'push_sent', count: 4 },
        ])
        appMetricsLogic({ logicKey: LOGIC_KEY }).actions.setParams(NEW_RANGE)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values[flag]).toBe(false)
        expect([logic.values.emailMetricsRows[0].sent, logic.values.pushMetricsRows[0].sent]).toEqual([3, 4])
    })

    it.each([
        { tab: 'Metrics tab', overview: false, pushSteps: ['push-1'], linkLoads: 2, completedFrom: NEW_RANGE.dateFrom },
        { tab: 'overview', overview: true, pushSteps: [], linkLoads: 0, completedFrom: '-7d' },
    ])(
        'the $tab reads its own workflow version and range',
        async ({ overview, pushSteps, linkLoads, completedFrom }) => {
            serveAppMetrics([])
            const live = makeWorkflow([step('email-1', 'function_email')], {
                draft: { actions: [step('email-1', 'function_email'), step('push-1', 'function_push')] },
            })
            const logic = await mountMetrics(live, { overview })
            appMetricsLogic({ logicKey: LOGIC_KEY }).actions.setParams(NEW_RANGE)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.pushActions.map((a) => a.id)).toEqual(pushSteps)
            expect(queries.filter((q) => q.includes('email_link_clicked_by_link'))).toHaveLength(linkLoads)
            const reloadedTotals = ["'email_sent'", "'push_sent'", "['conversion']", 'email_link_clicked_by_link']
                .map((marker) => queries.filter((q) => q.includes(marker) && q.includes('sum(count) AS total,')))
                .filter((sent) => sent.length > 0)
                .map((sent) => sent[sent.length - 1])
            expect(reloadedTotals).toHaveLength(overview ? 3 : 4)
            reloadedTotals.forEach((q) => expect(q).toContain(`toDateTime('${NEW_RANGE.dateFrom}'`))
            const completedKey = `workflow-completed-${overview ? 'overview-' : ''}${WORKFLOW_ID}`
            const completedLogic = appMetricsLogic({ logicKey: completedKey })
            expect(completedLogic.values.params.dateFrom).toBe(completedFrom)
            expect(completedLogic.values.appMetricsTrends === null).toBe(overview)
        }
    )

    it.each([
        {
            name: 'splits sent by channel when both send',
            steps: [step('email-1', 'function_email'), step('push-1', 'function_push')],
            sending: ['email', 'push'],
            sent: { 'Emails sent': [8, 0], 'Push notifications sent': [5, 0] },
        },
        {
            name: 'labels sent by the only channel',
            steps: [step('push-1', 'function_push')],
            sending: ['push'],
            sent: { 'Push notifications sent': [5, 0] },
        },
        {
            name: 'keeps a configured channel that has not sent yet',
            steps: [step('email-1', 'function_email'), step('push-1', 'function_push')],
            sending: ['push'],
            sent: { 'Emails sent': [0, 0], 'Push notifications sent': [5, 0] },
        },
        {
            name: 'adds email that sent from a since-deleted step',
            steps: [step('push-1', 'function_push')],
            sending: ['email', 'push'],
            sent: { 'Emails sent': [8, 0], 'Push notifications sent': [5, 0] },
        },
        {
            name: 'adds push that sent from a since-deleted step',
            steps: [step('email-1', 'function_email')],
            sending: ['email', 'push'],
            sent: { 'Emails sent': [8, 0], 'Push notifications sent': [5, 0] },
        },
    ])('summary trends $name', async ({ steps, sending, sent }) => {
        const sends: MetricRow[] = [
            { instanceId: 'email-1', metricName: 'email_sent', count: 8 },
            { instanceId: 'push-1', metricName: 'push_sent', count: 5 },
        ]
        serveAppMetrics([
            { instanceId: 'trigger_node', metricName: 'triggered', count: 10 },
            ...sends.filter((row) => sending.some((channel) => row.metricName.startsWith(channel))),
            { instanceId: '', metricName: 'succeeded', count: 4 },
            { instanceId: 'email-1', metricName: 'succeeded', count: 50 },
            { instanceId: 'exit_node', metricName: 'conversion', count: 2 },
        ])
        const logic = await mountMetrics(makeWorkflow(steps))

        expect(logic.values.workflowSummaryTrends).toEqual({
            labels: LABELS,
            interval: 'day',
            timezone: 'UTC',
            series: [
                { name: 'Workflows started', values: [10, 0] },
                ...Object.entries(sent).map(([name, values]) => ({ name, values })),
                { name: 'Workflows completed', values: [4, 0] },
                { name: 'Workflows converted', values: [2, 0] },
            ],
        })
    })

    it.each([
        { name: 'no goal', conversion: { filters: [] }, expected: false },
        { name: 'a property goal', conversion: { filters: [{ key: 'plan' }] }, expected: true },
        { name: 'an event goal', conversion: { filters: [], events: [{ id: 'purchase' }] }, expected: true },
    ])('shows conversion tiles for $name: $expected', async ({ conversion, expected }) => {
        serveAppMetrics([])
        const logic = await mountMetrics(makeWorkflow([], { conversion } as Partial<HogFlow>))

        expect(logic.values.hasConversionGoal).toBe(expected)
    })

    it('links converted users to this workflow’s conversion events', async () => {
        serveAppMetrics([])
        const logic = await mountMetrics(makeWorkflow([]))

        const hash = new URLSearchParams(logic.values.convertedUsersUrl.split('#')[1])
        const { source } = JSON.parse(hash.get('q') ?? '{}')
        expect(source).toMatchObject({
            event: '$workflows_conversion',
            properties: [{ key: '$workflow_id', value: WORKFLOW_ID }],
        })
    })
})
