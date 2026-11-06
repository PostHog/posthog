import { useCallback, useMemo } from 'react'

import {
    BarChart,
    type BarChartConfig,
    type ChartTheme,
    type PointClickData,
    type Series,
    type TooltipContext,
    ValueLabels,
    measureLabelWidth,
} from '@posthog/quill-charts'
import { Skeleton } from '@posthog/quill-primitives'

import { useChartConfig } from 'lib/charts/hooks'
import { formatPercentage } from 'lib/utils/numbers'

import { type ToolRow } from '../mcpDashboardOverviewLogic'
import { Card, CardState } from './Card'
import { ChartTooltip } from './ChartTooltip'

const MAX_TOOLS = 8
const ROW_HEIGHT_PX = 40
const MAX_LABEL_WIDTH_PX = 180
// The gap that quill-charts keeps between a row label and the plot.
const LABEL_GAP_PX = 18
const CHART_MARGINS = { top: 4, right: 20, bottom: 22 }

function topByErrorRate(rows: ToolRow[]): ToolRow[] {
    return [...rows].sort((a, b) => b.error_rate_pct - a.error_rate_pct).slice(0, MAX_TOOLS)
}

// The left gutter fits the widest label that any of the given charts shows, so charts that pass each
// other's rows start their bars at the same x. A label wider than the cap gets an ellipsis.
function labelGutterPx(rowSets: ToolRow[][]): number {
    const widths = rowSets.flatMap((rows) => topByErrorRate(rows).map((row) => measureLabelWidth(row.tool)))
    return Math.ceil(Math.min(Math.max(0, ...widths), MAX_LABEL_WIDTH_PX)) + LABEL_GAP_PX
}

// Upper bound for the error-rate track: a bit above the worst tool's rate, rounded up to a clean 10 —
// so the track ends just past the data (a 30% max gives a 50% track) rather than an empty-looking 100%.
function niceErrorAxisMax(maxRate: number): number {
    return Math.min(100, Math.max(10, Math.ceil((maxRate * 1.4) / 10) * 10))
}

export function ToolErrorRateChart({
    rows,
    alignWithRows,
    loading,
    theme,
    onToolClick,
    title = 'Tools with the highest error rate',
    emptyMessage = 'No tool calls yet.',
}: {
    rows: ToolRow[]
    /** Rows of a sibling error rate chart. Both charts then reserve the same label gutter, so their bars line up. */
    alignWithRows?: ToolRow[]
    loading: boolean
    theme: ChartTheme
    onToolClick?: (tool: string) => void
    title?: string
    emptyMessage?: string
}): JSX.Element {
    const sorted = useMemo(() => topByErrorRate(rows), [rows])
    const labelGutter = useMemo(() => labelGutterPx([rows, alignWithRows ?? []]), [rows, alignWithRows])
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
            margins: { ...CHART_MARGINS, left: labelGutter },
            maxCategoryLabelWidth: MAX_LABEL_WIDTH_PX,
            barCornerRadius: 4,
            bars: { minBandSize: 30, valueDomain: { min: 0, max: axisMax } },
        }
    }, [sorted, labelGutter])
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
                skeleton={
                    <div className="space-y-2 py-3">
                        {Array.from({ length: 5 }).map((_, i) => (
                            <Skeleton key={i} className="h-7 w-full" />
                        ))}
                    </div>
                }
                empty={<div className="py-6 text-center text-[12px] text-secondary">{emptyMessage}</div>}
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
