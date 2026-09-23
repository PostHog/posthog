import { dayjs } from 'lib/dayjs'

import { stepAnomaliesWindow, weekStartingOn } from './anomaliesDateWindow'

const NOW = dayjs('2026-09-23T11:00:00Z')

describe('anomaliesDateWindow', () => {
    test.each([
        {
            name: 'rolling 7 days steps back one week',
            dateRange: { date_from: '-7d', date_to: null },
            direction: -1 as const,
            expected: { date_from: '2026-09-09T11:00:00.000Z', date_to: '2026-09-16T11:00:00.000Z' },
        },
        {
            name: 'rolling 24 hours steps back one day',
            dateRange: { date_from: '-24h', date_to: null },
            direction: -1 as const,
            expected: { date_from: '2026-09-21T11:00:00.000Z', date_to: '2026-09-22T11:00:00.000Z' },
        },
        {
            name: 'rolling window cannot step forward',
            dateRange: { date_from: '-7d', date_to: null },
            direction: 1 as const,
            expected: null,
        },
        {
            name: 'fixed week steps forward one week',
            dateRange: { date_from: '2026-09-02T00:00:00.000Z', date_to: '2026-09-09T00:00:00.000Z' },
            direction: 1 as const,
            expected: { date_from: '2026-09-09T00:00:00.000Z', date_to: '2026-09-16T00:00:00.000Z' },
        },
        {
            name: 'a forward step that reaches now returns to the rolling option',
            dateRange: { date_from: '2026-09-09T11:00:00.000Z', date_to: '2026-09-16T11:00:00.000Z' },
            direction: 1 as const,
            expected: { date_from: '-7d', date_to: null },
        },
        {
            name: 'a week whose end is capped at now keeps its full length when it steps back',
            dateRange: { date_from: '2026-09-20T00:00:00.000Z', date_to: '2026-09-27T00:00:00.000Z' },
            direction: -1 as const,
            expected: { date_from: '2026-09-13T00:00:00.000Z', date_to: '2026-09-20T00:00:00.000Z' },
        },
        {
            name: 'a step back to exactly 35 days ago is allowed',
            dateRange: { date_from: '2026-08-26T11:00:00.000Z', date_to: '2026-09-02T11:00:00.000Z' },
            direction: -1 as const,
            expected: { date_from: '2026-08-19T11:00:00.000Z', date_to: '2026-08-26T11:00:00.000Z' },
        },
        {
            name: 'a step back past 35 days is refused',
            dateRange: { date_from: '2026-08-26T10:00:00.000Z', date_to: '2026-09-02T10:00:00.000Z' },
            direction: -1 as const,
            expected: null,
        },
    ])('$name', ({ dateRange, direction, expected }) => {
        expect(stepAnomaliesWindow(dateRange, direction, NOW)).toEqual(expected)
    })

    it('a picked day spans seven days from its midnight', () => {
        const day = dayjs('2026-09-08T15:30:00')
        expect(weekStartingOn(day)).toEqual({
            date_from: day.startOf('day').toISOString(),
            date_to: day.startOf('day').add(7, 'day').toISOString(),
        })
    })
})
