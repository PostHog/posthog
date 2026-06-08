import type { BarChartConfig, Series } from '@posthog/quill-charts'

// ActionsBarValue renders aggregated totals as a horizontal bar per series/breakdown — a single
// quill series whose per-bar entries carry the color and label.
export interface TrendsBarValueItem {
    label: string
    value: number
}

export interface BuildTrendsBarValueSeriesOpts {
    getColor: (index: number) => string
}

export function buildTrendsBarValueSeries(items: TrendsBarValueItem[], opts: BuildTrendsBarValueSeriesOpts): Series[] {
    return [
        {
            key: 'total',
            label: 'Total',
            data: items.map((item) => item.value),
            bars: items.map((item, index) => ({ color: opts.getColor(index), label: item.label })),
        },
    ]
}

export function buildTrendsBarValueConfig(): BarChartConfig {
    return {
        axisOrientation: 'horizontal',
        showGrid: true,
        bars: { cornerRadius: 4, fitToHeight: true },
    }
}
