import { type HarnessRow } from '../mcpDashboardOverviewLogic'

export type HarnessChartRow = Omit<HarnessRow, 'sessions'> & { sessions: number | null }

export function summarizeHarnessBreakdown(rows: HarnessRow[]): {
    totalCalls: number
    chartRows: HarnessChartRow[]
    allRows: HarnessRow[]
} {
    const allRows = [...rows].sort((a, b) => b.total_calls - a.total_calls || a.category.localeCompare(b.category))
    const namedRows = allRows.filter((row) => row.category !== 'Other')
    const chartRows: HarnessChartRow[] = namedRows.slice(0, 6)
    const remainder = [...namedRows.slice(6), ...allRows.filter((row) => row.category === 'Other')]
    if (remainder.length > 0) {
        const total_calls = remainder.reduce((sum, row) => sum + row.total_calls, 0)
        const errors = remainder.reduce((sum, row) => sum + row.errors, 0)
        chartRows.push({
            category: 'Other',
            total_calls,
            errors,
            error_rate_pct: total_calls > 0 ? (errors / total_calls) * 100 : 0,
            // Sessions can contain calls from multiple harnesses, so their counts cannot be added.
            sessions: null,
        })
    }
    return { totalCalls: allRows.reduce((sum, row) => sum + row.total_calls, 0), chartRows, allRows }
}

export function harnessChartLabel(category: string): string {
    return category === 'Other' ? 'Other harnesses' : category
}
