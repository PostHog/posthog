import { MetricCard } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'

import { flattenSeriesRows } from './metricsReduce'
import { thresholdColor } from './metricsThresholds'
import { formatMetricValue } from './metricsUnits'
import type { MetricsPanelProps } from './registry'
import { resolveReducer } from './registry'

const FALLBACK_COLOR = 'data-color-1'
/** Cap on grouped stat cards so a high-cardinality groupBy does not flood the tile. */
const MAX_STAT_CARDS = 12

/** A headline number with a sparkline, colored by threshold. One card per series when the
 * query groups, capped at `MAX_STAT_CARDS`. */
export function StatPanel({ series, display, unit, fallbackName }: MetricsPanelProps): JSX.Element {
    const theme = useChartTheme()
    const reducer = resolveReducer(display)
    // A series with no non-null point has nothing to headline; drop it rather than render a "—" card.
    const rows = flattenSeriesRows(series, [reducer]).filter((row) => row.values[reducer] !== null)

    const cards = rows.slice(0, MAX_STAT_CARDS).map((row, index) => {
        const value = row.values[reducer]
        const name =
            Object.entries(row.labels)
                .map(([k, v]) => `${k}=${v}`)
                .join(', ') ||
            row.metricName ||
            fallbackName
        const color = getColorVar(thresholdColor(value, display.thresholds, FALLBACK_COLOR))
        return (
            <MetricCard
                key={index}
                title={name}
                value={value ?? undefined}
                data={row.series.points.map((p) => p.value ?? 0)}
                labels={row.series.points.map((p) => p.time)}
                theme={theme}
                color={color}
                formatValue={(v) => formatMetricValue(v, unit)}
                sparklineFill
            />
        )
    })

    return (
        <div className="flex h-full w-full flex-wrap content-start items-start gap-3 overflow-auto p-2">
            {cards.length > 0 ? (
                <>
                    {cards}
                    {rows.length > MAX_STAT_CARDS && (
                        <span className="text-xs text-secondary self-center">
                            and {rows.length - MAX_STAT_CARDS} more
                        </span>
                    )}
                </>
            ) : (
                <div className="flex flex-1 items-center justify-center text-secondary text-sm">No data</div>
            )}
        </div>
    )
}
