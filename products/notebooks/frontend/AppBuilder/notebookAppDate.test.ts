import { isAbsoluteAppDate } from './notebookAppDate'

describe('absolute dates in shared app inputs', () => {
    it.each([
        '2026-01-31 09:00:00',
        '20260131T093000-01',
        '2026-W05-6',
        '2026W056',
        '2020-W53-7',
        '2024-02-29T09:30:00.123456+00:00:30',
        '0001-01-01',
        '2026-01-31T24:00:00',
    ])('keeps the server-compatible date %s', (value) => {
        expect(isAbsoluteAppDate(value)).toBe(true)
    })

    it.each([
        '2026-02-30',
        '2026-01-31T09:3045',
        '2026-01-31T0930:45',
        '2026-01-31T00:00:00+01:3045',
        '2025-W53-1',
        '0000-01-01',
        '9999-12-31T24:00:00',
    ])('rejects the invalid value %s', (value) => {
        expect(isAbsoluteAppDate(value)).toBe(false)
    })
})
