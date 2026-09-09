import { useCallback, useMemo } from 'react'

import { type ChartTheme, PieChart, type PieChartConfig, type Series, type TooltipContext } from '@posthog/quill-charts'

import { formatPercentage } from 'lib/utils/numbers'

import { type ModelRow } from '../mcpDashboardOverviewLogic'
import { Card } from './Card'
import { ChartTooltip } from './ChartTooltip'
import { formatNumber } from './formatters'

const MODEL_DONUT_CONFIG: PieChartConfig = {
    innerRadiusRatio: 0.6,
    showLabelOnSlice: false,
    showValueOnSlice: false,
    legend: { show: true, position: 'bottom' },
}

export function ModelDonut({ rows, theme }: { rows: ModelRow[]; theme: ChartTheme }): JSX.Element {
    const totalCalls = rows.reduce((total, row) => total + row.total_calls, 0)
    const identifiedCalls = rows.reduce((total, row) => total + (row.model === 'Unknown' ? 0 : row.total_calls), 0)
    const series = useMemo<Series<ModelRow>[]>(
        () =>
            rows.map((row) => ({
                key: row.model,
                label: row.model,
                data: [row.total_calls],
                meta: row,
            })),
        [rows]
    )
    const renderTooltip = useCallback((ctx: TooltipContext<ModelRow>): JSX.Element | null => {
        const entry = ctx.seriesData[0]
        const row = entry?.series.meta
        if (!row) {
            return null
        }
        const share = entry.fraction !== undefined ? entry.fraction * 100 : 0
        const captureRows: [string, string][] = []
        if (row.client_metadata_calls > 0) {
            captureRows.push(['Client metadata', formatNumber(row.client_metadata_calls)])
        }
        if (row.self_reported_calls > 0) {
            captureRows.push(['Self-reported', formatNumber(row.self_reported_calls)])
        }
        return (
            <ChartTooltip
                title={row.model}
                rows={[
                    ['Calls', formatNumber(row.total_calls)],
                    ['Share', formatPercentage(share, { compact: true })],
                    ...captureRows,
                ]}
            />
        )
    }, [])

    const identifiedShare = totalCalls > 0 ? (identifiedCalls / totalCalls) * 100 : 0

    return (
        <Card className="flex flex-1 flex-col" title="Share of calls by model">
            <div className="flex min-h-80 flex-1 flex-col" translate="no">
                <PieChart<ModelRow>
                    series={series}
                    theme={theme}
                    config={MODEL_DONUT_CONFIG}
                    tooltip={renderTooltip}
                    centerLabel={
                        <div className="text-center">
                            <div className="text-3xl font-semibold text-primary">
                                {formatPercentage(identifiedShare, { compact: true })}
                            </div>
                            <div className="text-xs text-secondary">identified</div>
                        </div>
                    }
                />
            </div>
        </Card>
    )
}
