import { useMemo } from 'react'

import {
    BarChart,
    type BarChartConfig,
    type ChartTheme,
    type Series,
    type TooltipContext,
    useChartLayout,
} from '@posthog/quill-charts'
import { Skeleton } from '@posthog/quill-primitives'

import { useChartConfig } from 'lib/charts/hooks'
import { formatPercentage } from 'lib/utils/numbers'

import { type HarnessRow } from '../mcpDashboardOverviewLogic'
import { Card, CardState } from './Card'
import { ChartTooltip } from './ChartTooltip'
import { formatNumber } from './formatters'
import { HarnessLogo } from './harness'
import { harnessColor } from './harnessRegistry'

function HarnessBarLabels({ rows, totalCalls }: { rows: HarnessRow[]; totalCalls: number }): JSX.Element {
    const { scales } = useChartLayout()
    return (
        <>
            {rows.map((row) => (
                <div
                    key={row.category}
                    className="absolute left-0 right-0 flex items-center justify-between gap-2 text-xs"
                    style={{ top: (scales.x(row.category) ?? 0) - 26 }}
                >
                    <span className="flex min-w-0 items-center gap-1.5" title={row.category}>
                        <HarnessLogo category={row.category} />
                        <span className="truncate">{row.category}</span>
                    </span>
                    <span className="shrink-0 text-secondary tabular-nums">
                        {formatPercentage(totalCalls > 0 ? (row.total_calls / totalCalls) * 100 : 0, { compact: true })}{' '}
                        · {formatNumber(row.total_calls)} {row.total_calls === 1 ? 'call' : 'calls'}
                    </span>
                </div>
            ))}
        </>
    )
}

function renderTooltip(ctx: TooltipContext<HarnessRow & { share: number }>): JSX.Element | null {
    const entry = ctx.seriesData[0]
    const row = entry?.series.meta
    if (!row) {
        return null
    }
    return (
        <ChartTooltip
            title={row.category}
            rows={[
                ['Calls', formatNumber(row.total_calls)],
                ['Share', formatPercentage(row.share, { compact: true })],
                ['Sessions', formatNumber(row.sessions)],
                ['Error rate', formatPercentage(row.error_rate_pct, { compact: true })],
            ]}
        />
    )
}

export function HarnessBarChart({
    rows,
    loading,
    theme,
}: {
    rows: HarnessRow[]
    loading: boolean
    theme: ChartTheme
}): JSX.Element {
    const totalCalls = rows.reduce((total, row) => total + row.total_calls, 0)
    const sortedRows = useMemo(() => [...rows].sort((a, b) => b.total_calls - a.total_calls), [rows])
    const labels = useMemo(() => sortedRows.map((row) => row.category), [sortedRows])
    const series = useMemo<Series<HarnessRow & { share: number }>[]>(
        () => [
            {
                key: 'calls',
                label: 'Calls',
                data: sortedRows.map((row) => row.total_calls),
                bars: sortedRows.map((row) => ({
                    label: row.category,
                    color: harnessColor(theme, row.category),
                    meta: { ...row, share: totalCalls > 0 ? (row.total_calls / totalCalls) * 100 : 0 },
                })),
            },
        ],
        [sortedRows, theme, totalCalls]
    )
    const config = useChartConfig<BarChartConfig>(
        () => ({
            axisOrientation: 'horizontal',
            hideXAxis: true,
            hideYAxis: true,
            showGrid: false,
            showAxisLines: false,
            showTickMarks: false,
            margins: { left: 0, right: 0, top: 20, bottom: 0 },
            barCornerRadius: 4,
            bars: { bandPadding: 0.65, maxBandRange: rows.length * 40, minBarSize: 6, minBarSizeScope: 'hover' },
        }),
        [rows.length]
    )

    return (
        <Card className="flex flex-1 flex-col" title="Share of calls by harness">
            <CardState
                loading={loading}
                isEmpty={rows.length === 0}
                skeleton={
                    <div className="h-80 space-y-6 py-3">
                        {Array.from({ length: 6 }).map((_, index) => (
                            <Skeleton key={index} className="h-4 w-full" />
                        ))}
                    </div>
                }
                empty={
                    <div className="flex h-80 items-center justify-center text-xs text-secondary">
                        No harness data yet.
                    </div>
                }
            >
                <div className="text-xs text-secondary" translate="no">
                    {formatNumber(totalCalls)} {totalCalls === 1 ? 'call' : 'calls'}
                </div>
                <div
                    className="h-80 overflow-y-auto"
                    translate="no"
                    tabIndex={0}
                    role="region"
                    aria-label="Calls by harness"
                >
                    <div className="flex min-h-80 flex-col" style={{ height: rows.length * 40 + 20 }}>
                        <BarChart series={series} labels={labels} theme={theme} config={config} tooltip={renderTooltip}>
                            <HarnessBarLabels rows={sortedRows} totalCalls={totalCalls} />
                        </BarChart>
                    </div>
                </div>
            </CardState>
        </Card>
    )
}
