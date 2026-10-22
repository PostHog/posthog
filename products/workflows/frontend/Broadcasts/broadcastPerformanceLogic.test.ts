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

    it('does not report tracking off before anything was sent', async () => {
        jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as unknown as HogQLQueryResponse)
        const logic = broadcastPerformanceLogic({ runId: 'run-2', runStartedAt: '2026-10-19T22:28:56Z' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadTotalsSuccess'])
        expect(logic.values.trackingOff).toBe(false)
    })
})
