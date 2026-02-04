import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconCopy } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { isHogQLQuery } from '~/queries/utils'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { useSortableColumns } from './hooks/useSortableColumns'
import { llmAnalyticsSharedLogic } from './llmAnalyticsSharedLogic'
import { llmAnalyticsErrorsLogic } from './tabs/llmAnalyticsErrorsLogic'

export function LLMAnalyticsErrors(): JSX.Element {
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters } = useActions(llmAnalyticsSharedLogic)
    const { setErrorsSort } = useActions(llmAnalyticsErrorsLogic)
    const { errorsQuery, errorsSort } = useValues(llmAnalyticsErrorsLogic)
    const { searchParams } = useValues(router)

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
                        renderTitle: () => (
                            <Tooltip title="Normalized error message with IDs, timestamps, and numbers replaced by placeholders for grouping">
                                <span>Error</span>
                            </Tooltip>
                        ),
                        render: function RenderError(x) {
                            const errorValue = x.value
                            if (!errorValue || errorValue === 'null' || errorValue === '') {
                                return <span className="text-muted">No error</span>
                            }

                            const errorString = String(errorValue)
                            const displayValue =
                                errorString.length > 80 ? errorString.slice(0, 77) + '...' : errorString

                            return (
                                <div className="flex items-center gap-1">
                                    <Tooltip title={errorString}>
                                        <Link
                                            to={
                                                combineUrl(urls.llmAnalyticsTraces(), {
                                                    ...searchParams,
                                                    filters: [
                                                        {
                                                            type: PropertyFilterType.Event,
                                                            key: '$ai_is_error',
                                                            operator: PropertyOperator.Exact,
                                                            value: 'true',
                                                        },
                                                        {
                                                            type: PropertyFilterType.Event,
                                                            key: '$ai_error_normalized',
                                                            operator: PropertyOperator.Exact,
                                                            // Escape backslashes and quotes to match HogQL's JSONExtractRaw extraction
                                                            value: errorString
                                                                .replace(/\\/g, '\\\\')
                                                                .replace(/"/g, '\\"'),
                                                        },
                                                    ],
                                                }).url
                                            }
                                            className="font-mono text-sm"
                                            data-attr="llm-errors-row-click"
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
