import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { isHogQLQuery } from '~/queries/utils'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { useSortableColumns } from './hooks/useSortableColumns'
import { llmAnalyticsSharedLogic } from './llmAnalyticsSharedLogic'
import { llmAnalyticsToolsLogic } from './tabs/llmAnalyticsToolsLogic'

export function LLMAnalyticsTools(): JSX.Element {
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters } = useActions(llmAnalyticsSharedLogic)
    const { setToolsSort } = useActions(llmAnalyticsToolsLogic)
    const { toolsQuery, toolsSort } = useValues(llmAnalyticsToolsLogic)
    const { searchParams } = useValues(router)

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
                setDates(dateRange.date_from || null, dateRange.date_to || null)
                setShouldFilterTestAccounts(filters.filterTestAccounts || false)
                setPropertyFilters(filters.properties || [])
            }}
            context={{
                columns: {
                    tool: {
                        render: function RenderTool(x) {
                            const toolValue = x.value
                            if (!toolValue || toolValue === 'null' || toolValue === '') {
                                return <span className="text-muted">Unknown tool</span>
                            }

                            const toolString = String(toolValue)

                            return (
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
                                                        value: `(^|,)${toolString}(,|$)`,
                                                    },
                                                ],
                                            }).url
                                        }
                                        className="font-mono text-sm"
                                        data-attr="llm-tools-row-click"
                                    >
                                        {toolString}
                                    </Link>
                                </Tooltip>
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
                    solo_pct: {
                        renderTitle: () => (
                            <Tooltip title="Percentage of calls where this was the only tool called">
                                {renderSortableColumnTitle('solo_pct', 'Solo %')}
                            </Tooltip>
                        ),
                        render: function RenderSoloPct(x) {
                            return <span>{x.value}%</span>
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
