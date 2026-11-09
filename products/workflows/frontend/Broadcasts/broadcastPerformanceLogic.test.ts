import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import type { HogQLQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { broadcastPerformanceLogic, sendActivityParams } from './broadcastPerformanceLogic'

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
            // An aborting step records `failed` at step and run level, so the run-level row must not count twice.
            const rows: [number, string, string][] = [
                [0, 'email_sent', 'step_1'],
                [0, 'push_sent', 'step_1'],
                [245, 'failed', 'step_1'],
                [245, 'failed', ''],
            ]
            const errorLog = '[Action:step_1] Errored: Error: invalid value expression: "person.name |", line:3, col:1'
            jest.spyOn(api, 'queryHogQL').mockImplementation(
                async (query) =>
                    ({
                        results: String(query).includes('log_entries')
                            ? [[errorLog]]
                            : rows.filter(([, name]) => String(query).includes(`'${name}'`)),
                    }) as HogQLQueryResponse
            )
            const logic = broadcastPerformanceLogic({
                runId: `run-errored-${channel}`,
                runStartedAt: '2026-10-19T22:28:56Z',
                channel,
            })
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
