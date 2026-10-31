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

import { isFoldedModelsLabel, seriesLab } from '../aiLabs'
import { labMark } from '../brandMarks'
import { modelColors } from '../colors'
import { BrandMark } from '../components/BrandMark'
import { type ModelRow } from '../mcpDashboardOverviewLogic'
import { ChartTooltip } from './ChartTooltip'
import { formatNumber } from './formatters'
import { buildModelExplorationQuery, summarizeModelBreakdown } from './modelBreakdown'
import { modelBreakdownLogic } from './modelBreakdownLogic'
import { ModelBreakdownTable } from './ModelBreakdownTable'
import { ShareBarChart, type ShareBarRow } from './ShareBarChart'

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
                ['Share of all calls', formatPercentage(row.share, { compact: true })],
            ]}
        />
    )
}

export function ModelBarChart({
    rows,
    theme,
    filters = {},
    colorOf,
    rowLabels,
}: {
    rows: ModelRow[]
    theme: ChartTheme
    filters?: HogQLFilters
    /** Pass the page's model colors when another chart on the page also shows models. */
    colorOf?: (model: string) => string | undefined
    /** Pass the page's model rows when another chart on the page also shows models. */
    rowLabels?: ReadonlyMap<string, string>
}): JSX.Element {
    const logic = modelBreakdownLogic({ filters })
    const { expanded, modelPageLoading } = useValues(logic)
    const { setExpanded } = useActions(logic)
    const {
        totalCalls,
        unknownCalls,
        rankedModels: sortedRows,
    } = useMemo(() => summarizeModelBreakdown(rows, rowLabels), [rows, rowLabels])
    const chartRows = useMemo<ShareBarRow<ModelRow>[]>(() => {
        const ownColors = modelColors(
            theme,
            sortedRows.map((row) => row.model)
        )
        return sortedRows.map((row) => {
            const lab = seriesLab(row.model)
            return {
                key: row.model,
                label: row.model,
                value: row.total_calls,
                color: colorOf ? colorOf(row.model) : ownColors.get(row.model),
                icon: <BrandMark name={labMark(lab)} />,
                meta: row,
            }
        })
    }, [sortedRows, theme, colorOf])

    return (
        <LemonCard
            className="flex min-w-0 flex-1 flex-col overflow-hidden bg-surface-secondary p-0"
            hoverEffect={false}
        >
            <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
                <h3 className="mb-0 text-sm font-bold">Share of calls by model</h3>
                <div className="flex items-center gap-1">
                    {expanded || sortedRows.some((row) => isFoldedModelsLabel(row.model)) ? (
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
                                    {sortedRows.some((row) => isFoldedModelsLabel(row.model))
                                        ? ' Models outside the top 10 are grouped by AI lab.'
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
                        <ShareBarChart rows={chartRows} totalCalls={totalCalls} theme={theme} tooltip={renderTooltip} />
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
