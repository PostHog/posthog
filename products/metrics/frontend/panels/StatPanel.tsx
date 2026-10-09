import { useValues } from 'kea'

import { MetricCard } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'

import { flattenSeriesRows } from './metricsReduce'
import { thresholdColor } from './metricsThresholds'
import { formatMetricValue } from './metricsUnits'
import type { MetricsPanelProps } from './registry'
import { resolveReducer } from './registry'

const FALLBACK_COLOR = 'data-color-1'
/** Cap on grouped stat cards so a high-cardinality groupBy does not flood the tile. */
const MAX_STAT_CARDS = 12
const GROUPED_SPARKLINE_HEIGHT = 40

/** A headline number with a sparkline, colored by threshold. One card per series when the
 * query groups, capped at `MAX_STAT_CARDS`. */
export function StatPanel({ series, display, fallbackName }: MetricsPanelProps): JSX.Element {
    const theme = useChartTheme()
    const { timezone } = useValues(teamLogic)
    const reducer = resolveReducer(display)
    // A series with no non-null point has nothing to headline; drop it rather than render a "—" card.
    const rows = flattenSeriesRows(series, [reducer]).filter((row) => row.values[reducer] !== null)
    // A single card fills the tile, and the tile title already names it. Grouped cards need their labels.
    const single = rows.length === 1

    if (rows.length === 0) {
        return <div className="flex h-full w-full items-center justify-center text-secondary text-sm">No data</div>
    }

    const cards = rows.slice(0, MAX_STAT_CARDS).map((row, index) => {
        const value = row.values[reducer] ?? null
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
                title={single ? null : name}
                value={value ?? undefined}
                data={row.series.points.map((p) => p.value ?? 0)}
                labels={row.series.points.map((p) => p.time)}
                formatLabel={(time) => dayjs(time).tz(timezone).format('D MMM HH:mm')}
                // The time shows only on hover. A blank caption at rest keeps its row, so the
                // sparkline does not resize under the cursor when the time appears.
                restingSubtitle={' '}
                theme={theme}
                color={color}
                formatValue={(v) => formatMetricValue(v, row.series.unit ?? undefined)}
                headlineClassName="whitespace-nowrap text-2xl @min-[13rem]:text-3xl @min-[16rem]:text-4xl"
                changeInline
                sparklineFill={single}
                sparklineHeight={GROUPED_SPARKLINE_HEIGHT}
                sparklineClassName="mt-2"
                className={cn('@container min-w-0', single && 'h-full')}
            />
        )
    })

    return (
        <div
            className={cn(
                'h-full w-full p-2',
                single
                    ? 'flex overflow-hidden'
                    : 'grid grid-cols-[repeat(auto-fill,minmax(12rem,1fr))] content-start gap-3 overflow-auto'
            )}
        >
            {cards}
            {rows.length > MAX_STAT_CARDS && (
                <span className="text-xs text-secondary self-center">and {rows.length - MAX_STAT_CARDS} more</span>
            )}
        </div>
    )
}
