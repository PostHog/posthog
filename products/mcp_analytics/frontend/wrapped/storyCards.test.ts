import type { MCPWrappedCardsApi } from '../generated/api.schemas'
import {
    formatHour,
    shareTiles,
    storyCardKeys,
    chartMonths,
    formatCallCount,
    peakMultiple,
    rushHourLine,
} from './storyCards'

const BASE: MCPWrappedCardsApi = {
    intro: { tracked_since: '2026-07', server_count: 1 },
    tool_calls: { total_calls: 4812655, months: [{ month: '2026-07', calls: 4812655 }], growth_multiple: null },
    top_tools: { tools: [{ tool: 'get_forecast', calls: 1540000 }] },
    apps: null,
    labs: null,
    models: null,
    rush_hour: null,
    reliability: { success_rate: 0.976, struggling_tool: null },
    speed: { p95_duration_ms: 410, quickest_busy_tool: null, slowest_tool: null },
    archetype: { archetype: 'all_rounder', evidence: null },
}

describe('storyCards', () => {
    it.each([
        [
            'skips cards the backend left out',
            BASE,
            ['intro', 'tool_calls', 'top_tools', 'reliability', 'speed', 'archetype', 'share'],
        ],
        [
            'keeps optional cards that have data',
            {
                ...BASE,
                models: { shares: [{ name: 'Claude Sonnet', share: 0.6 }] },
                rush_hour: {
                    weekday: 2,
                    hour: 15,
                    timezone: 'UTC',
                    heat: [],
                    quiet_weekends: true,
                    night_shift: false,
                },
            },
            ['intro', 'tool_calls', 'top_tools', 'models', 'rush_hour', 'reliability', 'speed', 'archetype', 'share'],
        ],
    ])('%s', (_name, cards, keys) => {
        expect(storyCardKeys(cards)).toEqual(keys)
    })

    it('shows the top model on the share card, and p95 speed without one', () => {
        const withModel = { ...BASE, models: { shares: [{ name: 'Claude Sonnet', share: 0.6 }] } }

        expect(shareTiles(withModel).at(-1)).toEqual({ label: 'Top model', value: 'Claude Sonnet' })
        expect(shareTiles(BASE).at(-1)).toEqual({ label: '95% answered in', value: '410 ms' })
    })

    it.each([
        [2, 15, 'Tuesday, 3 pm'],
        [7, 0, 'Sunday, 12 am'],
        [1, 12, 'Monday, 12 pm'],
    ])('formats weekday %i at hour %i', (weekday, hour, expected) => {
        expect(formatHour(weekday, hour)).toBe(expected)
    })

    it('fills months between tracked months with zero calls', () => {
        expect(
            chartMonths([
                { month: '2026-11', calls: 40 },
                { month: '2026-09', calls: 10 },
            ])
        ).toEqual([
            { month: '2026-09', calls: 10 },
            { month: '2026-10', calls: 0 },
            { month: '2026-11', calls: 40 },
        ])
    })

    it.each([
        [999_999, '999,999'],
        [4_812_655, '4.8M'],
        [219_000_000, '219M'],
    ])('shows %i calls as %s', (calls, count) => {
        expect(formatCallCount(calls)).toBe(count)
    })

    it.each([
        ['an even week', Array(168).fill(100), null],
        ['a peak three times the average', [100, 0, 0], '3.0×'],
        ['a peak far above the average', [100, ...Array(167).fill(1)], 'over 10×'],
        ['no calls', Array(168).fill(0), null],
    ])('gives the peak multiple for %s', (_, heat, expected) => {
        expect(peakMultiple(heat)).toBe(expected)
    })

    it.each([
        [2, 6, false, 'Your agents were already hard at work.'],
        [3, 14, false, 'Right in the middle of the workday.'],
        [4, 19, false, 'Your agents kept going after hours.'],
        [6, 14, false, 'Your agents worked through the weekend.'],
        [2, 14, true, 'Your agents worked the night shift.'],
        [5, 23, false, 'Your agents worked the night shift.'],
    ])('describes weekday %i at hour %i (night shift %s)', (weekday, hour, nightShift, expected) => {
        expect(rushHourLine(weekday, hour, nightShift)).toBe(expected)
    })
})
