import { DEFAULT_DATE_RANGE, parseDateRangeParam } from './issueFiltersLogic'

describe('parseDateRangeParam', () => {
    it('returns default when no relevant params are provided', () => {
        expect(parseDateRangeParam({})).toEqual(DEFAULT_DATE_RANGE)
    })

    it('returns structured dateRange object as-is', () => {
        const dateRange = { date_from: '-30d', date_to: null }
        expect(parseDateRangeParam({ dateRange })).toEqual(dateRange)
    })

    it('parses JSON-encoded dateRange strings', () => {
        const dateRange = { date_from: '-30d', date_to: null }
        expect(parseDateRangeParam({ dateRange: JSON.stringify(dateRange) })).toEqual(dateRange)
    })

    it('treats a bare dateRange string as date_from shorthand', () => {
        expect(parseDateRangeParam({ dateRange: '-30d' })).toEqual({ date_from: '-30d', date_to: null })
    })

    it('falls back to flat date_from / date_to params', () => {
        expect(parseDateRangeParam({ date_from: '-30d' })).toEqual({ date_from: '-30d', date_to: null })
        expect(parseDateRangeParam({ date_from: '-30d', date_to: '-1d' })).toEqual({
            date_from: '-30d',
            date_to: '-1d',
        })
    })

    it('prefers structured dateRange over flat params when both are present', () => {
        const dateRange = { date_from: '-7d', date_to: null }
        expect(parseDateRangeParam({ dateRange, date_from: '-30d' })).toEqual(dateRange)
    })
})
