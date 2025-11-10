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

                            // Extract the first 3 chunks of text between placeholders for filtering
                            // These chunks are the stable parts of the error message
                            const tokens = errorString
                                .split(/<ID>|<TIMESTAMP>|<PATH>|<RESPONSE_ID>|<TOOL_CALL_ID>|<TOKEN_COUNT>|<N>/)
                                .map((token) => token.trim())
                                .filter((token) => token.length >= 3) // Only keep meaningful chunks
                                .slice(0, 3) // Take first 3 chunks

                            return (
                                <div className="flex items-center gap-1">
                                    <Tooltip title={errorString}>
                                        <Link
                                            to={
                                                combineUrl(urls.llmAnalyticsTraces(), {
                                                    filters: [
                                                        // First filter: only show traces with errors
                                                        {
                                                            type: PropertyFilterType.Event,
                                                            key: '$ai_is_error',
                                                            operator: 'exact' as any,
                                                            value: 'true',
                                                        },
                                                        // Then filter by key words from the error
                                                        ...tokens.map((token) => ({
                                                            type: PropertyFilterType.Event,
                                                            key: '$ai_error',
                                                            operator: 'icontains' as any,
                                                            value: token,
                                                        })),
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
                    spans: {
                        renderTitle: () => (
                            <Tooltip title="Number of spans with this error">
                                {renderSortableColumnTitle('spans', 'Spans')}
                            </Tooltip>
                        ),
                    },
                    embeddings: {
                        renderTitle: () => (
                            <Tooltip title="Number of embeddings with this error">
                                {renderSortableColumnTitle('embeddings', 'Embeddings')}
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
