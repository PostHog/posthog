import { dayjs } from 'lib/dayjs'

import type {
    HogFlowBatchJobApi,
    HogFlowMinimalApi,
    HogFlowScheduleApi,
} from 'products/workflows/frontend/generated/api.schemas'

import {
    calendarDays,
    calendarRange,
    calendarSendsForFlow,
    isScheduledEmailFlow,
    periodLabel,
    scheduleSendTimes,
} from './sendCalendarUtils'

const EMAIL_STEP = { type: 'function_email' }

const flow = (
    trigger: string,
    actions: unknown[] = [EMAIL_STEP],
    status: string = 'active'
): Pick<HogFlowMinimalApi, 'status' | 'trigger' | 'actions'> =>
    ({ status, trigger: { type: trigger }, actions }) as Pick<HogFlowMinimalApi, 'status' | 'trigger' | 'actions'>

const schedule = (
    rrule: string,
    starts_at: string,
    status: HogFlowScheduleApi['status'] = 'active',
    timezone = 'Europe/London'
): HogFlowScheduleApi => ({
    id: `schedule-${rrule}-${status}`,
    rrule,
    starts_at,
    timezone,
    status,
    next_run_at: null,
    created_at: starts_at,
    updated_at: starts_at,
})

const job = (id: string, status: HogFlowBatchJobApi['status'], created_at: string): HogFlowBatchJobApi =>
    ({ id, status, hog_flow: 'flow', created_at }) as HogFlowBatchJobApi

const LONDON_OCT_19_TO_NOV_1 = calendarRange(['2026-10-19', '2026-11-01'], 'Europe/London')

describe('sendCalendarUtils', () => {
    it.each([
        ['a batch workflow with an email step', flow('batch'), true],
        ['a scheduled workflow with an email step', flow('schedule'), true],
        ['an event-triggered workflow', flow('event'), false],
        ['a batch workflow without an email step', flow('batch', [{ type: 'delay' }]), false],
        ['a draft', flow('batch', [EMAIL_STEP], 'draft'), false],
    ])('decides whether to show %s', (_, value, expected) => {
        expect(isScheduledEmailFlow(value)).toBe(expected)
    })

    it.each([
        [
            'keeps a weekly send at 09:00 local time across the DST change on Oct 25',
            schedule('FREQ=WEEKLY;BYDAY=TU', '2026-09-01T08:00:00Z'),
            ['2026-10-20T08:00:00.000Z', '2026-10-27T09:00:00.000Z'],
        ],
        [
            'returns a one-time send inside the range',
            schedule('FREQ=DAILY;COUNT=1', '2026-10-21T10:00:00Z'),
            ['2026-10-21T10:00:00.000Z'],
        ],
        [
            'returns nothing for a one-time send outside the range',
            schedule('FREQ=DAILY;COUNT=1', '2026-11-05T10:00:00Z'),
            [],
        ],
    ])('%s', (_, value, expected) => {
        expect(scheduleSendTimes(value, LONDON_OCT_19_TO_NOV_1).map((time) => time.toISOString())).toEqual(expected)
    })

    it('takes future sends from schedules and past sends from batch jobs', () => {
        const sends = calendarSendsForFlow(
            {
                flow: { id: 'flow', name: 'Weekly digest', origin_product: null } as HogFlowMinimalApi,
                schedules: [
                    schedule('FREQ=WEEKLY;BYDAY=TU', '2026-09-01T08:00:00Z'),
                    schedule('FREQ=WEEKLY;BYDAY=FR', '2026-09-04T15:00:00Z', 'paused'),
                    schedule('FREQ=DAILY;COUNT=1', '2026-10-22T10:00:00Z', 'completed'),
                ],
                batchJobs: [
                    job('sent', 'completed', '2026-10-20T08:00:05Z'),
                    job('failed', 'failed', '2026-10-19T09:00:00Z'),
                    job('outside', 'completed', '2026-10-05T08:00:00Z'),
                ],
            },
            LONDON_OCT_19_TO_NOV_1,
            dayjs('2026-10-21T12:00:00Z')
        )

        expect(sends.map(({ state, at, repeat }) => [state, at.toISOString(), repeat])).toEqual([
            ['planned', '2026-10-27T09:00:00.000Z', 'Every week on Tuesday'],
            ['paused', '2026-10-23T15:00:00.000Z', 'Every week on Friday'],
            ['paused', '2026-10-30T16:00:00.000Z', 'Every week on Friday'],
            ['sent', '2026-10-20T08:00:05.000Z', null],
            ['failed', '2026-10-19T09:00:00.000Z', null],
        ])
    })

    it.each([
        ['a month that starts on Monday weeks', 'month', '2026-10-16', 1, '2026-09-28', 35],
        ['a month that starts on Sunday weeks', 'month', '2026-10-16', 0, '2026-09-27', 35],
        ['a week around its anchor day', 'week', '2026-10-21', 1, '2026-10-19', 7],
    ] as const)('lays out %s', (_, view, anchor, weekStartDay, firstDay, length) => {
        const days = calendarDays(view, anchor, weekStartDay)

        expect([days[0], days.length]).toEqual([firstDay, length])
    })

    it.each([
        ['a month', 'month', '2026-10-16', 'October 2026'],
        ['a week inside one month', 'week', '2026-10-21', 'Oct 19 to 25, 2026'],
        ['a week across two months', 'week', '2026-09-30', 'Sep 28 to Oct 4, 2026'],
    ] as const)('labels %s', (_, view, anchor, expected) => {
        expect(periodLabel(view, anchor, calendarDays(view, anchor, 1))).toBe(expected)
    })
})
