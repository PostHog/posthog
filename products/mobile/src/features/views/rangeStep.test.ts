import type { RangeChoice, ResolvedRange, SavedRange } from '@/model/views'

import { projectToday, type StepDirection, stepRange } from './rangeStep'

const NOW = Date.parse('2026-10-14T19:00:00Z')
const TODAY = projectToday('2026-10-14T23:59:59-07:00', NOW)
const NO_SAVED: SavedRange = { dateFrom: null, dateTo: null }

function days(from: string, to: string): ResolvedRange {
    return { from: `${from}T00:00:00-07:00`, to: `${to}T23:59:59-07:00` }
}

function fixed(dateFrom: string, dateTo: string, unit: string, origin: string | null): RangeChoice {
    return { kind: 'fixed', dateFrom, dateTo, explicitDate: false, unit, origin } as RangeChoice
}

const preset = (key: string): RangeChoice => ({ kind: 'preset', key }) as RangeChoice

describe('stepRange', () => {
    test.each<[string, RangeChoice | null, SavedRange, ResolvedRange, StepDirection, RangeChoice | null]>([
        [
            'today back to yesterday',
            preset('today'),
            NO_SAVED,
            days('2026-10-14', '2026-10-14'),
            -1,
            preset('yesterday'),
        ],
        ['today forward', preset('today'), NO_SAVED, days('2026-10-14', '2026-10-14'), 1, null],
        [
            'yesterday forward to today',
            preset('yesterday'),
            NO_SAVED,
            days('2026-10-13', '2026-10-13'),
            1,
            preset('today'),
        ],
        [
            'a fixed day back',
            fixed('2026-10-10', '2026-10-10', 'day', null),
            NO_SAVED,
            days('2026-10-10', '2026-10-10'),
            -1,
            fixed('2026-10-09', '2026-10-09', 'day', null),
        ],
        [
            'last 7 days back by its 8 resolved days',
            preset('7d'),
            NO_SAVED,
            days('2026-10-07', '2026-10-14'),
            -1,
            fixed('2026-09-29', '2026-10-06', 'days', '7d'),
        ],
        [
            'the saved last 7 days back',
            null,
            { dateFrom: '-7d', dateTo: null },
            days('2026-10-07', '2026-10-14'),
            -1,
            fixed('2026-09-29', '2026-10-06', 'days', '7d'),
        ],
        [
            'a stepped week of days forward to the preset',
            fixed('2026-09-29', '2026-10-06', 'days', '7d'),
            NO_SAVED,
            days('2026-09-29', '2026-10-06'),
            1,
            preset('7d'),
        ],
        [
            'this week back to the whole week before',
            preset('this_week'),
            NO_SAVED,
            days('2026-10-12', '2026-10-14'),
            -1,
            fixed('2026-10-05', '2026-10-11', 'week', 'this_week'),
        ],
        [
            'a whole week forward to this week',
            fixed('2026-10-05', '2026-10-11', 'week', 'this_week'),
            NO_SAVED,
            days('2026-10-05', '2026-10-11'),
            1,
            preset('this_week'),
        ],
        ['this month back', preset('this_month'), NO_SAVED, days('2026-10-01', '2026-10-14'), -1, preset('last_month')],
        [
            'last month back',
            preset('last_month'),
            NO_SAVED,
            days('2026-09-01', '2026-09-30'),
            -1,
            fixed('2026-08-01', '2026-08-31', 'month', 'last_month'),
        ],
        [
            'a whole month forward to last month',
            fixed('2026-08-01', '2026-08-31', 'month', 'last_month'),
            NO_SAVED,
            days('2026-08-01', '2026-08-31'),
            1,
            preset('last_month'),
        ],
        [
            'this year back',
            preset('this_year'),
            NO_SAVED,
            days('2026-01-01', '2026-10-14'),
            -1,
            fixed('2025-01-01', '2025-12-31', 'year', 'this_year'),
        ],
        [
            'last 24 hours back',
            preset('24h'),
            NO_SAVED,
            { from: '2026-10-13T19:00:00Z', to: '2026-10-14T19:00:00Z' },
            -1,
            {
                kind: 'fixed',
                dateFrom: '2026-10-12T19:00:00.000Z',
                dateTo: '2026-10-13T19:00:00.000Z',
                explicitDate: true,
                unit: 'hours',
                origin: '24h',
            },
        ],
        [
            'a stepped day of hours forward to the preset',
            {
                kind: 'fixed',
                dateFrom: '2026-10-12T19:00:00.000Z',
                dateTo: '2026-10-13T19:00:00.000Z',
                explicitDate: true,
                unit: 'hours',
                origin: '24h',
            },
            NO_SAVED,
            { from: '2026-10-12T19:00:00Z', to: '2026-10-13T19:00:00Z' },
            1,
            preset('24h'),
        ],
        [
            'last 24 hours forward from a cache read in an earlier hour',
            preset('24h'),
            NO_SAVED,
            { from: '2026-10-13T17:00:00Z', to: '2026-10-14T17:59:59Z' },
            1,
            null,
        ],
        ['all time', preset('all'), NO_SAVED, days('2020-01-01', '2026-10-14'), -1, null],
    ])('steps %s', (_name, choice, saved, resolved, direction, expected) => {
        expect(stepRange(choice, saved, direction, { resolved, today: TODAY, now: NOW })).toEqual(expected)
    })
})
