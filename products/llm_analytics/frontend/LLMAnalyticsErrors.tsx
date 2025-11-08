import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { isHogQLQuery } from '~/queries/utils'
import { PropertyFilterType } from '~/types'

import { useSortableColumns } from './hooks/useSortableColumns'
import { llmAnalyticsLogic } from './llmAnalyticsLogic'

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
                columns: {
                    error: {
                        title: 'Error',
                        render: function RenderError(x) {
                            const errorValue = x.value
                            if (!errorValue || errorValue === 'null' || errorValue === '') {
                                return <span className="text-muted">No error</span>
                            }

                            const errorString = String(errorValue)
                            const displayValue =
                                errorString.length > 80 ? errorString.slice(0, 77) + '...' : errorString

                            return (
                                <Tooltip title={errorString}>
                                    <Link
                                        to={
                                            combineUrl(urls.llmAnalyticsTraces(), {
                                                filters: [
                                                    {
                                                        type: PropertyFilterType.Event,
                                                        key: '$ai_error',
                                                        operator: 'icontains' as any,
                                                        value: errorValue,
                                                    },
                                                ],
                                            }).url
                                        }
                                        className="font-mono text-sm"
                                    >
                                        {displayValue}
                                    </Link>
                                </Tooltip>
                            )
                        },
                    },
                    first_seen: {
                        renderTitle: () => renderSortableColumnTitle('first_seen', 'First Seen'),
                    },
                    last_seen: {
                        renderTitle: () => renderSortableColumnTitle('last_seen', 'Last Seen'),
                    },
                    traces: {
                        renderTitle: () => (
                            <Tooltip title="Number of unique traces with this error">
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
                    sessions: {
                        renderTitle: () => (
                            <Tooltip title="Number of unique sessions with this error">
                                {renderSortableColumnTitle('sessions', 'Sessions')}
                            </Tooltip>
                        ),
                    },
                    users: {
                        renderTitle: () => (
                            <Tooltip title="Number of unique users who encountered this error">
                                {renderSortableColumnTitle('users', 'Users')}
                            </Tooltip>
                        ),
                    },
                    days_seen: {
                        renderTitle: () => (
                            <Tooltip title="Number of distinct days this error occurred">
                                {renderSortableColumnTitle('days_seen', 'Days Seen')}
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
                            return <span>${Number(value).toFixed(4)}</span>
                        },
                    },
                },
            }}
            uniqueKey="llm-analytics-errors"
        />
    )
}
