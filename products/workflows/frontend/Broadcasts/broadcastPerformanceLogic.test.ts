import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import type { MockSignature } from '~/mocks/utils'
import type { HogQLQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { broadcastPerformanceLogic, sendActivityParams } from './broadcastPerformanceLogic'

type Row = Record<string, string | number>

function wherePredicate(term: string, columns: string[], dateFrom: string | undefined): ((row: Row) => boolean) | null {
    const timestampOf = (row: Row): number => Date.parse(String(row.timestamp))
    const equals = term.match(/^(?:lower\((\w+)\)|(\w+)) = '([^']*)'$/)
    const equalsColumn = equals?.[1] ?? equals?.[2]
    if (equals && equalsColumn && columns.includes(equalsColumn)) {
        const lower = equals[1] !== undefined
        return (row) => (lower ? String(row[equalsColumn]).toLowerCase() : row[equalsColumn]) === equals[3]
    }
    const within = term.match(/^(\w+) IN \[('[^']*'(?:, '[^']*')*)\]$/)
    if (within && columns.includes(within[1])) {
        const values = within[2].split(', ').map((value) => value.slice(1, -1))
        return (row) => values.includes(String(row[within[1]]))
    }
    const window = term.match(/^toTimeZone\(timestamp, 'UTC'\) (>=|<) toDateTime\('([^']*)', 'UTC'\)$/)
    if (window) {
        const bound = Date.parse(window[2])
        return window[1] === '>=' ? (row) => timestampOf(row) >= bound : (row) => timestampOf(row) < bound
    }
    if (term === 'timestamp > {filters.dateRange.from}' && dateFrom) {
        return (row) => timestampOf(row) > Date.parse(dateFrom)
    }
    return null
}

function sumCountByGroup(rows: Row[], groupColumns: string[]): Row[] {
    const groups = new Map<string, Row>()
    for (const row of rows) {
        const key = groupColumns.map((column) => row[column]).join('\0')
        const group = groups.get(key) ?? { ...Object.fromEntries(groupColumns.map((c) => [c, row[c]])), total: 0 }
        groups.set(key, { ...group, total: Number(group.total) + Number(row.count) })
    }
    return [...groups.values()]
}

