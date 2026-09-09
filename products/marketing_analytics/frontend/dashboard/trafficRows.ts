import { CompareLabelType, TrendResult } from '~/types'

export interface TrafficRow {
    name: string
    current: Record<number, number>
    previous: Record<number, number>
}

export function trafficRows(
    results: Pick<TrendResult, 'breakdown_value' | 'aggregated_value' | 'order' | 'action' | 'compare_label'>[]
): TrafficRow[] {
    const rows = new Map<string, TrafficRow>()
    for (const result of results) {
        const name = Array.isArray(result.breakdown_value)
            ? result.breakdown_value.join(' / ')
            : String(result.breakdown_value ?? 'Unknown')
        const order = result.order ?? result.action?.order
        if (order === undefined || !Number.isFinite(result.aggregated_value)) {
            continue
        }
        const row = rows.get(name) ?? { name, current: {}, previous: {} }
        const period = result.compare_label === CompareLabelType.Previous ? row.previous : row.current
        period[order] = result.aggregated_value
        rows.set(name, row)
    }
    return [...rows.values()].sort((a, b) => (b.current[0] ?? 0) - (a.current[0] ?? 0))
}
