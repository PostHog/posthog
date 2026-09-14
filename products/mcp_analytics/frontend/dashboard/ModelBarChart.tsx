import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconGraph } from '@posthog/icons'
import { BarChart, type ChartTheme, type Series, type TooltipContext, useChartLayout } from '@posthog/quill-charts'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
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
import { useShareBarChartConfig } from './useShareBarChartConfig'

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
    const { totalCalls, unknownCalls, rankedModels: sortedRows } = useMemo(() => summarizeModelBreakdown(rows), [rows])
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
    const config = useShareBarChartConfig(sortedRows.length, totalCalls)

    return (
        <LemonCard
            className="flex min-w-0 flex-1 flex-col overflow-hidden bg-surface-secondary p-0"
            hoverEffect={false}
        >
            <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
                <h3 className="mb-0 text-sm font-medium">Share of calls by model</h3>
                <div className="flex items-center gap-1">
                    {expanded || sortedRows.some((row) => row.model === 'Other') ? (
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            loading={modelPageLoading}
                            data-attr="mcp-dashboard-show-all-models"
                            onClick={() => setExpanded(true)}
                        >
                            Show all models
                        </LemonButton>
                    ) : null}
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        icon={<IconGraph />}
                        tooltip="Explore models"
                        aria-label="Explore models"
                        to={urls.insightNew({ query: buildModelExplorationQuery(filters) })}
                    />
                </div>
            </div>
            <div className="flex flex-col gap-3 p-3">
                <div>
                    <div
                        className="flex flex-wrap justify-between gap-2 text-xs text-secondary tabular-nums"
                        translate="no"
                    >
                        <span>
                            {formatNumber(totalCalls)} {totalCalls === 1 ? 'call' : 'calls'}
                        </span>
                        <Tooltip
                            title={
                                <>
                                    {formatNumber(unknownCalls)} calls have no model identifier. Model names are
                                    reported by clients or agents.
                                    {sortedRows.some((row) => row.model === 'Other')
                                        ? ' Other models includes identified models outside the top six.'
                                        : ''}
                                </>
                            }
                        >
                            <span tabIndex={0} className="cursor-help decoration-dotted underline underline-offset-2">
                                {formatPercentage(totalCalls > 0 ? (unknownCalls / totalCalls) * 100 : 0, {
                                    compact: true,
                                })}{' '}
                                unknown
                            </span>
                        </Tooltip>
                    </div>
                    {sortedRows.length > 0 ? (
                        <div
                            className="h-80 overflow-y-auto"
                            translate="no"
                            tabIndex={0}
                            role="region"
                            aria-label="Calls by model"
                        >
                            <div className="flex min-h-80 flex-col" style={{ height: sortedRows.length * 40 + 20 }}>
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
                </div>
                <LemonModal title="All models" isOpen={expanded} onClose={() => setExpanded(false)} width={640}>
                    <ModelBreakdownTable filters={filters} totalCalls={totalCalls} />
                </LemonModal>
            </div>
        </LemonCard>
    )
}
