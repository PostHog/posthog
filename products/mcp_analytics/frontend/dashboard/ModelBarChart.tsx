import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconGraph } from '@posthog/icons'
import { type ChartTheme, type TooltipContext } from '@posthog/quill-charts'

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
import { ShareBarChart, type ShareBarRow } from './ShareBarChart'

function modelLabel(model: string): string {
    return model === 'Other' ? 'Other models' : model
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
    const chartRows = useMemo<ShareBarRow<ModelRow>[]>(
        () =>
            sortedRows.map((row) => ({
                key: row.model,
                label: modelLabel(row.model),
                value: row.total_calls,
                color: modelColor(theme, row.model),
                meta: row,
            })),
        [sortedRows, theme]
    )

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
                        <ShareBarChart
                            rows={chartRows}
                            totalCalls={totalCalls}
                            theme={theme}
                            tooltip={renderTooltip}
                            label="Calls by model"
                        />
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
