import { Link } from '@posthog/lemon-ui'
import { type ChartTheme, MetricCard } from '@posthog/quill-charts'
import { Card, CardContent, Skeleton } from '@posthog/quill-primitives'

import { formatPercentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { type KPIData, KPIMetric } from '../mcpDashboardOverviewLogic'
import { formatMs, formatNumber } from './formatters'

interface TileSpec {
    label: string
    metric: KPIMetric
    href: string
    format: (n: number) => string
    color: string
    loading: boolean
    // Overrides the default "vs. prior" comparison line — used to flag a tile
    // whose value isn't scoped by the dashboard filters.
    subtitle?: string
}

function KPITile({ tile, theme }: { tile: TileSpec; theme: ChartTheme }): JSX.Element {
    const { metric } = tile
    const hasSparkline = metric.sparkline.length > 0
    const hasComparison = metric.deltaPct !== null

    return (
        <Link to={tile.href} subtle className="group/tile flex h-full">
            <Card size="sm" className="flex-1 transition-transform group-hover/tile:-translate-y-0.5">
                {tile.loading ? (
                    <CardContent className="flex flex-col gap-2">
                        <Skeleton className="h-3 w-16" />
                        <Skeleton className="h-7 w-20" />
                    </CardContent>
                ) : (
                    <CardContent>
                        <MetricCard
                            className="text-primary"
                            title={tile.label}
                            value={metric.value}
                            data={hasSparkline ? metric.sparkline : undefined}
                            theme={theme}
                            color={tile.color}
                            goodDirection={metric.goodDirection}
                            formatValue={tile.format}
                            subtitle={
                                tile.subtitle ??
                                (hasComparison ? `vs. ${tile.format(metric.previousValue)} prior` : undefined)
                            }
                            sparklineHeight={50}
                            sparklineClassName="mt-3 -mx-3 -mb-3"
                        />
                    </CardContent>
                )}
            </Card>
        </Link>
    )
}

export function KpiTiles({
    kpis,
    intentClusterCount,
    kpisLoading,
    theme,
}: {
    kpis: KPIData
    intentClusterCount: KPIMetric
    kpisLoading: boolean
    theme: ChartTheme
}): JSX.Element {
    const tiles: TileSpec[] = [
        {
            label: 'Sessions',
            metric: kpis.sessions,
            href: urls.mcpAnalyticsSessions(),
            format: formatNumber,
            color: theme.colors[0],
            loading: kpisLoading,
        },
        {
            label: 'Tool calls',
            metric: kpis.toolCalls,
            href: urls.mcpAnalyticsToolQuality(),
            format: formatNumber,
            color: theme.colors[0],
            loading: kpisLoading,
        },
        {
            label: 'Error rate',
            metric: kpis.errorRatePct,
            href: urls.mcpAnalyticsSessions(),
            format: (n) => formatPercentage(n, { compact: true }),
            color: theme.colors[4],
            loading: kpisLoading,
        },
        {
            label: 'p95 latency',
            metric: kpis.p95LatencyMs,
            href: urls.mcpAnalyticsToolQuality(),
            format: formatMs,
            color: theme.colors[0],
            loading: kpisLoading,
        },
        {
            label: 'Intent clusters',
            metric: intentClusterCount,
            href: urls.mcpAnalyticsIntentClustering(),
            format: formatNumber,
            color: theme.colors[6],
            loading: false,
            // Clusters come from the latest clustering snapshot across all sessions, so
            // unlike the other tiles this count isn't scoped by the date or test-account
            // filters. Label it so the grid doesn't read as a single consistent scope.
            subtitle: 'Latest run · all sessions',
        },
    ]

    return (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(175px,1fr))] gap-3">
            {tiles.map((tile) => (
                <KPITile key={tile.label} tile={tile} theme={theme} />
            ))}
        </div>
    )
}
