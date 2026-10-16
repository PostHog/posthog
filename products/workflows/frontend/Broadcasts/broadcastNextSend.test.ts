import type { HogFlowScheduleApi } from 'products/workflows/frontend/generated/api.schemas'

import { describeRepeat, nextSendTime, pickNextSchedule } from './broadcastNextSend'

const ONE_TIME = 'FREQ=DAILY;COUNT=1'
const WEEKLY = 'FREQ=WEEKLY;BYDAY=TU'

const schedule = (
    id: string,
    status: HogFlowScheduleApi['status'],
    next_run_at: string | null,
    rrule: string = WEEKLY,
    starts_at: string = '2026-10-20T10:00:00Z'
): HogFlowScheduleApi => ({ id, rrule, starts_at, status, next_run_at, created_at: starts_at, updated_at: starts_at })

describe('broadcastNextSend', () => {
    it.each([
        ['nothing when no schedule exists', [], null],
        ['nothing when every schedule finished', [schedule('a', 'completed', null)], null],
        [
            'the active schedule that sends first',
            [schedule('a', 'active', '2026-10-27T08:00:00Z'), schedule('b', 'active', '2026-10-20T08:00:00Z')],
            'b',
        ],
        [
            'an active schedule over a paused one',
            [schedule('a', 'paused', null), schedule('b', 'active', '2026-10-27T08:00:00Z')],
            'b',
        ],
        [
            'a paused schedule when nothing is active',
            [schedule('a', 'completed', null), schedule('b', 'paused', null)],
            'b',
        ],
        [
            'a known next run over one the scheduler has not set yet',
            [schedule('a', 'active', null), schedule('b', 'active', '2026-10-27T08:00:00Z')],
            'b',
        ],
    ])('picks %s', (_, schedules, expectedId) => {
        expect(pickNextSchedule(schedules)?.id ?? null).toBe(expectedId)
    })

    it.each([
        [
            'a one-time send before the scheduler sets its next run',
            schedule('a', 'active', null, ONE_TIME),
            '2026-10-20T10:00:00Z',
            'Once',
        ],
        [
            'a repeating send',
            schedule('a', 'active', '2026-10-20T08:00:00Z'),
            '2026-10-20T08:00:00Z',
            'Every week on Tuesday',
        ],
        [
            'a repeating send before the scheduler sets its next run',
            schedule('a', 'active', null),
            null,
            'Every week on Tuesday',
        ],
    ])('describes %s', (_, value, expectedTime, expectedRepeat) => {
        expect(nextSendTime(value)).toBe(expectedTime)
        expect(describeRepeat(value)).toBe(expectedRepeat)
    })
})
