import { useCallback, useMemo } from 'react'

import {
    BarChart,
    type BarChartConfig,
    type ChartTheme,
    type PointClickData,
    type Series,
    type TooltipContext,
    ValueLabels,
} from '@posthog/quill-charts'

import { useChartConfig } from 'lib/charts/hooks'
import { formatPercentage } from 'lib/utils/numbers'

import { type ToolRow } from '../mcpDashboardOverviewLogic'
import { Card, CardState } from './Card'
import { ChartSkeleton } from './ChartSkeleton'
import { ChartTooltip } from './ChartTooltip'

const MAX_TOOLS = 8
const ROW_HEIGHT_PX = 40
const CHART_MARGINS = { top: 4, right: 20, bottom: 22 }

// Upper bound for the error-rate track: a bit above the worst tool's rate, rounded up to a clean 10 —
// so the track ends just past the data (a 30% max gives a 50% track) rather than an empty-looking 100%.
function niceErrorAxisMax(maxRate: number): number {
    return Math.min(100, Math.max(10, Math.ceil((maxRate * 1.4) / 10) * 10))
}

export function ToolErrorRateChart({
    rows,
    loading,
    failed,
    onRetry,
    theme,
    onToolClick,
    title = 'Tools with the highest error rate',
    emptyMessage = 'No tool calls in this date range. Try a wider range.',
}: {
    rows: ToolRow[]
    loading: boolean
    failed?: boolean
    onRetry?: () => void
    theme: ChartTheme
    onToolClick?: (tool: string) => void
    title?: string
    emptyMessage?: string
}): JSX.Element {
    const sorted = useMemo(
        () => [...rows].sort((a, b) => b.error_rate_pct - a.error_rate_pct).slice(0, MAX_TOOLS),
        [rows]
    )
    const labels = useMemo(() => sorted.map((r) => r.tool), [sorted])
    const series = useMemo<Series[]>(
        () => [
            {
                key: 'errorRate',
                label: 'Error rate',
                color: theme.colors[4],
                data: sorted.map((r) => r.error_rate_pct),
            },
        ],
        [sorted, theme]
    )
    const config = useChartConfig<BarChartConfig>(() => {
        const axisMax = niceErrorAxisMax(sorted[0]?.error_rate_pct ?? 0)
        return {
            axisOrientation: 'horizontal',
            barLayout: 'grouped',
            showAxisLines: true,
            showTickMarks: true,
            showCrosshair: true,
            showGrid: true,
            yTickFormatter: (value: number) => formatPercentage(value, { compact: true }),
            tooltip: { placement: 'cursor' },
            margins: CHART_MARGINS,
            barCornerRadius: 4,
            // The wrapper height already gives each row ROW_HEIGHT_PX, and the chart's own row minimum
            // would make a chart with few rows taller than that wrapper.
            bars: { minBandSize: 0, valueDomain: { min: 0, max: axisMax } },
        }
    }, [sorted])
    const byTool = useMemo(() => new Map(sorted.map((r) => [r.tool, r])), [sorted])
    const renderTooltip = useCallback(
        (ctx: TooltipContext): JSX.Element | null => {
            const row = byTool.get(ctx.label)
            if (!row) {
                return null
            }
            return (
                <ChartTooltip
                    title={row.tool}
                    rows={[
                        ['Error rate', formatPercentage(row.error_rate_pct, { compact: true })],
                        ['Errors', String(row.errors)],
                        ['Calls', String(row.total_calls)],
                    ]}
                />
            )
        },
        [byTool]
    )
    const handlePointClick = useCallback((data: PointClickData) => onToolClick?.(data.label), [onToolClick])

    return (
        <Card title={title}>
            <CardState
                loading={loading}
                isEmpty={rows.length === 0}
                failed={failed}
                onRetry={onRetry}
                className="min-h-80"
                skeleton={<ChartSkeleton kind="bars" />}
                empty={
                    <div className="flex flex-1 items-center justify-center py-6 text-center text-[12px] text-secondary">
                        {emptyMessage}
                    </div>
                }
            >
                {/* The height follows the row count, not the card. The card stretches to the height of the card
                    next to it, so a chart that fills the card draws thicker bars beside a taller neighbor. */}
                <div
                    className="flex flex-col"
                    style={{ height: sorted.length * ROW_HEIGHT_PX + CHART_MARGINS.top + CHART_MARGINS.bottom }}
                >
                    <BarChart
                        series={series}
                        labels={labels}
                        config={config}
                        theme={theme}
                        tooltip={renderTooltip}
                        onPointClick={onToolClick ? handlePointClick : undefined}
                    >
                        <ValueLabels
                            valueFormatter={(value) => formatPercentage(value, { compact: true })}
                            offset={6}
                        />
                    </BarChart>
                </div>
            </CardState>
        </Card>
    )
}
