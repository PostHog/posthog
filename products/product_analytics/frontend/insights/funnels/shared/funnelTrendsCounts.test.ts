import { type FunnelTrendsCounts, formatFunnelTrendsCounts } from './funnelTrendsCounts'

describe('funnelTrendsCounts', () => {
    const series: FunnelTrendsCounts = {
        reached_from_step_count: [200, 18, 12345],
        reached_to_step_count: [110, 10, 6789],
    }

    it.each<[string, number, string]>([
        ['reads the period out of both arrays, converted first', 1, '10/18'],
        ['groups thousands so a large funnel stays readable', 2, '6,789/12,345'],
    ])('%s', (_name, periodIndex, expected) => {
        expect(formatFunnelTrendsCounts(series, periodIndex)).toBe(expected)
    })

    it.each<[string, FunnelTrendsCounts, number]>([
        ['a result cached before the runner returned counts', {}, 0],
        ['a series carrying only the entered count', { reached_from_step_count: [200] }, 0],
        ['a series carrying only the converted count', { reached_to_step_count: [110] }, 0],
        ['a period past the end of the counts', series, 5],
    ])('returns null for %s', (_name, incomplete, periodIndex) => {
        expect(formatFunnelTrendsCounts(incomplete, periodIndex)).toBeNull()
    })
})
