import type { MCPWrappedCardsApi } from '../generated/api.schemas'
import { formatHour, shareTiles, storyCardKeys } from './storyCards'

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
        [2, 15, 'Tuesdays, 3 pm'],
        [7, 0, 'Sundays, 12 am'],
        [1, 12, 'Mondays, 12 pm'],
    ])('formats weekday %i at hour %i', (weekday, hour, expected) => {
        expect(formatHour(weekday, hour)).toBe(expected)
    })
})
