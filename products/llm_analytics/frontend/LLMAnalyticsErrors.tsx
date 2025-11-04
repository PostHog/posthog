import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
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
                emptyStateHeading: 'There were no errors in this period',
                emptyStateDetail: 'Try changing the date range or filters.',
                columns: {
                    error_message: {
                        title: 'Error message',
                        render: function RenderError({ value }) {
                            if (!value || typeof value !== 'string') {
                                return <span className="text-muted">No error message</span>
                            }

                            // Try to parse as JSON to get a cleaner display
                            let errorText = value
                            try {
                                const parsed = JSON.parse(value)
                                if (typeof parsed === 'string') {
                                    errorText = parsed
                                } else if (parsed.message) {
                                    errorText = parsed.message
                                } else if (parsed.error) {
                                    errorText = parsed.error
                                }
                            } catch {
                                // Not JSON, use as is
                            }

                            return (
                                <div className="flex items-center gap-2">
                                    <LemonTag type="danger" size="small">
                                        Error
                                    </LemonTag>
                                    <Tooltip title={value}>
                                        <span
                                            className="font-mono text-xs truncate max-w-lg"
                                            onClick={() => {
                                                // Link to traces with this error
                                                const url = combineUrl(urls.llmAnalyticsTraces(), {
                                                    filters: [
                                                        {
                                                            type: PropertyFilterType.HogQL,
                                                            key: `properties.$ai_error == ${JSON.stringify(value)}`,
                                                            value: null,
                                                        },
                                                    ],
                                                }).url
                                                window.location.href = url
                                            }}
                                            style={{ cursor: 'pointer' }}
                                        >
                                            {errorText}
                                        </span>
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
                            <Tooltip title="Number of users affected by this error">
                                {renderSortableColumnTitle('users', 'Users')}
                            </Tooltip>
                        ),
                    },
                    first_seen: {
                        renderTitle: () => renderSortableColumnTitle('first_seen', 'First seen'),
                        render: function RenderFirstSeen({ value }) {
                            return <TZLabel time={value as string} />
                        },
                    },
                    last_seen: {
                        renderTitle: () => renderSortableColumnTitle('last_seen', 'Last seen'),
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
