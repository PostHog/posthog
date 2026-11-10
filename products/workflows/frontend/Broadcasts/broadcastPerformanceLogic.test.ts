import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import type { MockSignature } from '~/mocks/utils'
import type { HogQLQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { broadcastPerformanceLogic, sendActivityParams } from './broadcastPerformanceLogic'

interface AppMetricRow {
    app_source_id: string
    metric_name: string
    instance_id: string
    count: number
}

interface LogEntryRow {
    log_source_id: string
    level: string
    timestamp: string
    message: string
}

// Answers HogQL queries from in-memory app_metrics and log_entries rows, applying the clauses the query states.
// A clause it can't evaluate fails the request, so a query it doesn't understand can't pass silently.
function hogQLFake(appMetrics: AppMetricRow[], logEntries: LogEntryRow[]): MockSignature {
    return async ({ request }) => {
        const sql = ((await request.json()) as { query: { query: string } }).query.query
        const matches = (column: string, value: string): boolean => {
            const wanted = sql.match(new RegExp(`\\b${column} = '([^']*)'`))?.[1]
            return wanted === undefined || wanted === value
        }
        if (/FROM app_metrics/.test(sql)) {
            const metricNames = sql.match(/metric_name IN \[([^\]]*)\]/)?.[1].match(/'[^']*'/g)
            const groupBy =
                sql
                    .match(/GROUP BY ([\w, ]+)/)?.[1]
                    .trim()
                    .split(/,\s*/) ?? []
            if (groupBy.some((column) => column !== 'metric_name' && column !== 'instance_id')) {
                return [400, { detail: `Unexpected GROUP BY ${groupBy.join(', ')}` }]
            }
            const totals = new Map<string, [number, ...string[]]>()
            for (const row of appMetrics) {
                if (!matches('app_source_id', row.app_source_id)) {
                    continue
                }
                if (metricNames && !metricNames.includes(`'${row.metric_name}'`)) {
                    continue
                }
                const groups = groupBy.map((column) => row[column as 'metric_name' | 'instance_id'])
                const total = totals.get(groups.join('\0'))?.[0] ?? 0
                totals.set(groups.join('\0'), [total + row.count, ...groups])
            }
            return [200, { results: [...totals.values()] }]
        }
        if (/FROM log_entries/.test(sql)) {
            const order = sql.match(/ORDER BY (.*?)\s+LIMIT (\d+)/s)
            const keys = (order?.[1].split(/,\s*(?![^(]*\))/) ?? []).map((term) => {
                const prefix = term.match(/^startsWith\(message, '([^']*)'\) DESC$/)?.[1]
                if (prefix !== undefined) {
                    return (row: LogEntryRow): number => (row.message.startsWith(prefix) ? 1 : 0)
                }
                if (term === 'timestamp DESC') {
                    return (row: LogEntryRow): number => Date.parse(row.timestamp)
                }
                throw new Error(`Unexpected ORDER BY term ${term}`)
            })
            const rows = logEntries
                .filter((row) => matches('log_source_id', row.log_source_id))
                .filter((row) => !/lower\(level\) = 'error'/.test(sql) || row.level.toLowerCase() === 'error')
                .sort((a, b) => {
                    for (const key of keys) {
                        if (key(a) !== key(b)) {
                            return key(b) - key(a)
                        }
                    }
                    return 0
                })
                .slice(0, order ? Number(order[2]) : undefined)
            return [200, { results: rows.map((row) => [row.message]) }]
        }
        return [400, { detail: 'Unexpected table' }]
    }
}

describe('sendActivityParams', () => {
    const started = '2026-09-20T09:17:00Z'

    it.each([
        {
            name: 'a send from earlier today',
            now: '2026-09-20T15:00:00Z',
            interval: 'hour',
            dateFrom: '2026-09-20T09:17:00.000Z',
        },
        {
            name: 'a send from last week',
            now: '2026-09-27T15:00:00Z',
            interval: 'day',
            dateFrom: '2026-09-20T09:17:00.000Z',
        },
    ])('charts $name by $interval from the run start, scoped to the run', ({ now, interval, dateFrom }) => {
        expect(sendActivityParams('run-1', started, dayjs(now))).toMatchObject({
            appSource: 'hog_flow',
            appSourceId: 'run-1',
            interval,
            dateFrom,
        })
    })
})

