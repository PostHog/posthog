import { observationsDrilldownSearchParams } from './ScannerInsightsChart'

describe('observationsDrilldownSearchParams', () => {
    it('maps a clicked day to an inclusive single-day observations filter', () => {
        expect(observationsDrilldownSearchParams('2026-07-29')).toEqual({
            tab: 'observations',
            date_from: '2026-07-29',
            date_to: '2026-07-29',
        })
    })

    it('keeps only the date part of a datetime bucket', () => {
        expect(observationsDrilldownSearchParams('2026-07-29 14:00:00')).toEqual({
            tab: 'observations',
            date_from: '2026-07-29',
            date_to: '2026-07-29',
        })
    })

    it('adds the clicked tag for classifier breakdown series', () => {
        expect(observationsDrilldownSearchParams('2026-07-29', 'rageclick')).toEqual({
            tab: 'observations',
            date_from: '2026-07-29',
            date_to: '2026-07-29',
            tags: 'rageclick',
        })
    })

    it('unwraps single-value breakdown arrays', () => {
        expect(observationsDrilldownSearchParams('2026-07-29', ['rageclick'])?.tags).toEqual('rageclick')
    })

    // The "Other"/"None" breakdown buckets aren't real tags, so they can't be used as a tags filter.
    const nonTagBreakdowns: [string, unknown][] = [
        ['other bucket', '$$_posthog_breakdown_other_$$'],
        ['null bucket', '$$_posthog_breakdown_null_$$'],
        ['numeric breakdown', 42],
        ['empty string', ''],
        ['undefined', undefined],
    ]

    it.each(nonTagBreakdowns)('drills without a tags filter for %s', (_label, breakdown) => {
        expect(observationsDrilldownSearchParams('2026-07-29', breakdown)).toEqual({
            tab: 'observations',
            date_from: '2026-07-29',
            date_to: '2026-07-29',
        })
    })

    // Buckets that aren't plain dates have no observations-tab equivalent, so the click is a no-op.
    const invalidDays: [string, string | number | undefined][] = [
        ['undefined day', undefined],
        ['numeric day', 1753747200],
        ['non-date label', 'previous'],
    ]

    it.each(invalidDays)('returns null for %s', (_label, day) => {
        expect(observationsDrilldownSearchParams(day)).toBeNull()
    })
})
