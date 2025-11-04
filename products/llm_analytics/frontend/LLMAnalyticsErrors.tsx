import { useActions, useValues } from 'kea'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { isHogQLQuery } from '~/queries/utils'

import { useSortableColumns } from './hooks/useSortableColumns'
import { llmAnalyticsLogic } from './llmAnalyticsLogic'
import { formatLLMCost } from './utils'

export function LLMAnalyticsErrors(): JSX.Element {
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters, setErrorsSort } = useActions(llmAnalyticsLogic)
    const { errorsQuery, errorsSort } = useValues(llmAnalyticsLogic)

    const { renderSortableColumnTitle } = useSortableColumns(errorsSort, setErrorsSort)

    return (
        <DataTable
            query={{
                ...errorsQuery,
                showSavedFilters: true,
            }}
            setQuery={(query) => {
                if (!isHogQLQuery(query.source)) {
                    console.warn('LLMAnalyticsErrors received a non-HogQL query:', query.source)
                    return
                }
                const { filters = {} } = query.source
                const { dateRange = {} } = filters
                setDates(dateRange.date_from || null, dateRange.date_to || null)
                setShouldFilterTestAccounts(filters.filterTestAccounts || false)
                setPropertyFilters(filters.properties || [])
            }}
            context={{
                emptyStateHeading: 'There were no errors in this period',
                emptyStateDetail: 'Try changing the date range or filters.',
                columns: {
                    error_message: {
                        title: 'Error message',
                        render: function RenderErrorMessage({ value }) {
                            const errorMessage = value as string
                            if (!errorMessage || errorMessage === 'No error message') {
                                return <span className="text-muted">No error message</span>
                            }
                            return (
                                <div className="max-w-md">
                                    <Tooltip title={errorMessage}>
                                        <span className="font-mono text-sm">{errorMessage}</span>
                                    </Tooltip>
                                </div>
                            )
                        },
                    },
                    first_seen: {
                        renderTitle: () => renderSortableColumnTitle('first_seen', 'First seen'),
                    },
                    last_seen: {
                        renderTitle: () => renderSortableColumnTitle('last_seen', 'Last seen'),
                    },
                    traces: {
                        renderTitle: () => (
                            <Tooltip title="Number of traces with this error">
                                {renderSortableColumnTitle('traces', 'Traces')}
                            </Tooltip>
                        ),
                    },
                    generations: {
                        renderTitle: () => (
                            <Tooltip title="Number of generations with this error">
                                {renderSortableColumnTitle('generations', 'Generations')}
                            </Tooltip>
                        ),
                    },
                    users: {
                        renderTitle: () => (
                            <Tooltip title="Number of users who encountered this error">
                                {renderSortableColumnTitle('users', 'Users')}
                            </Tooltip>
                        ),
                    },
                    total_cost: {
                        renderTitle: () => (
                            <Tooltip title="Total cost of all generations with this error">
                                {renderSortableColumnTitle('total_cost', 'Cost')}
                            </Tooltip>
                        ),
                        render: function RenderCost({ value }) {
                            if (!value || !Number(value)) {
                                return <span>N/A</span>
                            }
                            return <span>{formatLLMCost(Number(value))}</span>
                        },
                    },
                },
            }}
            uniqueKey="llm-analytics-errors"
        />
    )
}
