import { useMemo } from 'react'

import {
    BarChart,
    type BarChartConfig,
    type ChartTheme,
    type Series,
    type TooltipContext,
    useChartLayout,
} from '@posthog/quill-charts'

import { useChartConfig } from 'lib/charts/hooks'
import { formatPercentage } from 'lib/utils/numbers'

import { type ModelRow } from '../mcpDashboardOverviewLogic'
import { Card } from './Card'
import { ChartTooltip } from './ChartTooltip'
import { formatNumber } from './formatters'
import { modelColor } from './modelColors'

function ModelBarLabels({ rows, totalCalls }: { rows: ModelRow[]; totalCalls: number }): JSX.Element {
    const { scales } = useChartLayout()
    return (
        <>
            {rows.map((row) => (
                <div
                    key={row.model}
                    className="absolute left-0 right-0 flex items-center justify-between gap-2 text-xs"
                    style={{ top: (scales.x(row.model) ?? 0) - 26 }}
                >
                    <span className="truncate" title={row.model}>
                        {row.model}
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

function renderTooltip(ctx: TooltipContext<ModelRow & { share: number }>): JSX.Element | null {
    const entry = ctx.seriesData[0]
    const row = entry?.series.meta
    if (!row) {
        return null
    }
    return (
        <ChartTooltip
            title={row.model}
            rows={[
                ['Calls', formatNumber(row.total_calls)],
                ['Share', formatPercentage(row.share, { compact: true })],
            ]}
        />
    )
}

export function ModelBarChart({ rows, theme }: { rows: ModelRow[]; theme: ChartTheme }): JSX.Element {
    const totalCalls = rows.reduce((total, row) => total + row.total_calls, 0)
    const sortedRows = useMemo(() => [...rows].sort((a, b) => b.total_calls - a.total_calls), [rows])
    const labels = useMemo(() => sortedRows.map((row) => row.model), [sortedRows])
    const series = useMemo<Series<ModelRow & { share: number }>[]>(
        () => [
            {
                key: 'calls',
                label: 'Calls',
                data: sortedRows.map((row) => row.total_calls),
                bars: sortedRows.map((row) => ({
                    label: row.model,
                    color: modelColor(theme, row.model),
                    meta: { ...row, share: totalCalls > 0 ? (row.total_calls / totalCalls) * 100 : 0 },
                })),
            },
        ],
        [sortedRows, theme, totalCalls]
    )
    const identifiedCalls = totalCalls - (rows.find((row) => row.model === 'Unknown')?.total_calls ?? 0)
    const identifiedShare = totalCalls > 0 ? (identifiedCalls / totalCalls) * 100 : 0
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
            bars: { bandPadding: 0.65, maxBandRange: rows.length * 40 },
        }),
        [rows.length]
    )

    return (
        <Card className="flex flex-1 flex-col" title="Share of calls by model">
            <div className="text-xs text-secondary" translate="no">
                {formatPercentage(identifiedShare, { compact: true })} identified
            </div>
            <div className="flex h-80 flex-col" translate="no">
                <BarChart series={series} labels={labels} theme={theme} config={config} tooltip={renderTooltip}>
                    <ModelBarLabels rows={sortedRows} totalCalls={totalCalls} />
                </BarChart>
            </div>
        </Card>
    )
}
