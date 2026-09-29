import { dayjs } from 'lib/dayjs'

import { sendActivityParams } from './broadcastPerformanceLogic'

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
