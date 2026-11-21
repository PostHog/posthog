import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { Link } from '@posthog/lemon-ui'
import { type ChartTheme } from '@posthog/quill-charts'

import { formatPercentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { IntervalType } from '~/types'

import { sortSearchParams } from '../mcpAnalyticsToolQualityLogic'
import { type KPIData, KPIMetric } from '../mcpDashboardOverviewLogic'
import { formatMs, formatNumber } from './formatters'
import { MetricTile } from './MetricTile'

interface TileSpec {
    label: string
    dataAttr: string
    metric: KPIMetric
    href: string
    format: (n: number) => string
    color: string
    loading: boolean
    hasValue: boolean
    failed?: boolean
    onRetry?: () => void
    summaryLabel: string
    // A loading metric has no sparkline data yet, so this says whether the placeholder should reserve one.
    trend: boolean
    // Overrides the summary caption — used to flag a tile whose value isn't
    // scoped by the dashboard filters.
    subtitle?: string
}

// A tile that reads two queries reruns only the one that failed, so the other's pending request isn't duplicated.
export function retryFailedSources(sources: { failed?: boolean; retry?: () => void }[]): void {
    for (const { failed, retry } of sources) {
        if (failed) {
            retry?.()
        }
    }
}

export function kpiTileUrls(searchParams: Record<string, any>): {
    sessions: string
    people: string
    toolQuality: string
    toolQualityByErrorRate: string
    intentClustering: string
} {
    const { landing: _landing, search: _search, ...sharedParams } = searchParams
    return {
        sessions: combineUrl(urls.mcpAnalyticsSessions(), sharedParams).url,
        people: combineUrl(urls.mcpAnalyticsPeople(), sharedParams).url,
        toolQuality: combineUrl(urls.mcpAnalyticsToolQuality(), sharedParams).url,
        toolQualityByErrorRate: combineUrl(urls.mcpAnalyticsToolQuality(), {
            ...sharedParams,
            ...sortSearchParams({ column: 'error_rate_pct', direction: 'DESC' }),
        }).url,
        intentClustering: combineUrl(urls.mcpAnalyticsIntentClustering(), sharedParams).url,
    }
}

function KPITile({
    tile,
    theme,
    interval,
    incompleteTail,
}: {
    tile: TileSpec
    theme: ChartTheme
    interval: IntervalType
    incompleteTail: boolean
}): JSX.Element {
    const { metric } = tile
    // Tiles whose metric carries no sparkline (Intent clusters) have no segment to dash.
    const dashedFromIndex = incompleteTail && metric.sparkline.length >= 2 ? metric.sparkline.length - 1 : undefined

    return (
        <Link to={tile.href} subtle className="group/tile flex h-full" data-attr={tile.dataAttr}>
            <MetricTile
                className="transition-transform group-hover/tile:-translate-y-0.5"
                label={tile.label}
                loading={tile.loading}
                hasValue={tile.hasValue}
                failed={tile.failed}
                onRetry={tile.onRetry}
                value={metric.value}
                data={metric.sparkline}
                labels={metric.sparklineLabels}
                interval={interval}
                theme={theme}
                color={tile.color}
                goodDirection={metric.goodDirection}
                formatValue={tile.format}
                change={metric.deltaPct !== null ? { value: metric.deltaPct } : null}
                changeTooltip={
                    metric.deltaPct !== null
                        ? `vs. ${tile.format(metric.previousValue)} in the previous period`
                        : undefined
                }
                hoverChangeFromPreviousPoint
                restingSubtitle={tile.subtitle ?? tile.summaryLabel}
                sparklineHeight={tile.trend ? 50 : undefined}
                sparklineDashedFromIndex={dashedFromIndex}
            />
        </Link>
    )
}

export function KpiTiles({
    kpis,
    intentClusterCount,
    kpisLoading,
    usersLoading,
    kpisLoaded,
    usersLoaded,
    kpisFailed,
    usersFailed,
    onRetryKpis,
    onRetryUsers,
    showIntentClusters,
    theme,
    interval,
    incompleteTail,
    usersAreSessions = false,
}: {
    kpis: KPIData
    intentClusterCount: KPIMetric
    kpisLoading: boolean
    usersLoading: boolean
    kpisLoaded: boolean
    usersLoaded: boolean
    kpisFailed?: boolean
    usersFailed?: boolean
    onRetryKpis?: () => void
    onRetryUsers?: () => void
    showIntentClusters: boolean
    theme: ChartTheme
    interval: IntervalType
    // When true, the sparklines' final point is the current in-progress interval — dash it so a
    // partial period doesn't read as a decline. Required rather than optional: an omitted prop
    // silently renders the partial bucket as settled data.
    incompleteTail: boolean
}): JSX.Element {
    const {
        sessions: sessionsHref,
        people: peopleHref,
        toolQuality: toolQualityHref,
        toolQualityByErrorRate: toolQualityByErrorRateHref,
        intentClustering: intentClusteringHref,
    } = kpiTileUrls(useValues(router).searchParams)

    const tiles: TileSpec[] = [
        {
            label: 'People',
            dataAttr: 'mcp-dashboard-kpi-users',
            metric: kpis.users,
            href: peopleHref,
            format: formatNumber,
            color: theme.colors[0],
            loading: kpisLoading || usersLoading,
            hasValue: kpisLoaded && usersLoaded,
            failed: kpisFailed || usersFailed,
            onRetry: () =>
                retryFailedSources([
                    { failed: kpisFailed, retry: onRetryKpis },
                    { failed: usersFailed, retry: onRetryUsers },
                ]),
            summaryLabel: 'Total',
            subtitle: usersAreSessions ? 'Anonymous sessions, not people' : undefined,
            trend: true,
        },
        {
            label: 'Sessions',
            dataAttr: 'mcp-dashboard-kpi-sessions',
            metric: kpis.sessions,
            href: sessionsHref,
            format: formatNumber,
            color: theme.colors[0],
            loading: kpisLoading,
            hasValue: kpisLoaded,
            failed: kpisFailed,
            onRetry: onRetryKpis,
            summaryLabel: 'Total',
            trend: true,
        },
        {
            label: 'Tool calls',
            dataAttr: 'mcp-dashboard-kpi-tool-calls',
            metric: kpis.toolCalls,
            href: toolQualityHref,
            format: formatNumber,
            color: theme.colors[0],
            loading: kpisLoading,
            hasValue: kpisLoaded,
            failed: kpisFailed,
            onRetry: onRetryKpis,
            summaryLabel: 'Total',
            trend: true,
        },
        {
            label: 'Error rate',
            dataAttr: 'mcp-dashboard-kpi-error-rate',
            metric: kpis.errorRatePct,
            href: toolQualityByErrorRateHref,
            format: (n) => formatPercentage(n, { compact: true }),
            color: theme.colors[4],
            loading: kpisLoading,
            hasValue: kpisLoaded,
            failed: kpisFailed,
            onRetry: onRetryKpis,
            summaryLabel: 'Overall',
            trend: true,
        },
        {
            label: 'p95 latency',
            dataAttr: 'mcp-dashboard-kpi-p95-latency',
            metric: kpis.p95LatencyMs,
            href: toolQualityHref,
            format: formatMs,
            color: theme.colors[0],
            loading: kpisLoading || usersLoading,
            hasValue: kpisLoaded && usersLoaded,
            failed: kpisFailed || usersFailed,
            onRetry: () =>
                retryFailedSources([
                    { failed: kpisFailed, retry: onRetryKpis },
                    { failed: usersFailed, retry: onRetryUsers },
                ]),
            summaryLabel: 'Overall',
            trend: true,
        },
        ...(showIntentClusters
            ? [
                  {
                      label: 'Intent clusters',
                      dataAttr: 'mcp-dashboard-kpi-intent-clusters',
                      metric: intentClusterCount,
                      href: intentClusteringHref,
                      format: formatNumber,
                      color: theme.colors[6],
                      loading: false,
                      hasValue: true,
                      summaryLabel: 'Total',
                      trend: false,
                      // Clusters come from the latest clustering snapshot across all sessions, so
                      // unlike the other tiles this count isn't scoped by the date or test-account
                      // filters. Label it so the grid doesn't read as a single consistent scope.
                      subtitle: 'Latest run · all sessions',
                  },
              ]
            : []),
    ]

    // Keep both flag states balanced: six tiles wrap as 3+3 or 2+2+2, while five stay on one
    // wide row. Container queries key off the card area's width rather than the viewport.
    return (
        <div className="@container">
            <div
                className={`grid gap-3 ${
                    showIntentClusters
                        ? 'grid-cols-2 @xl:grid-cols-3 @6xl:grid-cols-6'
                        : 'grid-cols-2 @xl:grid-cols-3 @5xl:grid-cols-5'
                }`}
            >
                {tiles.map((tile) => (
                    <KPITile
                        key={tile.label}
                        tile={tile}
                        theme={theme}
                        interval={interval}
                        incompleteTail={incompleteTail}
                    />
                ))}
            </div>
        </div>
    )
}
