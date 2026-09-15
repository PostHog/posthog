import type { MetricsDisplaySettings } from '~/queries/schema/schema-general'

import type { MetricsExemplar } from '../components/MetricsExemplarMarkers'
import type { MetricsChartSeries } from '../components/metricsSeries'
import { BarGaugePanel } from './BarGaugePanel'
import { GaugePanel } from './GaugePanel'
import { resolvePanelType } from './registry'
import { StatPanel } from './StatPanel'
import { TablePanel } from './TablePanel'
import { TimeSeriesPanel } from './TimeSeriesPanel'

/** The single dispatch point for a metrics tile: resolve the display type and render the
 * matching panel. `line`/`area`/`bar` are the time-series panel; `heatmap` renders here as a
 * line chart until its histogram runner lands (PR 3), so a tile never blanks. */
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
    const unit = display?.unit ?? series.find((s) => s.unit)?.unit ?? undefined

    switch (type) {
        case 'stat':
            return <StatPanel series={series} display={display ?? {}} unit={unit} fallbackName={fallbackName} />
        case 'gauge':
            return <GaugePanel series={series} display={display ?? {}} unit={unit} fallbackName={fallbackName} />
        case 'bargauge':
            return <BarGaugePanel series={series} display={display ?? {}} unit={unit} fallbackName={fallbackName} />
        case 'table':
            return <TablePanel series={series} display={display ?? {}} unit={unit} fallbackName={fallbackName} />
        case 'heatmap':
        // Heatmap needs the histogram runner (PR 3); fall through to a time series so the
        // tile shows the metric rather than a blank until then.
        default:
            return (
                <TimeSeriesPanel
                    series={series}
                    display={display ?? {}}
                    unit={unit}
                    fallbackName={fallbackName}
                    exemplars={exemplars}
                />
            )
    }
}