function strictHogQLFake(tables: Record<string, Row[]>): MockSignature {
    return async ({ request }) => {
        const body = (await request.json()) as { query: { query: string }; filters_override?: { date_from?: string } }
        const sql = body.query.query.replace(/\s+/g, ' ').trim()
        const unsupported = (what: string): [number, { detail: string }] => [400, { detail: `Unsupported ${what}` }]
        const parts = sql.match(
            /^SELECT (.+?) FROM (\w+)(?: WHERE (.+?))?(?: GROUP BY (.+?))?(?: ORDER BY (.+?))?(?: LIMIT (\d+))?$/
        )
        if (!parts || !tables[parts[2]]) {
            return unsupported(`query ${sql}`)
        }
        const [, select, table, where, groupBy, orderBy, limit] = parts
        const list = (text: string | undefined): string[] => (text ? text.split(/, (?![^(]*\))/) : [])
        const tableColumns = Object.keys(tables[table][0] ?? {})
        const terms = where ? where.split(' AND ') : []
        const predicates = terms.map((term) => wherePredicate(term, tableColumns, body.filters_override?.date_from))
        if (predicates.includes(null)) {
            return unsupported(`WHERE ${where}`)
        }
        const matching = tables[table].filter((row) => predicates.every((predicate) => predicate?.(row)))
        const groupColumns = list(groupBy)
        const sumsCount = !!groupBy && list(select).includes('sum(count) AS total')
        const columns = groupBy ? [...groupColumns, ...(sumsCount ? ['total'] : [])] : tableColumns
        const selected = list(select).map((term) => (sumsCount && term === 'sum(count) AS total' ? 'total' : term))
        if (groupColumns.some((column) => !tableColumns.includes(column))) {
            return unsupported(`GROUP BY ${groupBy}`)
        }
        const rows = groupBy ? sumCountByGroup(matching, groupColumns) : matching
        if (selected.some((column) => !columns.includes(column))) {
            return unsupported(`SELECT ${select}`)
        }
        const sortKeys = list(orderBy).map((term) => {
            const prefix = term.match(/^startsWith\(message, '([^']*)'\) DESC$/)?.[1]
            if (prefix !== undefined && columns.includes('message')) {
                return (row: Row): number => (String(row.message).startsWith(prefix) ? 1 : 0)
            }
            const column = term.match(/^(\w+) DESC$/)?.[1]
            if (column && columns.includes(column)) {
                return (row: Row): number =>
                    column === 'timestamp' ? Date.parse(String(row[column])) : Number(row[column])
            }
            return null
        })
        if (sortKeys.includes(null)) {
            return unsupported(`ORDER BY ${orderBy}`)
        }
        const sorted = [...rows].sort((a, b) => {
            for (const key of sortKeys as ((row: Row) => number)[]) {
                if (key(a) !== key(b)) {
                    return key(b) - key(a)
                }
            }
            return 0
        })
        const results = sorted.slice(0, limit ? Number(limit) : undefined).map((row) => selected.map((c) => row[c]))
        return [200, { results }]
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

const failedMetric = (appSourceId: string, instanceId: string, count: number): Row => ({
    app_source: 'hog_flow',
    app_source_id: appSourceId,
    metric_name: 'failed',
    instance_id: instanceId,
    count,
    timestamp: '2026-10-19T22:29:00Z',
})

const logEntry = (logSourceId: string, level: string, timestamp: string, message: string): Row => ({
    log_source: 'hog_flow',
    log_source_id: logSourceId,
    level,
    timestamp,
    message,
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
                    '/api/environments/:team_id/query/:kind/': strictHogQLFake({
                        app_metrics: [
                            // An aborting step records `failed` at step and run level, so the run-level row must not count twice.
                            failedMetric(runId, 'step_1', 245),
                            failedMetric(runId, '', 245),
                            failedMetric('another-run', 'step_1', 7),
                        ],
                        log_entries: [
                            logEntry(runId, 'ERROR', '2026-10-19T22:29:01Z', 'Workflow run aborted: socket hang up'),
                            logEntry(
                                runId,
                                'INFO',
                                '2026-10-19T22:29:02Z',
                                '[Action:step_1] Errored: Error: Failed to send email via SES'
                            ),
                            logEntry(
                                'another-run',
                                'ERROR',
                                '2026-10-19T22:29:03Z',
                                '[Action:step_1] Errored: Error: Email integration not found'
                            ),
                            logEntry(
                                runId,
                                'ERROR',
                                '2026-10-19T22:29:00Z',
                                '[Action:step_1] Errored: Error: invalid value expression: "person.name |", line:3, col:1'
                            ),
                        ],
                    }),
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
        {
            name: 'a send where some emails have no result yet',
            runStartedAt: '2026-11-10T22:28:56Z',
            totals: [
                [24, 'email_sent'],
                [22, 'email_delivered'],
            ],
            expected: { delivered: 22, awaitingResult: 2 },
        },
        {
            name: 'a send with spam complaints and emails that never reached the provider',
            runStartedAt: '2026-11-10T22:28:56Z',
            totals: [
                [10, 'email_sent'],
                [7, 'email_delivered'],
                [1, 'email_bounced'],
                [1, 'email_blocked'],
                [2, 'email_failed'],
            ],
            expected: { markedAsSpam: 1, failed: 2, awaitingResult: 2 },
        },
    ])('reports what happened to the emails for $name', async ({ name, runStartedAt, totals, expected }) => {
        jest.spyOn(api, 'queryHogQL').mockImplementation(
            async (query) =>
                ({ results: String(query).includes('email_link_clicked_by_link') ? [] : totals }) as HogQLQueryResponse
        )
        const logic = broadcastPerformanceLogic({
            runId: `run-${totals.length}-${name}`,
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
