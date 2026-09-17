import { sessionErrorsWindow, traceErrorsWindow, usableId } from './errorCorrelation'

describe('errorCorrelation', () => {
    // A span whose timestamp the parser rejects must not widen the range to an invalid one, which
    // would put NaN into the query the badge lookup builds. The range is six hours either side.
    it.each([
        ['every timestamp parses', ['2026-09-03T10:00:00Z', '2026-09-03T12:00:00Z']],
        [
            'one timestamp is missing and another unparseable',
            ['2026-09-03T10:00:00Z', null, 'not-a-timestamp', '2026-09-03T12:00:00Z'],
        ],
    ])('spans the earliest and latest timestamp when %s', (_name, timestamps) => {
        expect(sessionErrorsWindow(timestamps)).toEqual({
            date_from: '2026-09-03T04:00:00.000Z',
            date_to: '2026-09-03T18:00:00.000Z',
        })
    })

    it.each([
        ['no timestamps', []],
        ['only unparseable timestamps', ['not-a-timestamp']],
        ['only missing timestamps', [null]],
    ])('resolves no range when there are %s', (_name, timestamps) => {
        expect(sessionErrorsWindow(timestamps)).toBeNull()
    })

    it.each([
        ['a real id', '4BF92F3577B34DA6A3CE929D0E0E4736', '4bf92f3577b34da6a3ce929d0e0e4736'],
        ['an all-zero trace id', '0'.repeat(32), null],
        ['an all-zero span id', '0'.repeat(16), null],
        ['a missing id', null, null],
        ['an empty id', '', null],
    ])('resolves %s', (_name, value, expected) => {
        expect(usableId(value)).toBe(expected)
    })

    // The exact join only has to cover the trace's own run, so it asks over a much narrower range
    // than the session guess needs.
    it('spans one hour either side for the trace window', () => {
        expect(traceErrorsWindow(['2026-09-03T10:00:00Z'])).toEqual({
            date_from: '2026-09-03T09:00:00.000Z',
            date_to: '2026-09-03T11:00:00.000Z',
        })
    })
})
