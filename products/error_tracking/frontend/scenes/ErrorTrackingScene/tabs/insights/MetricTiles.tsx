import './MetricTiles.scss'

import { LemonSkeleton } from '@posthog/lemon-ui'
import { type ChartTheme } from '@posthog/quill-charts'
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
import { Card } from 'lib/ui/quill'
import { formatPercentage, humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { InsightMetric, InsightsMetrics } from './insightsMetrics'

const SPARKLINE_HEIGHT = 50
// The same height as a class, for the placeholder standing in for the chart. Tailwind reads class
// names out of the source, so it cannot be built from the constant: keep the two equal, or the tile
// changes height the moment the data lands.
const SPARKLINE_HEIGHT_CLASS = 'h-[50px]'

// The tile's own layout, shared by the loaded and the loading state so the grid keeps one height
// across the load. Metric owns these classes when it renders; the skeleton repeats them because it
// stands in for the same boxes.
const TILE_BODY_CLASS = 'flex h-full flex-col px-3 text-primary'
const TILE_HEADER_CLASS = 'flex items-start justify-between gap-2'
const TILE_TITLE_CLASS = 'text-sm font-medium'
const TILE_SUBTITLE_CLASS = 'mt-1 text-sm opacity-60'
const NO_VALUE = '-'

/** A rate a hair under 100 must not render as a clean "100%" — that reads as "no crashes at all". */
function formatRate(value: number): string {
    return formatPercentage(Math.floor(value * 10) / 10, { precise: true, compact: true })
}

interface TileSpec {
    label: string
    metric: InsightMetric
    format: (value: number) => string
    color: string
    /** Caption under the headline. On hover it yields to the hovered point's bucket label. */
    subtitle: string
}

function MetricTile({
    tile,
    theme,
    incompleteTail,
}: {
    tile: TileSpec
    theme: ChartTheme
    incompleteTail: boolean
}): JSX.Element {
    // The final bucket is the interval still in progress, so dash it. Without that a period only a few
    // hours old reads as a collapse in exceptions rather than a period that has not finished.
    const dashedFromIndex =
        incompleteTail && tile.metric.sparkline.length >= 2 ? tile.metric.sparkline.length - 1 : undefined
    const { value, previousValue, deltaPct } = tile.metric
    // A zero delta is not a rise, so it gets no pill rather than the change badge's upward chevron.
    const change = value !== null && deltaPct !== null && deltaPct !== 0 ? { value: deltaPct } : null

    return (
        <Card size="sm" flush className="flex-1">
            <Metric
                className={TILE_BODY_CLASS}
                value={value ?? 0}
                data={tile.metric.sparkline}
                labels={tile.metric.sparklineLabels}
                theme={theme}
                color={tile.color}
                goodDirection={tile.metric.goodDirection}
                formatValue={value === null ? () => NO_VALUE : tile.format}
                change={change}
                changeTooltip={
                    change !== null && previousValue !== null
                        ? `vs. ${tile.format(previousValue)} in the previous period`
                        : undefined
                }
                hoverChangeFromPreviousPoint
                restingSubtitle={tile.subtitle}
                sparklineHeight={SPARKLINE_HEIGHT}
                sparklineDashedFromIndex={dashedFromIndex}
            >
                <MetricHeader className={TILE_HEADER_CLASS}>
                    <MetricTitle className={TILE_TITLE_CLASS}>{tile.label}</MetricTitle>
                    <MetricDelta />
                </MetricHeader>
                <MetricValue className="mt-2 h-10" />
                <MetricSubtitle className={TILE_SUBTITLE_CLASS} />
                <MetricSparkline className="mt-3 -mx-3" />
            </Metric>
        </Card>
    )
}

// The label is a fixed property of the tile rather than a query result, so it renders for real while
// the numbers and the chart load.
function LoadingTile({ tile }: { tile: TileSpec }): JSX.Element {
    return (
        <Card size="sm" flush className="flex-1">
            <div className={TILE_BODY_CLASS}>
                <div className={TILE_HEADER_CLASS}>
                    <div className={TILE_TITLE_CLASS}>{tile.label}</div>
                    {/* The change pill is 1rem tall against a 1.25rem title, so this can never be
                        what sets the header's height. */}
                    <LemonSkeleton className="h-4 w-12 rounded-full" />
                </div>
                <LemonSkeleton className="mt-2 h-10 w-24" />
                {/* Hidden rather than dropped: the real caption still holds the box it will occupy,
                    so the tile keeps one height across the load without a second element having to
                    match its line height. */}
                <div className={`${TILE_SUBTITLE_CLASS} invisible`}>{tile.subtitle}</div>
                {/* `top-[6px]` mirrors MetricSparkline, which rests the line on the card's bottom edge. */}
                <LemonSkeleton
                    className={`MetricTiles__chart-skeleton relative top-[6px] mt-3 -mx-3 rounded-none ${SPARKLINE_HEIGHT_CLASS}`}
                />
            </div>
        </Card>
    )
}

export function MetricTiles({
    metrics,
    loading,
    incompleteTail,
}: {
    metrics: InsightsMetrics
    loading: boolean
    // When true, the last bucket is the interval still in progress. Required rather than optional: an
    // omitted prop silently renders a partial period as settled data.
    incompleteTail: boolean
}): JSX.Element {
    const theme = useChartTheme()

    const tiles: TileSpec[] = [
        {
            label: 'Exceptions',
            metric: metrics.exceptions,
            format: humanFriendlyLargeNumber,
            color: theme.colors[4],
            subtitle: 'Total',
        },
        {
            label: 'Affected users',
            metric: metrics.affectedUsers,
            format: humanFriendlyLargeNumber,
            color: theme.colors[2],
            subtitle: 'Total',
        },
        {
            label: 'Sessions',
            metric: metrics.sessions,
            format: humanFriendlyLargeNumber,
            color: theme.colors[0],
            subtitle: 'Total',
        },
        {
            label: 'Sessions with a crash',
            metric: metrics.crashSessions,
            format: humanFriendlyLargeNumber,
            color: theme.colors[4],
            subtitle: 'Total',
        },
        {
            label: 'Crash-free sessions',
            metric: metrics.crashFreeRate,
            format: formatRate,
            color: theme.colors[0],
            subtitle: 'This period',
        },
        {
            label: 'Releases',
            metric: metrics.releases,
            format: humanFriendlyLargeNumber,
            color: theme.colors[6],
            subtitle: 'Seen in this period',
        },
    ]

    // Wrap the six tiles only into rows that divide evenly (6 → 3+3 → 2+2+2), never a lone trailing
    // card. Container queries key off the card area's own width, so an open side panel cannot push it
    // to an awkward 5+1 the way viewport breakpoints would.
    return (
        <div className="@container">
            <div className="grid grid-cols-2 gap-3 @xl:grid-cols-3 @6xl:grid-cols-6">
                {tiles.map((tile) =>
                    loading ? (
                        <LoadingTile key={tile.label} tile={tile} />
                    ) : (
                        <MetricTile key={tile.label} tile={tile} theme={theme} incompleteTail={incompleteTail} />
                    )
                )}
            </div>
        </div>
    )
}
