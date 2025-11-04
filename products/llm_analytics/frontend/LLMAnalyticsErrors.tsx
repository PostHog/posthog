import { useActions, useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
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
                        render: function RenderError({ value }) {
                            const errorMessage = (value as string) || 'Unknown error'
                            const truncated = errorMessage.length > 100 ? `${errorMessage.slice(0, 100)}...` : errorMessage
                            return (
                                <div className="max-w-2xl">
                                    <Tooltip title={errorMessage}>
                                        <span className="font-mono text-sm break-words">{truncated}</span>
                                    </Tooltip>
                                </div>
                            )
                        },
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
                            <Tooltip title="Total cost of failed generations with this error">
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
                    first_seen: {
                        renderTitle: () => renderSortableColumnTitle('first_seen', 'First Seen'),
                        render: function RenderFirstSeen({ value }) {
                            return <TZLabel time={value as string} />
                        },
                    },
                    last_seen: {
                        renderTitle: () => renderSortableColumnTitle('last_seen', 'Last Seen'),
                        render: function RenderLastSeen({ value }) {
                            return <TZLabel time={value as string} />
                        },
                    },
                },
            }}
            uniqueKey="llm-analytics-errors"
        />
    )
}
