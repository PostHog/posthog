import { useCallback, useMemo } from 'react'

import {
    BarChart,
    type BarChartConfig,
    type ChartTheme,
    type Series,
    type TooltipContext,
    ValueLabels,
} from '@posthog/quill-charts'
import { Skeleton } from '@posthog/quill-primitives'

import { useChartConfig } from 'lib/charts/hooks'
import { formatPercentage } from 'lib/utils/numbers'

import { type ToolRow } from '../mcpDashboardOverviewLogic'
import { Card, CardState } from './Card'
import { ChartTooltip } from './ChartTooltip'

const MAX_TOOLS = 8

// Upper bound for the error-rate track: a bit above the worst tool's rate, rounded up to a clean 10 —
// so the track ends just past the data (a 30% max gives a 50% track) rather than an empty-looking 100%.
function niceErrorAxisMax(maxRate: number): number {
    return Math.min(100, Math.max(10, Math.ceil((maxRate * 1.4) / 10) * 10))
}

export function ToolErrorRateChart({
    rows,
    loading,
    theme,
}: {
    rows: ToolRow[]
    loading: boolean
    theme: ChartTheme
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
            yTickFormatter: (value: number) => formatPercentage(value, { compact: true }),
            tooltip: { placement: 'cursor' },
            margins: { top: 4, right: 20, bottom: 22 },
            bars: { cornerRadius: 4, minBandSize: 30, valueDomain: [0, axisMax] },
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

    return (
        <Card title="Tools with the highest error rate">
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
                empty={<div className="py-6 text-center text-[12px] text-secondary">No tool calls yet.</div>}
            >
                <div className="flex flex-1 flex-col">
                    <BarChart series={series} labels={labels} config={config} theme={theme} tooltip={renderTooltip}>
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
