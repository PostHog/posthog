import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconCopy } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
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

                            // Extract a stable part of the error for filtering by removing our normalization placeholders
                            // This gives us a pattern that should match the original errors
                            const searchPattern = errorString
                                .replace(/<ID>/g, '')
                                .replace(/<TIMESTAMP>/g, '')
                                .replace(/<PATH>/g, '')
                                .replace(/<RESPONSE_ID>/g, '')
                                .replace(/<TOOL_CALL_ID>/g, '')
                                .replace(/<TOKEN_COUNT>/g, '')
                                .replace(/\s+/g, ' ') // Collapse multiple spaces
                                .trim()
                                .slice(0, 100) // Take first 100 chars of the stable part

                            return (
                                <div className="flex items-center gap-1">
                                    <Tooltip title={errorString}>
                                        <Link
                                            to={
                                                combineUrl(urls.llmAnalyticsTraces(), {
                                                    filters: [
                                                        {
                                                            type: PropertyFilterType.Event,
                                                            key: '$ai_error',
                                                            operator: 'icontains' as any,
                                                            value: searchPattern,
                                                        },
                                                    ],
                                                }).url
                                            }
                                            className="font-mono text-sm"
                                        >
                                            {displayValue}
                                        </Link>
                                    </Tooltip>
                                    <LemonButton
                                        size="xsmall"
                                        noPadding
                                        icon={<IconCopy />}
                                        onClick={(e) => {
                                            e.preventDefault()
                                            e.stopPropagation()
                                            copyToClipboard(errorString, 'error')
                                        }}
                                        tooltip="Copy error to clipboard"
                                        className="opacity-50 hover:opacity-100"
                                    />
                                </div>
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
                },
            }}
            uniqueKey="llm-analytics-errors"
        />
    )
}
