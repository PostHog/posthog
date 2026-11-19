import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { ArchetypeEnumApi, MCPWrappedCardsApi, MCPWrappedMonthApi } from '../generated/api.schemas'

export type WrappedCardKey =
    | 'intro'
    | 'tool_calls'
    | 'top_tools'
    | 'apps'
    | 'labs'
    | 'models'
    | 'rush_hour'
    | 'reliability'
    | 'speed'
    | 'archetype'
    | 'share'

export interface ShareTile {
    label: string
    value: string
}

export const ARCHETYPE_NAMES: Record<ArchetypeEnumApi, string> = {
    one_hit_wonder: 'The One-Hit Wonder',
    swiss_army_knife: 'The Swiss Army Knife',
    night_owl: 'The Night Owl',
    weekend_warrior: 'The Weekend Warrior',
    speed_demon: 'The Speed Demon',
    rocket: 'The Rocket',
    all_rounder: 'The All-Rounder',
}

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const OTHER = 'Other'

/** The cards the story shows, in order. A card the backend left out (null) is skipped. */
export function storyCardKeys(cards: MCPWrappedCardsApi): WrappedCardKey[] {
    const optional: Record<'apps' | 'labs' | 'models' | 'rush_hour' | 'speed', boolean> = {
        apps: cards.apps !== null,
        labs: cards.labs !== null,
        models: cards.models !== null,
        rush_hour: cards.rush_hour !== null,
        speed: cards.speed !== null,
    }
    const order: WrappedCardKey[] = [
        'intro',
        'tool_calls',
        'top_tools',
        'apps',
        'labs',
        'models',
        'rush_hour',
        'reliability',
        'speed',
        'archetype',
        'share',
    ]
    return order.filter((key) => !(key in optional) || optional[key as keyof typeof optional])
}

export function formatMonth(month: string, style: 'long' | 'short' = 'long'): string {
    const [year, monthNumber] = month.split('-').map(Number)
    return new Date(Date.UTC(year, monthNumber - 1, 1)).toLocaleString('en-US', { month: style, timeZone: 'UTC' })
}

/** The tracked months in order, with any month in between that had no calls filled in as zero. */
export function chartMonths(months: readonly MCPWrappedMonthApi[]): MCPWrappedMonthApi[] {
    if (months.length === 0) {
        return []
    }
    const sorted = [...months].sort((a, b) => a.month.localeCompare(b.month))
    const [year, first] = sorted[0].month.split('-').map(Number)
    const last = Number(sorted[sorted.length - 1].month.split('-')[1])
    const calls = new Map(sorted.map((month) => [month.month, month.calls]))
    return Array.from({ length: last - first + 1 }, (_, index) => {
        const key = `${year}-${String(first + index).padStart(2, '0')}`
        return { month: key, calls: calls.get(key) ?? 0 }
    })
}

const COMPACT = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })

export function formatCompact(value: number): string {
    return COMPACT.format(value)
}

/** Exact below a million, where every digit still fits on the card; short form above it. */
export function formatCallCount(calls: number): string {
    return calls < 1_000_000 ? calls.toLocaleString('en-US') : formatCompact(calls)
}

const CALL_MILESTONES: [number, string][] = [
    [1_000_000_000, '1 billion'],
    [100_000_000, '100 million'],
    [10_000_000, '10 million'],
    [1_000_000, '1 million'],
    [100_000, '100,000'],
    [10_000, '10,000'],
]

/** The largest round number the total passed, or null below the first one. */
export function callMilestone(calls: number): string | null {
    const milestone = CALL_MILESTONES.find(([threshold]) => calls >= threshold)
    return milestone ? `Over ${milestone[1]} tool calls` : null
}

export function formatPercent(share: number): string {
    const percent = share * 100
    return `${percent >= 10 || percent === 0 ? Math.round(percent) : percent.toFixed(1)}%`
}

export function formatDuration(ms: number): string {
    return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`
}

export function formatHour(weekday: number, hour: number): string {
    const suffix = hour < 12 ? 'am' : 'pm'
    const twelveHour = hour % 12 === 0 ? 12 : hour % 12
    return `${WEEKDAYS[weekday - 1]}s, ${twelveHour} ${suffix}`
}

/** The tiles on the share card: only values from cards the project actually has, six at most. */
export function shareTiles(cards: MCPWrappedCardsApi): ShareTile[] {
    const tiles: ShareTile[] = [{ label: 'Tool calls', value: humanFriendlyNumber(cards.tool_calls.total_calls) }]
    const topTool = cards.top_tools.tools[0]
    if (topTool) {
        tiles.push({ label: 'Top tool', value: topTool.tool })
    }
    tiles.push({ label: 'Error-free calls', value: formatPercent(cards.reliability.success_rate) })
    const topApp = cards.apps?.shares.find((share) => share.name !== OTHER)
    if (topApp) {
        tiles.push({ label: 'Top app', value: topApp.name })
    }
    if (cards.rush_hour) {
        tiles.push({
            label: 'Rush hour',
            value: formatHour(cards.rush_hour.weekday, cards.rush_hour.hour).replace('s,', ''),
        })
    }
    const topModel = cards.models?.shares.find((share) => share.name !== OTHER)
    if (topModel) {
        tiles.push({ label: 'Top model', value: topModel.name })
    } else if (cards.speed) {
        tiles.push({ label: '95% answered in', value: formatDuration(cards.speed.p95_duration_ms) })
    }
    return tiles.slice(0, 6)
}
