import { useActions, useValues } from 'kea'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { isHogQLQuery } from '~/queries/utils'

import { useSortableColumns } from './hooks/useSortableColumns'
import { llmAnalyticsColumnRenderers } from './llmAnalyticsColumnRenderers'
import { buildApplyUrlStatePayload, llmAnalyticsSharedLogic } from './llmAnalyticsSharedLogic'
import { llmAnalyticsUsersLogic } from './tabs/llmAnalyticsUsersLogic'

export function LLMAnalyticsUsers(): JSX.Element {
    const { applyUrlState } = useActions(llmAnalyticsSharedLogic)
    const { dateFilter, propertyFilters: currentPropertyFilters } = useValues(llmAnalyticsSharedLogic)
    const { setUsersSort } = useActions(llmAnalyticsUsersLogic)
    const { usersQuery, usersSort } = useValues(llmAnalyticsUsersLogic)

    const { renderSortableColumnTitle } = useSortableColumns(usersSort, setUsersSort)

    return (
        <DataTable
            attachTo={llmAnalyticsSharedLogic}
            query={{
                ...usersQuery,
                showSavedFilters: true,
            }}
            setQuery={(query) => {
                if (!isHogQLQuery(query.source)) {
                    console.warn('LLMAnalyticsUsers received a non-events query:', query.source)
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
                columns: {
                    __llm_person: llmAnalyticsColumnRenderers.__llm_person,
                    first_seen: {
                        renderTitle: () => renderSortableColumnTitle('first_seen', 'First Seen'),
                    },
                    last_seen: {
                        renderTitle: () => renderSortableColumnTitle('last_seen', 'Last Seen'),
                    },
                    traces: {
                        renderTitle: () => (
                            <Tooltip title="Number of traces created by this user">
                                {renderSortableColumnTitle('traces', 'Traces')}
                            </Tooltip>
                        ),
                    },
                    generations: {
                        renderTitle: () => (
                            <Tooltip title="Number of generations created by this user">
                                {renderSortableColumnTitle('generations', 'Generations')}
                            </Tooltip>
                        ),
                    },
                    errors: {
                        renderTitle: () => (
                            <Tooltip title="Number of errors encountered by this user">
                                {renderSortableColumnTitle('errors', 'Errors')}
                            </Tooltip>
                        ),
                    },
                    total_cost: {
                        renderTitle: () => (
                            <Tooltip title="Total cost of all generations for this user">
                                {renderSortableColumnTitle('total_cost', 'Cost')}
                            </Tooltip>
                        ),
                        render: function RenderCost({ value }) {
                            if (!value || !Number(value)) {
                                return <span>N/A</span>
                            }
                            return <span>${Number(value).toFixed(4)}</span>
                        },
                    },
                },
            }}
            uniqueKey="llm-analytics-users"
        />
    )
}
