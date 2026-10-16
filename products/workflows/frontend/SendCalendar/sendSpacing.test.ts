import { dayjs } from 'lib/dayjs'

import { type SendAudience, audienceFromProperties } from './sendCalendarUtils'
import { SendingRule, mayShareRecipients, sendingRule, suggestSendTime } from './sendSpacing'

const DEFAULT_RULE = sendingRule(null)
const TWO_PER_WEEK: SendingRule = { maxMessages: 2, windowDays: 7, fromCap: true }

const send = (iso: string): { at: dayjs.Dayjs } => ({ at: dayjs.utc(iso) })

const audience = (cohortIds: number[], filters: SendAudience['filters'] = []): SendAudience => ({
    cohortIds,
    filters,
    accounts: false,
    address: null,
})

describe('sendSpacing', () => {
    it.each([
        [
            'skips the days within 2 days of another send when no cap is set',
            DEFAULT_RULE,
            '2026-10-20T08:00:00Z',
            [send('2026-10-21T10:00:00Z')],
            '2026-10-23T10:00:00.000Z',
        ],
        [
            'takes today when the cap allows a second send',
            TWO_PER_WEEK,
            '2026-10-20T08:00:00Z',
            [send('2026-10-21T10:00:00Z')],
            '2026-10-20T10:00:00.000Z',
        ],
        [
            'counts a past send inside the cap window',
            TWO_PER_WEEK,
            '2026-10-20T08:00:00Z',
            [send('2026-10-18T10:00:00Z'), send('2026-10-21T10:00:00Z')],
            '2026-10-25T10:00:00.000Z',
        ],
        [
            'starts tomorrow when the time already passed today',
            DEFAULT_RULE,
            '2026-10-20T12:00:00Z',
            [],
            '2026-10-21T10:00:00.000Z',
        ],
    ])('%s', (_, rule, now, others, expected) => {
        const suggestion = suggestSendTime({
            timeOfDay: '10:00:00',
            timezone: 'UTC',
            now: dayjs.utc(now),
            others,
            rule,
        })

        expect(suggestion?.toISOString()).toBe(expected)
    })

    it.each([
        ['two audiences that share a cohort', audience([21, 22]), audience([22]), true],
        ['two audiences of different cohorts', audience([21]), audience([24]), false],
        ['an audience of everyone', audience([]), audience([24]), true],
        [
            'an audience that filters on a person property',
            audience([21], [
                { key: 'plan', type: 'person', operator: 'exact', value: ['free'] },
            ] as SendAudience['filters']),
            audience([24]),
            true,
        ],
        [
            'two audiences that each leave out a different cohort',
            audienceFromProperties([
                { key: 'id', type: 'cohort', operator: 'not_in', value: 21 },
            ] as SendAudience['filters']),
            audienceFromProperties([
                { key: 'id', type: 'cohort', operator: 'not_in', value: 24 },
            ] as SendAudience['filters']),
            true,
        ],
    ])('decides whether %s can share people', (_, a, b, expected) => {
        expect(mayShareRecipients(a, b)).toBe(expected)
    })
})
