import { useValues } from 'kea'

import {
    Metric,
    MetricDelta,
    MetricHeader,
    MetricSparkline,
    MetricSubtitle,
    MetricTitle,
    MetricValue,
} from '@posthog/quill-components/metric'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'

import { flattenSeriesRows } from './metricsReduce'
import { thresholdColorToken } from './metricsThresholds'
import { metricValuesFormatter } from './metricsUnits'
import type { MetricsPanelProps } from './registry'
import { resolveReducer } from './registry'

const FALLBACK_COLOR = 'data-color-1'
/** Cap on grouped stat cards so a high-cardinality groupBy does not flood the tile. */
const MAX_STAT_CARDS = 12
const GROUPED_SPARKLINE_HEIGHT = 40

/** A headline number with an optional sparkline, colored by threshold. One card per series when the
 * query groups, capped at `MAX_STAT_CARDS`. */
export function StatPanel({ series, display, fallbackName }: MetricsPanelProps): JSX.Element {
    const theme = useChartTheme()
    const { timezone } = useValues(teamLogic)
    const reducer = resolveReducer(display)
    const showsSparkline = display.statSparkline !== false
    // A series with no non-null point has nothing to headline; drop it rather than render a "—" card.
    const rows = flattenSeriesRows(series, [reducer]).filter((row) => row.values[reducer] !== null)
    // A single card fills the tile, and the tile title already names it. Grouped cards need their labels.
    const single = rows.length === 1
    const valueColor = display.thresholds?.length
        ? (v: number): string => getColorVar(thresholdColorToken(v, display.thresholds, FALLBACK_COLOR))
        : undefined

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
        const color = getColorVar(thresholdColorToken(value, display.thresholds, FALLBACK_COLOR))
        const data = row.series.points.map((p) => p.value ?? 0)
        // The headline shows the hovered sparkline point, so it shares one scale with every point.
        const formatValue = metricValuesFormatter(row.series.unit ?? undefined, [...data, value ?? 0])
        return (
            <Metric
                key={index}
                value={value ?? undefined}
                data={data}
                labels={row.series.points.map((p) => p.time)}
                formatLabel={(time) => dayjs(time).tz(timezone).format('D MMM HH:mm')}
                // The time shows only on hover. A blank caption at rest keeps its row, so the
                // sparkline does not resize under the cursor when the time appears.
                restingSubtitle={' '}
                theme={theme}
                color={color}
                formatValue={formatValue}
                valueColor={valueColor}
                sparklineFill={single}
                sparklineHeight={GROUPED_SPARKLINE_HEIGHT}
                className={cn('@container w-full min-w-0 px-0', !showsSparkline && single && 'justify-center')}
            >
                {!single && <MetricTitle>{name}</MetricTitle>}
                <MetricHeader className={cn('flex-wrap items-center', !single && 'mt-2')}>
                    <MetricValue className="text-2xl @min-[13rem]:text-3xl @min-[16rem]:text-4xl" />
                    <MetricDelta />
                </MetricHeader>
                {showsSparkline && (
                    <>
                        <MetricSubtitle className="mt-1" />
                        <MetricSparkline className="mt-2" />
                    </>
                )}
            </Metric>
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
