import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconGraph, IconRetentionHeatmap, IconTrends, IconUserPaths } from '@posthog/icons'

import { escapeRegex } from 'lib/actionUtils'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { type InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { isHogQLQuery } from '~/queries/utils'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { useSortableColumns } from './hooks/useSortableColumns'
import { buildApplyUrlStatePayload, llmAnalyticsSharedLogic } from './llmAnalyticsSharedLogic'
import { llmAnalyticsToolsLogic } from './tabs/llmAnalyticsToolsLogic'

export function LLMAnalyticsTools(): JSX.Element {
    const { applyUrlState } = useActions(llmAnalyticsSharedLogic)
    const { dateFilter, propertyFilters: currentPropertyFilters } = useValues(llmAnalyticsSharedLogic)
    const { setToolsSort } = useActions(llmAnalyticsToolsLogic)
    const {
        toolsQuery,
        toolsSort,
        buildToolPathsQuery,
        buildToolSequencesQuery,
        buildToolTrendQuery,
        buildAllToolsTrendQuery,
        buildToolHeatmapQuery,
    } = useValues(llmAnalyticsToolsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { searchParams } = useValues(router)
    const showToolsCharts = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_TOOLS_CHARTS]

    const { renderSortableColumnTitle } = useSortableColumns(toolsSort, setToolsSort)

    return (
        <DataTable
            query={{
                ...toolsQuery,
                showSavedFilters: true,
            }}
            setQuery={(query) => {
                if (!isHogQLQuery(query.source)) {
                    console.warn('LLMAnalyticsTools received a non-HogQL query:', query.source)
                    return
                }
                const { filters = {} } = query.source
                const { dateRange = {} } = filters
                applyUrlState(
                    buildApplyUrlStatePayload({
                        dateFrom: dateRange.date_from || null,
                        dateTo: dateRange.date_to || null,
                        shouldFilterTestAccounts: filters.filterTestAccounts || false,
                        propertyFilters: filters.properties || [],
                        currentDateFilter: dateFilter,
                        currentPropertyFilters,
                    })
                )
            }}
            context={{
                customActions: showToolsCharts
                    ? [
                          <Tooltip title="View tool usage trends over time" key="trends">
                              <LemonButton
                                  icon={<IconTrends />}
                                  size="small"
                                  type="secondary"
                                  to={urls.insightNew({ query: buildAllToolsTrendQuery })}
                                  targetBlank
                                  data-attr="llma-tools-all-trends-click"
                              >
                                  Tool trends
                              </LemonButton>
                          </Tooltip>,
                          <Tooltip title="View tool co-occurrence heatmap" key="heatmap">
                              <LemonButton
                                  icon={<IconRetentionHeatmap />}
                                  size="small"
                                  type="secondary"
                                  to={urls.insightNew({ query: buildToolHeatmapQuery })}
                                  targetBlank
                                  data-attr="llma-tools-heatmap-click"
                              >
                                  Tool co-occurrence
                              </LemonButton>
                          </Tooltip>,
                      ]
                    : undefined,
                columns: {
                    tool: {
                        render: function RenderTool(x) {
                            const toolValue = x.value
                            if (!toolValue || toolValue === 'null' || toolValue === '') {
                                return <span className="text-muted">Unknown tool</span>
                            }

                            const toolString = String(toolValue)

                            return (
                                <div className="flex items-center gap-1">
                                    <Tooltip title={`View generations calling ${toolString}`}>
                                        <Link
                                            to={
                                                combineUrl(urls.llmAnalyticsGenerations(), {
                                                    ...searchParams,
                                                    filters: [
                                                        {
                                                            type: PropertyFilterType.Event,
                                                            key: '$ai_tools_called',
                                                            operator: PropertyOperator.Regex,
                                                            value: `(^|,)${escapeRegex(toolString)}(,|$)`,
                                                        },
                                                    ],
                                                }).url
                                            }
                                            className="font-mono text-sm"
                                            data-attr="llma-tools-row-click"
                                        >
                                            {toolString}
                                        </Link>
                                    </Tooltip>
                                    {showToolsCharts && (
                                        <>
                                            <Tooltip title={`View ${toolString} usage over time`}>
                                                <LemonButton
                                                    icon={<IconTrends />}
                                                    size="xsmall"
                                                    to={urls.insightNew({
                                                        query: {
                                                            kind: NodeKind.InsightVizNode,
                                                            source: buildToolTrendQuery(toolString),
                                                        } as InsightVizNode,
                                                    })}
                                                    targetBlank
                                                    data-attr="llma-tools-trend-click"
                                                />
                                            </Tooltip>
                                            <Tooltip title={`View tool combinations with ${toolString}`}>
                                                <LemonButton
                                                    icon={<IconGraph />}
                                                    size="xsmall"
                                                    to={urls.insightNew({
                                                        query: {
                                                            kind: NodeKind.InsightVizNode,
                                                            source: buildToolSequencesQuery(toolString),
                                                        } as InsightVizNode,
                                                    })}
                                                    targetBlank
                                                    data-attr="llma-tools-sequences-click"
                                                />
                                            </Tooltip>
                                            <Tooltip title={`View tool paths from ${toolString}`}>
                                                <LemonButton
                                                    icon={<IconUserPaths />}
                                                    size="xsmall"
                                                    to={urls.insightNew({
                                                        query: {
                                                            kind: NodeKind.InsightVizNode,
                                                            source: buildToolPathsQuery(toolString),
                                                        } as InsightVizNode,
                                                    })}
                                                    targetBlank
                                                    data-attr="llma-tools-paths-click"
                                                />
                                            </Tooltip>
                                        </>
                                    )}
                                </div>
                            )
                        },
                    },
                    total_calls: {
                        renderTitle: () => (
                            <Tooltip title="Total number of times this tool was called">
                                {renderSortableColumnTitle('total_calls', 'Total calls')}
                            </Tooltip>
                        ),
                    },
                    traces: {
                        renderTitle: () => (
                            <Tooltip title="Number of unique traces where this tool was called">
                                {renderSortableColumnTitle('traces', 'Traces')}
                            </Tooltip>
                        ),
                    },
                    users: {
                        renderTitle: () => (
                            <Tooltip title="Number of unique users who triggered this tool">
                                {renderSortableColumnTitle('users', 'Users')}
                            </Tooltip>
                        ),
                    },
                    sessions: {
                        renderTitle: () => (
                            <Tooltip title="Number of unique sessions where this tool was called">
                                {renderSortableColumnTitle('sessions', 'Sessions')}
                            </Tooltip>
                        ),
                    },
                    single_pct: {
                        renderTitle: () => (
                            <Tooltip title="Percentage of calls where this was the only tool called">
                                {renderSortableColumnTitle('single_pct', 'Single %')}
                            </Tooltip>
                        ),
                        render: function RenderSinglePct(x) {
                            return <span>{String(x.value)}%</span>
                        },
                    },
                    days_seen: {
                        renderTitle: () => (
                            <Tooltip title="Number of distinct days this tool was called">
                                {renderSortableColumnTitle('days_seen', 'Days seen')}
                            </Tooltip>
                        ),
                    },
                    first_seen: {
                        renderTitle: () => renderSortableColumnTitle('first_seen', 'First seen'),
                    },
                    last_seen: {
                        renderTitle: () => renderSortableColumnTitle('last_seen', 'Last seen'),
                    },
                },
            }}
            uniqueKey="llm-analytics-tools"
        />
    )
}
