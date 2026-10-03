import type { MetricsDisplaySettings } from '~/queries/schema/schema-general'

import type { MetricsExemplar } from '../components/MetricsExemplarMarkers'
import type { MetricsChartSeries } from '../components/metricsSeries'
import { BarGaugePanel } from './BarGaugePanel'
import { GaugePanel } from './GaugePanel'
import { seriesUnit } from './metricsReduce'
import { resolvePanelType } from './registry'
import { StatPanel } from './StatPanel'
import { TablePanel } from './TablePanel'
import { TimeSeriesPanel } from './TimeSeriesPanel'

/** A series with its own unit resolved: the display override wins, then the series'
 * ingested unit — but only when no other series carries a different unit, since a tile
 * mixes the values on one chart. A mixed-unit result renders bare numbers rather than
 * mislabeling one series with another's unit. */
function withResolvedUnits(series: MetricsChartSeries[], displayUnit: string | undefined): MetricsChartSeries[] {
    if (displayUnit) {
        return series.map((s) => ({ ...s, unit: displayUnit }))
    }
    const shared = seriesUnit(series, undefined)
    return series.map((s) => ({ ...s, unit: shared }))
}

/** The single dispatch point for a metrics tile: resolve the display type and render the
 * matching panel. `line`/`area`/`bar` are the time-series panel; `heatmap` renders here as a
 * line chart because the histogram runner is not wired to it yet, so a tile never blanks. */
export function MetricsPanel({
    series,
    display,
    fallbackName,
    exemplars,
}: {
    series: MetricsChartSeries[]
    display?: MetricsDisplaySettings
    fallbackName: string
    exemplars?: MetricsExemplar[]
}): JSX.Element {
    const type = resolvePanelType(display)
    const resolvedSeries = withResolvedUnits(series, display?.unit)

    switch (type) {
        case 'stat':
            return <StatPanel series={resolvedSeries} display={display ?? {}} fallbackName={fallbackName} />
        case 'gauge':
            return <GaugePanel series={resolvedSeries} display={display ?? {}} fallbackName={fallbackName} />
        case 'bargauge':
            return <BarGaugePanel series={resolvedSeries} display={display ?? {}} fallbackName={fallbackName} />
        case 'table':
            return <TablePanel series={resolvedSeries} display={display ?? {}} fallbackName={fallbackName} />
        case 'heatmap':
        // The histogram runner is not wired to the heatmap panel yet; fall through to a
        // time series so the tile shows the metric rather than a blank until then.
        default:
            return (
                <TimeSeriesPanel
                    series={resolvedSeries}
                    display={display ?? {}}
                    fallbackName={fallbackName}
                    exemplars={exemplars}
                />
            )
    }
}
