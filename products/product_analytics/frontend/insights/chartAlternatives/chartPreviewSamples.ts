import type { BoxPlotDatum } from '~/queries/schema/schema-general'
import type { TrendResult } from '~/types'

const SAMPLE_COUNTRIES: [string, number][] = [
    ['US', 1840],
    ['GB', 920],
    ['DE', 610],
    ['IN', 540],
    ['CA', 430],
    ['FR', 380],
    ['BR', 310],
    ['AU', 260],
    ['JP', 220],
    ['NL', 170],
]

const SAMPLE_BOX_PLOT_DAYS = 7

function sampleAction(result: TrendResult | undefined): Pick<TrendResult, 'action' | 'label'> {
    return { action: result?.action ?? null, label: result?.label ?? 'Sample' }
}

export function sampleWorldMapRows(loaded: TrendResult[]): unknown[] {
    const base = sampleAction(loaded[0])
    return SAMPLE_COUNTRIES.map(([code, value]) => ({
        ...base,
        breakdown_value: code,
        data: [],
        days: [],
        labels: [],
        count: 0,
        aggregated_value: value,
    }))
}

export function sampleCalendarHeatmapRows(loaded: TrendResult[]): unknown[] {
    const data: { row: number; column: number; value: number }[] = []
    const rows = Array.from({ length: 7 }, () => 0)
    const columns = Array.from({ length: 24 }, () => 0)
    let all = 0
    for (let row = 0; row < 7; row++) {
        const weekday = row >= 1 && row <= 5
        for (let column = 0; column < 24; column++) {
            const working = column >= 8 && column <= 18
            const value = (weekday ? 40 : 12) + (working ? 60 : 0) + ((row * 7 + column * 3) % 11)
            data.push({ row, column, value })
            rows[row] += value
            columns[column] += value
            all += value
        }
    }
    return [
        {
            ...sampleAction(loaded[0]),
            data: [],
            days: [],
            labels: [],
            count: all,
            aggregated_value: all,
            calendar_heatmap_data: {
                data,
                rowAggregations: rows.map((value, row) => ({ row, value })),
                columnAggregations: columns.map((value, column) => ({ column, value })),
                allAggregations: all,
            },
        },
    ]
}

export function sampleBoxPlotRows(loaded: TrendResult[]): BoxPlotDatum[] {
    const first = loaded[0]
    const days = first?.days?.length
        ? first.days
        : Array.from({ length: SAMPLE_BOX_PLOT_DAYS }, (_, i) => `Day ${i + 1}`)
    const labels = first?.labels?.length === days.length ? first.labels : days
    return days.map((day, index) => {
        const median = 40 + ((index * 13) % 17)
        return {
            day,
            label: labels[index],
            min: median - 25,
            p25: median - 10,
            median,
            p75: median + 12,
            max: median + 30,
            mean: median + 2,
            series_index: 0,
            series_label: first?.label ?? 'Sample',
        }
    })
}
