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
            const rows: [number, string][] = [
                [0, 'email_sent'],
                [0, 'push_sent'],
                [245, 'failed'],
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

    it('does not report tracking off before anything was sent', async () => {
        jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as unknown as HogQLQueryResponse)
        const logic = broadcastPerformanceLogic({ runId: 'run-2', runStartedAt: '2026-10-19T22:28:56Z' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadTotalsSuccess'])
        expect(logic.values.trackingOff).toBe(false)
    })
})
