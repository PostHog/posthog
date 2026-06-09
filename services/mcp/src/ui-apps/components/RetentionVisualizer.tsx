import { type ReactElement, useMemo, useState } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'
import { TimeSeriesBarChart, TimeSeriesLineChart, type TooltipConfig } from '@posthog/quill-charts'

import { buildRetentionChartModel } from 'products/product_analytics/frontend/insights/retention/shared/retentionChartTransforms'

import { Select } from './charts'
import { CHART_COLORS, CHART_THEME, colorAt } from './charts/theme'
import type { RetentionVisualizerProps } from './types'

type ChartMode = 'line' | 'bar'

const CHART_MODE_OPTIONS = [
    { value: 'line' as const, label: 'Line' },
    { value: 'bar' as const, label: 'Bar' },
]

const TOOLTIP_CONFIG: TooltipConfig = { pinnable: true, placement: 'top' }

// Cap at the size of the shared chart palette so each cohort gets its own distinct color rather
// than cycling — beyond this the lines blur into noise anyway.
const MAX_COHORTS = CHART_COLORS.length

export function RetentionVisualizer({ query, results }: RetentionVisualizerProps): ReactElement {
    const [chartMode, setChartMode] = useState<ChartMode>('line')

    const { series, labels, lineConfig, barConfig, totalCohorts } = useMemo(
        () =>
            buildRetentionChartModel(results ?? [], {
                aggregationType: query?.retentionFilter?.aggregationType ?? 'count',
                reference: query?.retentionFilter?.retentionReference ?? 'total',
                period: query?.retentionFilter?.period ?? 'Day',
                showTrendLines: query?.retentionFilter?.showTrendLines ?? false,
                getColor: colorAt,
                tooltip: TOOLTIP_CONFIG,
                maxCohorts: MAX_COHORTS,
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

    const truncationNotice =
        totalCohorts > MAX_COHORTS ? `Showing first ${MAX_COHORTS} of ${totalCohorts} cohorts (oldest first)` : null

    return (
        <div>
            <div className="mb-2 flex items-center justify-between">
                <span className="text-xs text-muted-foreground">{truncationNotice}</span>
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
