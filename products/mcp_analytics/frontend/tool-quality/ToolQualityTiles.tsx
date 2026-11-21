import { useValues } from 'kea'

import { useChartTheme } from 'lib/charts/hooks'
import { formatPercentage } from 'lib/utils/numbers'

import { formatMs, formatNumber } from '../dashboard/formatters'
import { MetricTile } from '../dashboard/MetricTile'
import { mcpAnalyticsToolQualityLogic } from '../mcpAnalyticsToolQualityLogic'
import { deltaPct } from '../mcpDashboardOverviewLogic'

export function ToolQualityTiles(): JSX.Element {
    const {
        dailyChartData,
        dailyTotals: totals,
        dailyStatsLoading,
        interval,
        incompleteTail,
    } = useValues(mcpAnalyticsToolQualityLogic)
    const theme = useChartTheme()

    const errorRate = totals && totals.calls > 0 ? (totals.errors / totals.calls) * 100 : 0
    const dashedFromIndex =
        incompleteTail && dailyChartData.labels.length >= 2 ? dailyChartData.labels.length - 1 : undefined

    const tiles = [
        {
            label: 'Calls',
            value: totals?.calls ?? 0,
            previous: totals?.previous_calls,
            data: dailyChartData.calls,
            format: formatNumber,
            goodDirection: 'up' as const,
            color: theme.colors[0],
            subtitle: 'Total',
        },
        {
            label: 'Errors',
            value: totals?.errors ?? 0,
            previous: totals?.previous_errors,
            data: dailyChartData.errors,
            format: formatNumber,
            goodDirection: 'down' as const,
            color: theme.colors[4],
            subtitle: `${formatPercentage(errorRate, { compact: true })} of calls`,
        },
        {
            label: 'p50 latency',
            value: totals?.p50 ?? 0,
            previous: totals?.previous_p50,
            data: dailyChartData.p50,
            format: formatMs,
            goodDirection: 'down' as const,
            color: theme.colors[0],
            subtitle: 'Overall',
        },
        {
            label: 'p95 latency',
            value: totals?.p95 ?? 0,
            previous: totals?.previous_p95,
            data: dailyChartData.p95,
            format: formatMs,
            goodDirection: 'down' as const,
            color: theme.colors[0],
            subtitle: 'Overall',
        },
    ]

    return (
        <div className="@container" data-attr="mcp-tool-quality-tiles">
            <div className="grid grid-cols-2 gap-3 @3xl:grid-cols-4">
                {tiles.map((tile) => {
                    const change = totals && tile.previous != null ? deltaPct(tile.value, tile.previous) : null
                    return (
                        <MetricTile
                            key={tile.label}
                            label={tile.label}
                            loading={dailyStatsLoading && !totals}
                            value={tile.value}
                            data={tile.data}
                            labels={dailyChartData.labels}
                            interval={interval}
                            theme={theme}
                            color={tile.color}
                            goodDirection={tile.goodDirection}
                            formatValue={tile.format}
                            change={change !== null ? { value: change } : null}
                            changeTooltip={
                                change !== null && tile.previous != null
                                    ? `vs. ${tile.format(tile.previous)} in the previous period`
                                    : undefined
                            }
                            hoverChangeFromPreviousPoint
                            restingSubtitle={tile.subtitle}
                            sparklineHeight={50}
                            sparklineDashedFromIndex={dashedFromIndex}
                        />
                    )
                })}
            </div>
        </div>
    )
}
