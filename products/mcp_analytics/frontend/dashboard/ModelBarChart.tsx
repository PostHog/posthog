import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconChevronDown } from '@posthog/icons'
import {
    BarChart,
    type BarChartConfig,
    type ChartTheme,
    type Series,
    type TooltipContext,
    useChartLayout,
} from '@posthog/quill-charts'

import { useChartConfig } from 'lib/charts/hooks'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { formatPercentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { HogQLFilters } from '~/queries/schema/schema-general'

import { type ModelRow } from '../mcpDashboardOverviewLogic'
import { ChartTooltip } from './ChartTooltip'
import { formatNumber } from './formatters'
import { buildModelExplorationQuery, summarizeModelBreakdown } from './modelBreakdown'
import { modelBreakdownLogic } from './modelBreakdownLogic'
import { ModelBreakdownTable } from './ModelBreakdownTable'
import { modelColor } from './modelColors'

function modelLabel(model: string): string {
    return model === 'Other' ? 'Other models' : model
}

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
                    <span className="truncate" title={modelLabel(row.model)}>
                        {modelLabel(row.model)}
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
            title={modelLabel(row.model)}
            rows={[
                ['Calls', formatNumber(row.total_calls)],
                ['Share of all calls', formatPercentage(row.share, { compact: true })],
            ]}
        />
    )
}

export function ModelBarChart({
    rows,
    theme,
    filters = {},
}: {
    rows: ModelRow[]
    theme: ChartTheme
    filters?: HogQLFilters
}): JSX.Element {
    const logic = modelBreakdownLogic({ filters })
    const { expanded, modelPageLoading } = useValues(logic)
    const { setExpanded } = useActions(logic)
    const {
        totalCalls,
        unknownCalls,
        identifiedShare,
        rankedModels: sortedRows,
    } = useMemo(() => summarizeModelBreakdown(rows), [rows])
    const labels = useMemo(() => sortedRows.map((row) => row.model), [sortedRows])
    const series = useMemo<Series<ModelRow & { share: number }>[]>(
        () => [
            {
                key: 'calls',
                label: 'Calls',
                data: sortedRows.map((row) => row.total_calls),
                bars: sortedRows.map((row) => ({
                    label: modelLabel(row.model),
                    color: modelColor(theme, row.model),
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
            bars: { bandPadding: 0.65, maxBandRange: sortedRows.length * 40 },
        }),
        [sortedRows.length]
    )

    return (
        <LemonCard className="flex min-w-0 flex-1 flex-col p-0 overflow-hidden" hoverEffect={false}>
            <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
                <h3 className="mb-0 text-sm font-semibold">Share of calls by model</h3>
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    to={urls.insightNew({ query: buildModelExplorationQuery(filters) })}
                >
                    Explore models
                </LemonButton>
            </div>
            <div className="flex flex-col gap-4 p-4">
                <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap justify-between gap-1 text-xs">
                        <span className="font-medium">Model coverage</span>
                        <span className="text-secondary tabular-nums">{formatNumber(totalCalls)} calls</span>
                    </div>
                    <LemonProgress
                        percent={identifiedShare}
                        smoothing={false}
                        bgColor="var(--color-border-primary)"
                        role="progressbar"
                        aria-label="Model identification coverage"
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={identifiedShare}
                    />
                    <div className="flex flex-wrap justify-between gap-x-3 gap-y-1 text-xs tabular-nums">
                        <span>{formatPercentage(identifiedShare, { compact: true })} identified</span>
                        <span className="text-secondary">
                            {formatNumber(unknownCalls)} unknown
                            {totalCalls > 0
                                ? ` (${formatPercentage((unknownCalls / totalCalls) * 100, { compact: true })})`
                                : ''}
                        </span>
                    </div>
                </div>
                {sortedRows.length > 0 ? (
                    <div>
                        <div className="mb-2 text-xs text-secondary">Reported models · % of all calls</div>
                        <div className="flex flex-col" style={{ height: sortedRows.length * 40 + 20 }} translate="no">
                            <BarChart
                                series={series}
                                labels={labels}
                                theme={theme}
                                config={config}
                                tooltip={renderTooltip}
                            >
                                <ModelBarLabels rows={sortedRows} totalCalls={totalCalls} />
                            </BarChart>
                        </div>
                    </div>
                ) : (
                    <p className="mb-0 text-xs text-secondary">
                        {totalCalls > 0
                            ? 'No model identifiers were captured for these calls.'
                            : 'No calls in this period.'}
                    </p>
                )}
                <p className="mb-0 text-xs text-secondary">
                    {sortedRows.some((row) => row.model === 'Other')
                        ? 'Other models includes identified models outside the top six. '
                        : ''}
                    Unknown means no model identifier was captured. Model names are reported by clients or agents.
                </p>
                {expanded || sortedRows.some((row) => row.model === 'Other') ? (
                    <LemonButton
                        type="tertiary"
                        size="small"
                        fullWidth
                        center
                        icon={<IconChevronDown className={expanded ? 'rotate-180' : undefined} />}
                        loading={modelPageLoading}
                        aria-expanded={expanded}
                        onClick={() => setExpanded(!expanded)}
                    >
                        {expanded ? 'Show fewer models' : 'Show all models'}
                    </LemonButton>
                ) : null}
                {expanded ? <ModelBreakdownTable filters={filters} totalCalls={totalCalls} /> : null}
            </div>
        </LemonCard>
    )
}
