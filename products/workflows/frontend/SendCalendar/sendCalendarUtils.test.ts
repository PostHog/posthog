import { dayjs } from 'lib/dayjs'

import type {
    HogFlowBatchJobApi,
    HogFlowMinimalApi,
    HogFlowScheduleApi,
} from 'products/workflows/frontend/generated/api.schemas'

import {
    CalendarSend,
    calendarDays,
    calendarRange,
    calendarSendsForFlow,
    describeRepeat,
    dropTarget,
    isScheduledEmailFlow,
    moveBlockedReason,
    movedScheduleFields,
    periodLabel,
    scheduleSendTimes,
    sendAudience,
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

    const COHORT_FILTER = { key: 'id', type: 'cohort', value: 21 }
    const EMAIL_IS_SET = { key: 'email', type: 'person', operator: 'is_set', value: 'is_set' }
    const COHORT_EXCLUSION = { key: 'id', type: 'cohort', operator: 'not_in', value: 22 }

    it.each([
        [
            'a broadcast that filters on a cohort and a person property',
            { type: 'batch', filters: { properties: [COHORT_FILTER, EMAIL_IS_SET] } },
            [EMAIL_STEP],
            { cohortIds: [21], filters: [EMAIL_IS_SET], accounts: false, address: null },
        ],
        [
            'a broadcast that leaves out a cohort',
            { type: 'batch', filters: { properties: [COHORT_FILTER, COHORT_EXCLUSION] } },
            [EMAIL_STEP],
            { cohortIds: [21], filters: [COHORT_EXCLUSION], accounts: false, address: null },
        ],
        [
            'a batch workflow that runs for each account',
            { type: 'batch', filters: { properties: [], audience_type: 'accounts' } },
            [EMAIL_STEP],
            { cohortIds: [], filters: [], accounts: true, address: null },
        ],
        [
            'a scheduled workflow, which sends to the To address of its email',
            { type: 'schedule' },
            [
                {
                    type: 'function_email',
                    config: { inputs: { email: { value: { to: { email: 'team@example.com' } } } } },
                },
            ],
            { cohortIds: [], filters: [], accounts: false, address: 'team@example.com' },
        ],
    ])('reads who %s sends to', (_, trigger, actions, expected) => {
        expect(sendAudience({ trigger, actions } as Pick<HogFlowMinimalApi, 'trigger' | 'actions'>)).toEqual(expected)
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

    it.each([
        ['a one-time send', 'FREQ=DAILY;COUNT=1', 'Once'],
        ['a weekly send', 'FREQ=WEEKLY;BYDAY=TU', 'Every week on Tuesday'],
        ['an hourly send from the API', 'FREQ=HOURLY', 'Every hour'],
        ['a monthly send on a set date', 'FREQ=MONTHLY;BYMONTHDAY=15', 'Every month on the 15th'],
    ])('describes the repeat rule of %s', (_, rrule, expected) => {
        expect(describeRepeat({ rrule, starts_at: '2026-09-01T08:00:00Z' })).toBe(expected)
    })

    const NOW = dayjs('2026-10-16T12:00:00Z')

    const plannedSend = (rrule: string, overrides: Partial<CalendarSend> = {}): CalendarSend =>
        ({
            state: 'planned',
            at: dayjs('2026-10-20T10:00:00Z'),
            schedule: schedule(rrule, '2026-10-20T10:00:00Z', 'active', 'UTC'),
            userAccessLevel: 'editor',
            ...overrides,
        }) as CalendarSend

    it.each([
        ['a one-time send', plannedSend('FREQ=DAILY;COUNT=1'), null],
        ['a weekly send', plannedSend('FREQ=WEEKLY;BYDAY=TU'), null],
        [
            'a send that already went out',
            plannedSend('FREQ=DAILY;COUNT=1', { state: 'sent', schedule: null }),
            'This send already went out.',
        ],
        [
            'a paused schedule',
            plannedSend('FREQ=WEEKLY;BYDAY=TU', { state: 'paused' }),
            'This schedule is paused. Open it to schedule it again.',
        ],
        [
            'a send whose time passed while the calendar was open',
            plannedSend('FREQ=DAILY;COUNT=1', { at: dayjs('2026-10-16T09:00:00Z') }),
            'This send already went out.',
        ],
        [
            'an hourly send from the API',
            plannedSend('FREQ=HOURLY'),
            'Open the schedule to move a send that repeats this way.',
        ],
        ['a send that repeats every 2 weeks', plannedSend('FREQ=WEEKLY;INTERVAL=2;BYDAY=TH'), null],
        [
            'a send that repeats every 2 weeks on two weekdays',
            plannedSend('FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,FR'),
            'Open the schedule to move a send that repeats this way.',
        ],
        [
            'a send that the person can only view',
            plannedSend('FREQ=DAILY;COUNT=1', { userAccessLevel: 'viewer' }),
            expect.any(String),
        ],
    ])('decides whether %s can move', (_, send, expected) => {
        expect(moveBlockedReason(send, NOW)).toEqual(expected)
    })

    it.each([
        ['the same day', '2026-10-20', null],
        ['a day in the past', '2026-10-14', null],
        ['a later day', '2026-10-22', { days: 2, at: '2026-10-22T10:00:00.000Z' }],
    ])('drops a send on %s', (_, day, expected) => {
        const send = {
            at: dayjs('2026-10-20T10:00:00Z'),
            schedule: schedule('FREQ=DAILY;COUNT=1', '2026-10-20T10:00:00Z', 'active', 'UTC'),
        }
        const target = dropTarget(send, day, 'UTC', dayjs('2026-10-16T12:00:00Z'))

        expect(target && { days: target.days, at: target.at.toISOString() }).toEqual(expected)
    })

    it.each([
        [
            'keeps the local time of a one-time send across the DST change',
            schedule('FREQ=DAILY;COUNT=1', '2026-10-23T15:00:00Z'),
            3,
            { starts_at: '2026-10-26T16:00:00.000Z', rrule: 'FREQ=DAILY;COUNT=1' },
        ],
        [
            'moves the weekday of a weekly send',
            schedule('FREQ=WEEKLY;BYDAY=TU', '2026-09-01T09:00:00Z', 'active', 'UTC'),
            1,
            { starts_at: '2026-09-02T09:00:00.000Z', rrule: 'FREQ=WEEKLY;INTERVAL=1;BYDAY=WE' },
        ],
        [
            'wraps a weekday past the end of the week',
            schedule('FREQ=WEEKLY;BYDAY=SU', '2026-09-06T09:00:00Z', 'active', 'UTC'),
            1,
            { starts_at: '2026-09-07T09:00:00.000Z', rrule: 'FREQ=WEEKLY;INTERVAL=1;BYDAY=MO' },
        ],
        [
            'keeps the interval of a send that repeats every 2 weeks',
            schedule('FREQ=WEEKLY;INTERVAL=2;BYDAY=TU', '2026-09-01T16:00:00Z', 'active', 'UTC'),
            2,
            { starts_at: '2026-09-03T16:00:00.000Z', rrule: 'FREQ=WEEKLY;INTERVAL=2;BYDAY=TH' },
        ],
    ])('%s', (_, value, days, expected) => {
        expect(movedScheduleFields(value, days, dayjs('2026-08-31T00:00:00Z'))).toEqual(expected)
    })

    it.each([
        [
            'a series that ends after a count keeps only the sends left',
            schedule('FREQ=WEEKLY;BYDAY=TU;COUNT=10', '2026-09-01T09:00:00Z', 'active', 'UTC'),
            { starts_at: '2026-10-21T09:00:00.000Z', rrule: 'FREQ=WEEKLY;INTERVAL=1;BYDAY=WE;COUNT=3' },
        ],
        [
            'a series that ends on a date keeps its last send',
            schedule('FREQ=WEEKLY;BYDAY=TU;UNTIL=20261124T235959Z', '2026-10-20T09:00:00Z', 'active', 'UTC'),
            {
                starts_at: '2026-10-21T09:00:00.000Z',
                rrule: 'FREQ=WEEKLY;INTERVAL=1;BYDAY=WE;UNTIL=20261125T235959Z',
            },
        ],
        [
            'a one-time send that names a weekday becomes a plain one-time send',
            schedule('FREQ=WEEKLY;BYDAY=TU;COUNT=1', '2026-10-20T09:00:00Z', 'active', 'UTC'),
            { starts_at: '2026-10-21T09:00:00.000Z', rrule: 'FREQ=DAILY;COUNT=1' },
        ],
    ])('moves %s', (_, value, expected) => {
        expect(movedScheduleFields(value, 1, NOW)).toEqual(expected)
    })

    it('starts a moved weekly send from its next send, so no past send comes back', () => {
        const weekly = schedule('FREQ=WEEKLY;BYDAY=TU', '2026-09-01T09:00:00Z', 'active', 'UTC')

        expect(movedScheduleFields(weekly, 6, NOW)).toEqual({
            starts_at: '2026-10-26T09:00:00.000Z',
            rrule: 'FREQ=WEEKLY;INTERVAL=1;BYDAY=MO',
        })
    })
})