describe('broadcastPerformanceLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        { name: 'every send went out with tracking off', untracked: 49, trackingOff: true },
        { name: 'some sends had tracking on', untracked: 20, trackingOff: false },
        { name: 'every send had tracking on', untracked: 0, trackingOff: false },
    ])('reports tracking off only when $name', async ({ untracked, trackingOff }) => {
        jest.spyOn(api, 'queryHogQL').mockImplementation(
            async (query) =>
                ({
                    results: String(query).includes('email_link_clicked_by_link')
                        ? []
                        : [
                              [49, 'email_sent'],
                              [49, 'email_delivered'],
                              [untracked, 'email_untracked'],
                          ],
                }) as HogQLQueryResponse
        )
        const logic = broadcastPerformanceLogic({ runId: 'run-1', runStartedAt: '2026-10-19T22:28:56Z' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadTotalsSuccess']).toMatchValues({ trackingOff })
        expect(logic.values.stats?.sent).toEqual(49)
    })

    it.each(['email', 'push'] as const)(
        'counts %s sends that stopped at an error before reaching the provider, and says why',
        async (channel) => {
            const runId = `run-errored-${channel}`
            useMocks({
                post: {
                    '/api/environments/:team_id/query/:kind/': hogQLFake(
                        [
                            // An aborting step records `failed` at step and run level, so the run-level row must not count twice.
                            { app_source_id: runId, metric_name: 'failed', instance_id: 'step_1', count: 245 },
                            { app_source_id: runId, metric_name: 'failed', instance_id: '', count: 245 },
                            { app_source_id: 'another-run', metric_name: 'failed', instance_id: 'step_1', count: 7 },
                        ],
                        [
                            {
                                log_source_id: runId,
                                level: 'ERROR',
                                timestamp: '2026-10-19T22:29:00Z',
                                message:
                                    '[Action:step_1] Errored: Error: invalid value expression: "person.name |", line:3, col:1',
                            },
                            {
                                log_source_id: runId,
                                level: 'ERROR',
                                timestamp: '2026-10-19T22:29:01Z',
                                message: 'Workflow run aborted: socket hang up',
                            },
                            {
                                log_source_id: runId,
                                level: 'INFO',
                                timestamp: '2026-10-19T22:29:02Z',
                                message: '[Action:step_1] Errored: Error: Failed to send email via SES',
                            },
                            {
                                log_source_id: 'another-run',
                                level: 'ERROR',
                                timestamp: '2026-10-19T22:29:03Z',
                                message: '[Action:step_1] Errored: Error: Email integration not found',
                            },
                        ]
                    ),
                },
            })
            const logic = broadcastPerformanceLogic({ runId, runStartedAt: '2026-10-19T22:28:56Z', channel })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadTotalsSuccess', 'loadLatestErrorLogSuccess'])
            expect(logic.values.stats).toMatchObject({ sent: 0, failed: 0 })
            expect(logic.values.sendCounts).toEqual({ sent: 0, notSent: 245 })
            expect(logic.values.sendError).toEqual({
                kind: 'content',
                reason: "A merge tag can't be read",
                tag: '{{ person.name | }}',
                nextStep: `Check the tag in the ${channel === 'push' ? 'notification' : 'email'} for typos.`,
            })
        }
    )

    it.each([
        {
            name: 'a send that counted people',
            runStartedAt: '2026-11-10T22:28:56Z',
            totals: [
                [10, 'email_sent'],
                [5, 'email_opened'],
                [8, 'email_link_clicked'],
                [4, 'email_opened_by_person'],
                [1, 'email_clicked_by_person'],
            ],
            expected: { opened: 4, clicked: 1, engagementCountsPeople: true },
        },
        {
            name: 'an older send that only counted events',
            runStartedAt: '2026-10-19T22:28:56Z',
            totals: [
                [10, 'email_sent'],
                [5, 'email_opened'],
                [8, 'email_link_clicked'],
            ],
            expected: { opened: 5, clicked: 8, engagementCountsPeople: false },
        },
        {
            name: 'an older send with a late open',
            runStartedAt: '2026-10-19T22:28:56Z',
            totals: [
                [10, 'email_sent'],
                [5, 'email_opened'],
                [8, 'email_link_clicked'],
                [1, 'email_opened_by_person'],
            ],
            expected: { opened: 5, clicked: 8, engagementCountsPeople: false },
        },
    ])('reports opens and clicks for $name', async ({ runStartedAt, totals, expected }) => {
        jest.spyOn(api, 'queryHogQL').mockImplementation(
            async (query) =>
                ({ results: String(query).includes('email_link_clicked_by_link') ? [] : totals }) as HogQLQueryResponse
        )
        const logic = broadcastPerformanceLogic({
            runId: `run-${totals.length}-${expected.opened}`,
            runStartedAt,
        })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadTotalsSuccess'])
        expect(logic.values.stats).toMatchObject(expected)
    })

    it('does not report tracking off before anything was sent', async () => {
        jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as unknown as HogQLQueryResponse)
        const logic = broadcastPerformanceLogic({ runId: 'run-2', runStartedAt: '2026-10-19T22:28:56Z' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadTotalsSuccess'])
        expect(logic.values.trackingOff).toBe(false)
    })
})
