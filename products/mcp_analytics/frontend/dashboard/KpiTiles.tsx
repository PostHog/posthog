import { LemonSkeleton, Link } from '@posthog/lemon-ui'
import { type ChartTheme, MetricCard } from '@posthog/quill-charts'

import { urls } from 'scenes/urls'

import { type KPIData, KPIMetric } from '../mcpDashboardOverviewLogic'
import { formatMs, formatNumber, formatPercent } from './formatters'

interface TileSpec {
    label: string
    metric: KPIMetric
    href: string
    format: (n: number) => string
    color: string
    loading: boolean
}

function KPITile({ tile, theme }: { tile: TileSpec; theme: ChartTheme }): JSX.Element {
    const { metric } = tile
    const hasSparkline = metric.sparkline.length > 0
    const hasComparison = metric.deltaPct !== null

    return (
        <Link
            to={tile.href}
            subtle
            className="flex flex-col rounded-lg border border-primary bg-surface-primary px-3.5 py-3 shadow-sm transition-all hover:border-secondary hover:shadow-md"
        >
            {tile.loading ? (
                <div className="flex flex-col gap-2">
                    <LemonSkeleton className="h-3 w-16" />
                    <LemonSkeleton className="h-7 w-20" />
                </div>
            ) : (
                <MetricCard
                    className="text-primary"
                    title={tile.label}
                    value={metric.value}
                    data={hasSparkline ? metric.sparkline : undefined}
                    theme={theme}
                    color={tile.color}
                    goodDirection={metric.goodDirection}
                    formatValue={tile.format}
                    subtitle={hasComparison ? `vs. ${tile.format(metric.previousValue)} prior` : undefined}
                    sparklineHeight={50}
                    sparklineClassName="mt-3 -mx-3.5 -mb-3"
                />
            )}
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
            color: theme.colors[0], // --data-color-1 (blue)
            loading: kpisLoading,
        },
        {
            label: 'Tool calls',
            metric: kpis.toolCalls,
            href: urls.mcpAnalyticsToolQuality(),
            format: formatNumber,
            color: theme.colors[0], // --data-color-1 (blue)
            loading: kpisLoading,
        },
        {
            label: 'Error rate',
            metric: kpis.errorRatePct,
            href: urls.mcpAnalyticsSessions(),
            format: formatPercent,
            color: theme.colors[4], // --data-color-5 (red)
            loading: kpisLoading,
        },
        {
            label: 'p95 latency',
            metric: kpis.p95LatencyMs,
            href: urls.mcpAnalyticsToolQuality(),
            format: formatMs,
            color: theme.colors[0], // --data-color-1 (blue)
            loading: kpisLoading,
        },
        {
            label: 'Intent clusters',
            metric: intentClusterCount,
            href: urls.mcpAnalyticsIntentClustering(),
            format: formatNumber,
            color: theme.colors[6], // --data-color-7 (green)
            loading: false,
        },
    ]

    return (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            {tiles.map((tile) => (
                <KPITile key={tile.label} tile={tile} theme={theme} />
            ))}
        </div>
    )
}
