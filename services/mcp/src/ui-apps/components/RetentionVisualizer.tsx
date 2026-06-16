import { type ReactElement, useMemo, useState } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'
import { TimeSeriesBarChart, TimeSeriesLineChart, type TooltipConfig } from '@posthog/quill-charts'

import { buildRetentionChartModel } from 'products/product_analytics/frontend/insights/retention/shared/retentionChartTransforms'

import { Select } from './charts'
import { CHART_THEME, colorAt } from './charts/theme'
import type { RetentionVisualizerProps } from './types'

type ChartMode = 'line' | 'bar'

const CHART_MODE_OPTIONS = [
    { value: 'line' as const, label: 'Line' },
    { value: 'bar' as const, label: 'Bar' },
]

const TOOLTIP_CONFIG: TooltipConfig = { pinnable: true, placement: 'top' }

export function RetentionVisualizer({ query, results }: RetentionVisualizerProps): ReactElement {
    const [chartMode, setChartMode] = useState<ChartMode>('line')

    // No cohort cap — mirrors the web, which renders every cohort and lets colors wrap past the palette.
    const { series, labels, lineConfig, barConfig } = useMemo(
        () =>
            buildRetentionChartModel(results ?? [], {
                aggregationType: query?.retentionFilter?.aggregationType ?? 'count',
                reference: query?.retentionFilter?.retentionReference ?? 'total',
                period: query?.retentionFilter?.period ?? 'Day',
                showTrendLines: query?.retentionFilter?.showTrendLines ?? false,
                getColor: colorAt,
                tooltip: TOOLTIP_CONFIG,
            }),
        [
            results,
            query?.retentionFilter?.aggregationType,
            query?.retentionFilter?.retentionReference,
            query?.retentionFilter?.period,
            query?.retentionFilter?.showTrendLines,
        ]
    )

    if (!results || results.length === 0 || series.length === 0 || labels.length === 0) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyMedia>{emptyStateIllustration('chart')}</EmptyMedia>
                    <EmptyDescription>No retention data available</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    return (
        <div>
            <div className="mb-2 flex items-center justify-end">
                {/* eslint-disable-next-line react/forbid-elements */}
                <Select value={chartMode} onChange={setChartMode} options={CHART_MODE_OPTIONS} />
            </div>
            <div className="flex flex-col w-full h-[400px]">
                {chartMode === 'bar' ? (
                    <TimeSeriesBarChart series={series} labels={labels} theme={CHART_THEME} config={barConfig} />
                ) : (
                    <TimeSeriesLineChart series={series} labels={labels} theme={CHART_THEME} config={lineConfig} />
                )}
            </div>
        </div>
    )
}
