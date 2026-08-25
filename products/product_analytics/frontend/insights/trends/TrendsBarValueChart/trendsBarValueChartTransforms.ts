import type { BarChartConfig, Series } from '@posthog/quill-charts'

// ActionsBarValue renders aggregated totals as a horizontal bar per series/breakdown — a single
// quill series whose per-bar entries carry the color and label. Kept dependency-neutral (quill
// only) so the MCP app can import it; the web TrendsBarChart transforms pull in frontend-only
// modules (lib/utils, ~/queries, scenes/...) and can't be imported outside the frontend bundle.
export interface TrendsBarValueItem {
    label: string
    value: number | null | undefined
}

export interface BuildTrendsBarValueSeriesOpts {
    getColor: (index: number) => string
}

export function buildTrendsBarValueSeries(items: TrendsBarValueItem[], opts: BuildTrendsBarValueSeriesOpts): Series[] {
    return [
        {
            key: 'total',
            label: 'Total',
            data: items.map((item) => (Number.isFinite(item.value) ? (item.value as number) : 0)),
            bars: items.map((item, index) => ({ color: opts.getColor(index), label: item.label })),
        },
    ]
}

export function buildTrendsBarValueConfig(): BarChartConfig {
    return {
        axisOrientation: 'horizontal',
        showGrid: true,
        barCornerRadius: 4,
        bars: { fitToHeight: true },
    }
}
