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

/**
 * A share as a percentage that stays honest at both ends: a small non-zero share never reads as 0%,
 * and a share short of everything never reads as 100%.
 */
export function formatPercent(share: number): string {
    if (share <= 0) {
        return '0%'
    }
    if (share >= 1) {
        return '100%'
    }
    const percent = share * 100
    if (percent < 0.1) {
        return '<0.1%'
    }
    if (percent < 10) {
        return `${trimZero(percent.toFixed(1))}%`
    }
    if (percent >= 99) {
        return `${trimZero(Math.min(99.9, Math.floor(percent * 10) / 10).toFixed(1))}%`
    }
    return `${Math.round(percent)}%`
}

function trimZero(value: string): string {
    return value.endsWith('.0') ? value.slice(0, -2) : value
}

/** One line on how reliable the server was, from the share of calls that returned without an error. */
export function reliabilityLine(rate: number): string {
    if (rate >= 0.995) {
        return 'Your server rarely missed a beat.'
    }
    if (rate >= 0.95) {
        return 'Your agents could count on you.'
    }
    if (rate >= 0.9) {
        return 'Mostly on point, with a few bumps.'
    }
    return 'A bumpy year, with room to improve.'
}

/** The error share as a count out of 100 calls, which reads more concretely than a percentage. */
export function errorLine(rate: number): string {
    if (rate >= 1) {
        return 'Not a single tool call hit an error.'
    }
    const errorsPer100 = Math.round((1 - rate) * 100)
    return errorsPer100 < 1
        ? 'Fewer than 1 in 100 tool calls hit an error.'
        : `${errorsPer100} in every 100 tool calls hit an error.`
}

/** A text size for a tool name, stepping down as it gets longer so long names stay on two lines or fewer. */
export function toolNameSize(name: string, sizes: readonly [string, string, string]): string {
    return name.length <= 14 ? sizes[0] : name.length <= 24 ? sizes[1] : sizes[2]
}

/** One line on how quick the server felt, from the p95 response time across all calls. */
export function speedLine(p95Ms: number): string {
    if (p95Ms < 300) {
        return 'Lightning fast.'
    }
    if (p95Ms < 1000) {
        return 'Quick on the draw.'
    }
    if (p95Ms < 5000) {
        return 'Your agents rarely waited long.'
    }
    return 'Some calls kept agents waiting.'
}

export function formatDuration(ms: number): string {
    if (ms < 1) {
        return '<1 ms'
    }
    if (ms < 999.5) {
        return `${Math.round(ms)} ms`
    }
    if (ms < 59_950) {
        return `${(ms / 1000).toFixed(1)} s`
    }
    if (ms < 3_597_000) {
        return `${(ms / 60_000).toFixed(1)} min`
    }
    return `${(ms / 3_600_000).toFixed(1)} h`
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
    const tiles: ShareTile[] = [{ label: 'Tool calls', value: formatCallCount(cards.tool_calls.total_calls) }]
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
