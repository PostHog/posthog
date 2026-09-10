import { sessionErrorsWindow } from './sessionErrors'

describe('sessionErrorsWindow', () => {
    // A span whose timestamp the parser rejects must not widen the range to an invalid one, which
    // would put NaN into the query the badge lookup builds. The range is six hours either side.
    it.each([
        ['every timestamp parses', ['2026-09-03T10:00:00Z', '2026-09-03T12:00:00Z']],
        ['one timestamp is missing or unparseable', ['2026-09-03T10:00:00Z', null, '2026-09-03T12:00:00Z']],
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
})
