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

export function formatPercent(share: number): string {
    const percent = share * 100
    return `${percent >= 10 || percent === 0 ? Math.round(percent) : percent.toFixed(1)}%`
}

/** A success rate that never rounds up to a perfect 100% while any call failed. */
export function formatSuccessRate(rate: number): string {
    if (rate >= 1) {
        return '100%'
    }
    if (rate >= 0.99) {
        return `${Math.min(99.9, Math.floor(rate * 1000) / 10)}%`
    }
    return formatPercent(rate)
}

export function formatDuration(ms: number): string {
    return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`
}

export function formatHour(weekday: number, hour: number): string {
    const suffix = hour < 12 ? 'am' : 'pm'
    const twelveHour = hour % 12 === 0 ? 12 : hour % 12
    return `${WEEKDAYS[weekday - 1]}, ${twelveHour} ${suffix}`
}

/** A short name for the project's timezone, such as "GMT+1" or "PST", or the IANA name when there is none. */
export function formatTimezone(timezone: string): string {
    try {
        const parts = new Intl.DateTimeFormat('en-US', { timeZone: timezone, timeZoneName: 'short' }).formatToParts(
            new Date()
        )
        return parts.find((part) => part.type === 'timeZoneName')?.value ?? timezone
    } catch {
        return timezone
    }
}

/** One line on what the busiest hour says about the agents. Weekday runs 1 (Monday) to 7 (Sunday). */
export function rushHourLine(weekday: number, hour: number, nightShift: boolean): string {
    if (nightShift || hour >= 22 || hour < 5) {
        return 'Your agents worked the night shift.'
    }
    if (weekday >= 6) {
        return 'Your agents worked through the weekend.'
    }
    if (hour < 9) {
        return 'Your agents were already hard at work.'
    }
    if (hour < 17) {
        return 'Right in the middle of the workday.'
    }
    return 'Your agents kept going after hours.'
}

/**
 * How many times busier the peak hour was than the average hour. Heat is linear with the peak at 100, so
 * the ratio is exact apart from rounding, which only matters when the average cell is small.
 */
export function peakMultiple(heat: readonly number[]): string | null {
    const mean = heat.reduce((sum, level) => sum + level, 0) / (heat.length || 1)
    if (mean <= 0) {
        return null
    }
    const multiple = 100 / mean
    if (multiple < 1.5) {
        return null
    }
    return multiple >= 10 ? 'over 10×' : `${multiple.toFixed(1)}×`
}

/** The tiles on the share card: only values from cards the project actually has, six at most. */
export function shareTiles(cards: MCPWrappedCardsApi): ShareTile[] {
    const tiles: ShareTile[] = [{ label: 'Tool calls', value: humanFriendlyNumber(cards.tool_calls.total_calls) }]
    const topTool = cards.top_tools.tools[0]
    if (topTool) {
        tiles.push({ label: 'Top tool', value: topTool.tool })
    }
    tiles.push({ label: 'Error-free calls', value: formatSuccessRate(cards.reliability.success_rate) })
    const topApp = cards.apps?.shares.find((share) => share.name !== OTHER)
    if (topApp) {
        tiles.push({ label: 'Top app', value: topApp.name })
    }
    if (cards.rush_hour) {
        tiles.push({
            label: 'Rush hour',
            value: formatHour(cards.rush_hour.weekday, cards.rush_hour.hour).replace(',', ''),
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
