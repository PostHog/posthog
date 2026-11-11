import { asRecord, isRecord } from '@/lib/records'

import type { RankedValueView, RankingView } from '../views'
import { asTrendsInsight, hasBreakdown, isSummableMath } from './metric'

type JsonRecord = Record<string, unknown>

// The server's placeholders for the values past the breakdown limit and for events without the property. The web
// shows them as "Other" and "None".
const BREAKDOWN_OTHER = '$$_posthog_breakdown_other_$$'
const BREAKDOWN_NULL = '$$_posthog_breakdown_null_$$'

/** A breakdown value as the web shows it. Several breakdowns give a list, joined with commas. */
export function breakdownLabel(value: unknown): string | null {
    if (Array.isArray(value)) {
        const parts = value.map(breakdownLabel).filter((part): part is string => part !== null)
        return parts.length > 0 ? parts.join(', ') : null
    }
    if (value === BREAKDOWN_OTHER) {
        return 'Other'
    }
    if (value === BREAKDOWN_NULL) {
        return 'None'
    }
    return typeof value === 'string' || typeof value === 'number' ? String(value) : null
}

/** A series label with the server's breakdown placeholders replaced, such as "$pageview - Other". */
export function displaySeriesLabel(label: string): string {
    return label.split(BREAKDOWN_OTHER).join('Other').split(BREAKDOWN_NULL).join('None')
}

// Trends displays that total the window per series and breakdown value. The phone ranks the totals as bars.
const RANKING_DISPLAYS: ReadonlySet<string> = new Set([
    'ActionsBarValue',
    'ActionsTable',
    'ActionsPie',
    'ActionsDonut',
    'ActionsProportionBar',
])

function finite(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function seriesNodes(source: JsonRecord): JsonRecord[] {
    return Array.isArray(source.series) ? source.series.filter(isRecord) : []
}

function hasFormula(source: JsonRecord): boolean {
    const filter = asRecord(source.trendsFilter)
    return Boolean(filter?.formula) || (Array.isArray(filter?.formulaNodes) && filter.formulaNodes.length > 0)
}

function isGroupedRest(entry: JsonRecord): boolean {
    return entry.breakdown_value === BREAKDOWN_OTHER
}

function rankedValue(entry: JsonRecord, index: number): RankedValueView | null {
    const value = finite(entry.aggregated_value)
    if (value === undefined) {
        return null
    }
    const order = finite(asRecord(entry.action)?.order) ?? index
    const breakdown = breakdownLabel(entry.breakdown_value)
    const label =
        typeof entry.label === 'string' && entry.label !== ''
            ? displaySeriesLabel(entry.label)
            : (breakdown ?? `Series ${order + 1}`)
    return { key: `${order}:${JSON.stringify(entry.breakdown_value ?? null)}`, label, value }
}

/** True for a trends insight in a value bar, table or pie display, which the phone ranks as bars. */
export function isRankingQuery(query: unknown): boolean {
    const display = asRecord(asTrendsInsight(query)?.source.trendsFilter)?.display
    return typeof display === 'string' && RANKING_DISPLAYS.has(display)
}

/**
 * The totals of a value bar, table or pie insight, highest first, with "Other" last as the web lists it. The previous
 * period of a compare is left out: the bars rank the current window.
 */
export function rankingView(query: unknown, result: unknown): RankingView | null {
    const insight = asTrendsInsight(query)
    if (!insight || !isRankingQuery(query)) {
        return null
    }
    const entries = Array.isArray(result) ? result.filter(isRecord) : []
    const current = entries.filter((entry) => entry.compare_label !== 'previous')
    const ranked = (list: JsonRecord[]): RankedValueView[] =>
        list
            .map(rankedValue)
            .filter((row): row is RankedValueView => row !== null)
            .sort((a, b) => b.value - a.value)
    const rows = [...ranked(current.filter((entry) => !isGroupedRest(entry))), ...ranked(current.filter(isGroupedRest))]
    const source = insight.source
    const nodes = seriesNodes(source)
    // Only the breakdown values of one series add up, and only for math that counts events, not people.
    const summable = nodes.length === 1 && hasBreakdown(source) && !hasFormula(source) && isSummableMath(nodes[0]?.math)
    return { rows, total: summable ? rows.reduce((total, row) => total + row.value, 0) : null }
}
