import { useCallback, useMemo } from 'react'

import {
    BarChart,
    type BarChartConfig,
    type ChartTheme,
    type PointClickData,
    type Series,
    type TooltipContext,
    type ValueDomain,
    ValueLabels,
} from '@posthog/quill-charts'

import { useChartConfig } from 'lib/charts/hooks'

import { type ToolRow } from '../mcpDashboardOverviewLogic'
import { Card, CardState } from './Card'
import { ChartSkeleton } from './ChartSkeleton'
import { ChartTooltip } from './ChartTooltip'

const MAX_TOOLS = 8
const ROW_HEIGHT_PX = 40
const CHART_MARGINS = { top: 4, right: 20, bottom: 22 }

export interface RankedToolBarChartProps {
    rows: ToolRow[]
    loading: boolean
    failed?: boolean
    onRetry?: () => void
    theme: ChartTheme
    onToolClick?: (tool: string) => void
    title: string
    action?: React.ReactNode
    emptyMessage?: string
}

export interface RankedToolMetric {
    label: string
    color: string
    value: (row: ToolRow) => number
    formatValue: (value: number) => string
    /** Value axis range for the highest value. Leave room past it for the top bar's value label. */
    valueDomain: (maxValue: number) => ValueDomain
    tooltipRows: (row: ToolRow) => [string, string][]
}

// The metric's functions go into memo dependencies, so define them at module level to keep the
// chart from rebuilding on every render.
export function RankedToolBarChart({
    rows,
    loading,
    failed,
    onRetry,
    theme,
    onToolClick,
    title,
    action,
    emptyMessage = 'No tool calls in this date range. Try a wider range.',
    metric,
}: RankedToolBarChartProps & { metric: RankedToolMetric }): JSX.Element {
    const { label, color, value, formatValue, valueDomain, tooltipRows } = metric
    const sorted = useMemo(() => [...rows].sort((a, b) => value(b) - value(a)).slice(0, MAX_TOOLS), [rows, value])
    const labels = useMemo(() => sorted.map((r) => r.tool), [sorted])
    const series = useMemo<Series[]>(
        () => [{ key: 'value', label, color, data: sorted.map(value) }],
        [sorted, label, color, value]
    )
    const config = useChartConfig<BarChartConfig>(
        () => ({
            axisOrientation: 'horizontal',
            barLayout: 'grouped',
            showAxisLines: true,
            showTickMarks: true,
            showCrosshair: true,
            showGrid: true,
            yTickFormatter: formatValue,
            tooltip: { placement: 'cursor' },
            margins: CHART_MARGINS,
            barCornerRadius: 4,
            // The wrapper height already gives each row ROW_HEIGHT_PX, and the chart's own row minimum
            // would make a chart with few rows taller than that wrapper.
            bars: { minBandSize: 0, valueDomain: valueDomain(sorted[0] ? value(sorted[0]) : 0) },
        }),
        [sorted, value, formatValue, valueDomain]
    )
    const byTool = useMemo(() => new Map(sorted.map((r) => [r.tool, r])), [sorted])
    const renderTooltip = useCallback(
        (ctx: TooltipContext): JSX.Element | null => {
            const row = byTool.get(ctx.label)
            return row ? <ChartTooltip title={row.tool} rows={tooltipRows(row)} /> : null
        },
        [byTool, tooltipRows]
    )
    const handlePointClick = useCallback((data: PointClickData) => onToolClick?.(data.label), [onToolClick])

    return (
        <Card title={title} action={action}>
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
                        <ValueLabels valueFormatter={formatValue} offset={6} />
                    </BarChart>
                </div>
            </CardState>
        </Card>
    )
}
