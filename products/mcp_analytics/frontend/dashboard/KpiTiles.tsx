import { Link } from '@posthog/lemon-ui'
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
import { Card, CardContent, Skeleton } from '@posthog/quill-primitives'

import { formatPercentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { type KPIData, KPIMetric } from '../mcpDashboardOverviewLogic'
import { formatBucketLabel, formatMs, formatNumber } from './formatters'

interface TileSpec {
    label: string
    metric: KPIMetric
    href: string
    format: (n: number) => string
    color: string
    loading: boolean
    // What the resting headline summarizes ('Total' | 'Avg'), like the metric insight's subtitle.
    summaryLabel: string
    // Overrides the summary caption — used to flag a tile whose value isn't
    // scoped by the dashboard filters.
    subtitle?: string
}

function KPITile({ tile, theme }: { tile: TileSpec; theme: ChartTheme }): JSX.Element {
    const { metric } = tile
    const hasSparkline = metric.sparkline.length > 0

    return (
        <Link to={tile.href} subtle className="group/tile flex h-full">
            <Card
                size="sm"
                flush={hasSparkline}
                className="flex-1 transition-transform group-hover/tile:-translate-y-0.5"
            >
                {tile.loading ? (
                    <CardContent className="flex flex-col gap-2">
                        <Skeleton className="h-3 w-16" />
                        <Skeleton className="h-7 w-20" />
                    </CardContent>
                ) : (
                    <Metric
                        className="px-3 text-primary"
                        value={metric.value}
                        data={hasSparkline ? metric.sparkline : undefined}
                        labels={hasSparkline ? metric.sparklineLabels.map(formatBucketLabel) : undefined}
                        theme={theme}
                        color={tile.color}
                        goodDirection={metric.goodDirection}
                        formatValue={tile.format}
                        // Window-over-window pill (suppressed without prior-window data); hovering a
                        // point swaps it for the point-vs-previous delta, like the metric insight.
                        change={metric.deltaPct !== null ? { value: metric.deltaPct } : null}
                        changeTooltip={
                            metric.deltaPct !== null
                                ? `vs. ${tile.format(metric.previousValue)} in the previous period`
                                : undefined
                        }
                        hoverChangeFromPreviousPoint
                        // Resting caption only — hovering a sparkline point swaps in that bucket's label.
                        restingSubtitle={tile.subtitle ?? tile.summaryLabel}
                        sparklineHeight={50}
                    >
                        <MetricHeader>
                            <MetricTitle>{tile.label}</MetricTitle>
                            <MetricDelta />
                        </MetricHeader>
                        <MetricValue className="mt-2" />
                        <MetricSubtitle className="mt-1" />
                        <MetricSparkline className="mt-3 -mx-3 relative top-[6px]" />
                    </Metric>
                )}
            </Card>
        </Link>
    )
}

export function KpiTiles({
    kpis,
    users,
    intentClusterCount,
    kpisLoading,
    usersLoading,
    theme,
}: {
    kpis: KPIData
    users: KPIMetric
    intentClusterCount: KPIMetric
    kpisLoading: boolean
    usersLoading: boolean
    theme: ChartTheme
}): JSX.Element {
    const tiles: TileSpec[] = [
        {
            label: 'Users',
            metric: users,
            // Person identity (email/name) is resolved on the Sessions tab, so that's the drill-down for "who".
            href: urls.mcpAnalyticsSessions(),
            format: formatNumber,
            color: theme.colors[2],
            loading: usersLoading,
            summaryLabel: 'Total',
        },
        {
            label: 'Sessions',
            metric: kpis.sessions,
            href: urls.mcpAnalyticsSessions(),
            format: formatNumber,
            color: theme.colors[0],
            loading: kpisLoading,
            summaryLabel: 'Total',
        },
        {
            label: 'Tool calls',
            metric: kpis.toolCalls,
            href: urls.mcpAnalyticsToolQuality(),
            format: formatNumber,
            color: theme.colors[0],
            loading: kpisLoading,
            summaryLabel: 'Total',
        },
        {
            label: 'Error rate',
            metric: kpis.errorRatePct,
            href: urls.mcpAnalyticsSessions(),
            format: (n) => formatPercentage(n, { compact: true }),
            color: theme.colors[4],
            loading: kpisLoading,
            summaryLabel: 'Avg',
        },
        {
            label: 'p95 latency',
            metric: kpis.p95LatencyMs,
            href: urls.mcpAnalyticsToolQuality(),
            format: formatMs,
            color: theme.colors[0],
            loading: kpisLoading,
            summaryLabel: 'Avg',
        },
        {
            label: 'Intent clusters',
            metric: intentClusterCount,
            href: urls.mcpAnalyticsIntentClustering(),
            format: formatNumber,
            color: theme.colors[6],
            loading: false,
            summaryLabel: 'Total',
            // Clusters come from the latest clustering snapshot across all sessions, so
            // unlike the other tiles this count isn't scoped by the date or test-account
            // filters. Label it so the grid doesn't read as a single consistent scope.
            subtitle: 'Latest run · all sessions',
        },
    ]

    // Wrap the six tiles only into rows that divide evenly (6 → 3+3 → 2+2+2), never a lone
    // trailing card. Container queries key off the card area's own width, so the sidebar can't
    // push it to an awkward 5+1 the way viewport breakpoints or plain auto-fit would.
    return (
        <div className="@container">
            <div className="grid grid-cols-2 gap-3 @xl:grid-cols-3 @6xl:grid-cols-6">
                {tiles.map((tile) => (
                    <KPITile key={tile.label} tile={tile} theme={theme} />
                ))}
            </div>
        </div>
    )
}
