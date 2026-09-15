import type { MetricsDisplaySettings, MetricsDisplayType } from '~/queries/schema/schema-general'

import type { MetricsChartSeries } from '../components/metricsSeries'

/** The props every metrics panel receives. `unit` is the resolved unit (display override,
 * else the first series' ingested unit). A panel is a pure function of these props. */
export interface MetricsPanelProps {
    series: MetricsChartSeries[]
    display: MetricsDisplaySettings
    unit: string | undefined
    fallbackName: string
}

export interface MetricsPanelDefinition {
    /** Human label for the chart-type picker. */
    label: string
    /** The panel needs a `groupBy` to be meaningful; the picker disables it otherwise. */
    needsGroupBy?: boolean
    /** The panel needs a histogram metric; the picker disables it otherwise. */
    needsHistogram?: boolean
}

/** Static metadata per panel type. The render components register themselves in
 * `panelComponents.tsx` (kept separate so this module stays React-free and cheap to
 * import from logic). The picker and the dispatcher both read this list, so adding a
 * panel is one component file plus one entry here. */
export const METRICS_PANELS: Record<MetricsDisplayType, MetricsPanelDefinition> = {
    line: { label: 'Line' },
    area: { label: 'Area' },
    bar: { label: 'Bar' },
    stat: { label: 'Stat' },
    gauge: { label: 'Gauge' },
    bargauge: { label: 'Bar gauge', needsGroupBy: true },
    table: { label: 'Table' },
    heatmap: { label: 'Heatmap', needsHistogram: true },
}

/** The display type to render for a query, falling back to `line` for an unknown or
 * unrenderable type so an older or newer client never blanks a tile. */
export function resolvePanelType(display: MetricsDisplaySettings | undefined): MetricsDisplayType {
    const type = display?.type ?? 'line'
    return type in METRICS_PANELS ? type : 'line'
}

/** Map the deprecated `statSummary` onto `reduce`. Saved insights keep working. */
export function statSummaryToReduce(summary: 'latest' | 'average' | 'total' | undefined): 'last' | 'mean' | 'sum' {
    switch (summary) {
        case 'average':
            return 'mean'
        case 'total':
            return 'sum'
        default:
            return 'last'
    }
}

/** The reducer a panel should use: the explicit `reduce`, else the deprecated
 * `statSummary`, else `last`. */
export function resolveReducer(
    display: MetricsDisplaySettings | undefined
): 'last' | 'mean' | 'min' | 'max' | 'sum' | 'delta' {
    return display?.reduce ?? statSummaryToReduce(display?.statSummary)
}
