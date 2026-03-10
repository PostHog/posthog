import { useActions, useMountedLogic, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { objectsEqual } from 'lib/utils'
import { urls } from 'scenes/urls'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { DataTableNode, LLMTrace } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumnComponent } from '~/queries/types'
import { isTracesQuery } from '~/queries/utils'

import { LLMMessageDisplay } from './ConversationDisplay/ConversationMessagesDisplay'
import { llmAnalyticsColumnRenderers } from './llmAnalyticsColumnRenderers'
import { llmAnalyticsSharedLogic } from './llmAnalyticsSharedLogic'
import { llmAnalyticsTracesTabLogic } from './tabs/llmAnalyticsTracesTabLogic'
import { traceReviewsLazyLoaderLogic } from './traceReviews/traceReviewsLazyLoaderLogic'
import {
    formatLLMCost,
    formatLLMLatency,
    formatLLMUsage,
    getTraceTimestamp,
    normalizeMessages,
    sanitizeTraceUrlSearchParams,
} from './utils'

export function LLMAnalyticsTraces(): JSX.Element {
    useMountedLogic(traceReviewsLazyLoaderLogic)

    const { setDates, setShouldFilterTestAccounts, setShouldFilterSupportTraces, setPropertyFilters } =
        useActions(llmAnalyticsSharedLogic)
    const { propertyFilters: currentPropertyFilters } = useValues(llmAnalyticsSharedLogic)
    const { tracesQuery } = useValues(llmAnalyticsTracesTabLogic)

    return (
        <div data-attr="llm-trace-table">
            <DataTable
                attachTo={llmAnalyticsSharedLogic}
                query={{
                    ...tracesQuery,
                    showSavedFilters: true,
                }}
                setQuery={(query) => {
                    if (!isTracesQuery(query.source)) {
                        throw new Error('Invalid query')
                    }
                    setDates(query.source.dateRange?.date_from || null, query.source.dateRange?.date_to || null)
                    setShouldFilterTestAccounts(query.source.filterTestAccounts || false)
                    setShouldFilterSupportTraces(query.source.filterSupportTraces ?? true)

                    const newPropertyFilters = query.source.properties || []
                    if (!objectsEqual(newPropertyFilters, currentPropertyFilters)) {
                        setPropertyFilters(newPropertyFilters)
                    }
                }}
                context={useTracesQueryContext()}
                uniqueKey="llm-analytics-traces"
            />
        </div>
    )
}

export const useTracesQueryContext = (): QueryContext<DataTableNode> => {
    return {
        emptyStateHeading: 'There were no traces in this period',
        emptyStateDetail: 'Try changing the date range or filters.',
        columns: {
            id: {
                title: 'ID',
                render: IDColumn,
            },
            inputState: {
                title: 'Input message',
                render: InputMessageColumn,
            },
            outputState: {
                title: 'Output message',
                render: OutputMessageColumn,
            },
            timestamp: {
                title: 'Time',
                render: TimestampColumn,
            },
            traceName: {
                title: 'Trace Name',
                render: TraceNameColumn,
            },
            review: llmAnalyticsColumnRenderers.review,
            promptVersion: {
                title: 'Prompt version',
                render: PromptVersionColumn,
            },
            promptVersionId: {
                title: 'Prompt version ID',
                render: PromptVersionIdColumn,
            },
            person: llmAnalyticsColumnRenderers.person,
            sentiment: llmAnalyticsColumnRenderers.sentiment,
            tools: llmAnalyticsColumnRenderers.tools,
            errors: {
                renderTitle: () => <Tooltip title="Number of errors in this trace">Errors</Tooltip>,
                render: ErrorsColumn,
            },
            totalLatency: {
                renderTitle: () => <Tooltip title="Total latency of all operations in this trace">Latency</Tooltip>,
                render: LatencyColumn,
            },
            usage: {
                renderTitle: () => (
                    <Tooltip title="Total token usage (input + output) for this trace">Token Usage</Tooltip>
                ),
                render: UsageColumn,
            },
            totalCost: {
                renderTitle: () => (
                    <Tooltip title="Total cost of all generations and embeddings in this trace">Cost</Tooltip>
                ),
                render: CostColumn,
            },
        },
    }
}

const IDColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    const { searchParams } = useValues(router)
    const nonTraceSearchParams = sanitizeTraceUrlSearchParams(searchParams, { removeSearch: true })
    return (
        <strong>
            <Tooltip title={row.id}>
                <Link
                    to={
                        combineUrl(urls.llmAnalyticsTrace(row.id), {
                            ...nonTraceSearchParams,
                            back_to: 'traces',
                            timestamp: getTraceTimestamp(row.createdAt),
                        }).url
                    }
                    data-attr="trace-id-link"
                >
                    {row.id.slice(0, 4)}...{row.id.slice(-4)}
                </Link>
            </Tooltip>
        </strong>
    )
}

const TraceNameColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    const { searchParams } = useValues(router)
    const nonTraceSearchParams = sanitizeTraceUrlSearchParams(searchParams, { removeSearch: true })
    return (
        <div className="flex items-center gap-2">
            <strong>
                <Link
                    to={
                        combineUrl(urls.llmAnalyticsTrace(row.id), {
                            ...nonTraceSearchParams,
                            back_to: 'traces',
                            timestamp: getTraceTimestamp(row.createdAt),
                        }).url
                    }
                    data-attr="trace-name-link"
                >
                    {row.traceName || '–'}
                </Link>
            </strong>
            {row.isSupportTrace && <LemonTag type="muted">Support</LemonTag>}
        </div>
    )
}

const TimestampColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    return <TZLabel time={row.createdAt} />
}
TimestampColumn.displayName = 'TimestampColumn'

const PromptVersionColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    const promptVersions = Array.from(
        new Set(
            row.events
                .map((event) => event.properties?.['$ai_prompt_version'])
                .filter((value): value is string | number => typeof value === 'string' || typeof value === 'number')
                .map((value) => String(value))
                .filter((value) => value.length > 0)
        )
    )

    if (promptVersions.length === 0) {
        return <>–</>
    }

    const primaryVersion = promptVersions[0]

    return (
        <Tooltip title={promptVersions.map((version) => `v${version}`).join(', ')}>
            <span className="block max-w-28 truncate font-mono text-xs">v{primaryVersion}</span>
        </Tooltip>
    )
}
PromptVersionColumn.displayName = 'PromptVersionColumn'

const PromptVersionIdColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    const promptVersionIds = Array.from(
        new Set(
            row.events
                .map((event) => event.properties?.['$ai_prompt_version_id'])
                .filter((value): value is string => typeof value === 'string' && value.length > 0)
        )
    )

    if (promptVersionIds.length === 0) {
        return <>–</>
    }

    const primaryVersionId = promptVersionIds[0]

    return (
        <Tooltip title={promptVersionIds.join(', ')}>
            <span className="block max-w-56 truncate font-mono text-xs">{primaryVersionId}</span>
        </Tooltip>
    )
}
PromptVersionIdColumn.displayName = 'PromptVersionIdColumn'

const LatencyColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    if (typeof row.totalLatency === 'number') {
        return <>{formatLLMLatency(row.totalLatency, true)}</>
    }
    return <>–</>
}
LatencyColumn.displayName = 'LatencyColumn'

const UsageColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    const usage = formatLLMUsage(row)
    return <>{usage || '–'}</>
}
UsageColumn.displayName = 'UsageColumn'

const CostColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    if (typeof row.totalCost === 'number') {
        return <>{formatLLMCost(row.totalCost)}</>
    }
    return <>–</>
}
CostColumn.displayName = 'CostColumn'

const ErrorsColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    if (typeof row.errorCount === 'number' && row.errorCount > 0) {
        return <LemonTag type="danger">{row.errorCount}</LemonTag>
    }
    return <>–</>
}
ErrorsColumn.displayName = 'ErrorsColumn'

const InputMessageColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    const inputNormalized = normalizeMessages(row.inputState?.messages, 'user')
    if (!inputNormalized.length) {
        return <>–</>
    }
    return <LLMMessageDisplay message={inputNormalized.at(-1)!} isOutput={false} minimal />
}
InputMessageColumn.displayName = 'InputMessageColumn'

const OutputMessageColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    const errorEventFound = Array.isArray(row.events)
        ? row.events.find((e) => e.properties?.$ai_error || e.properties?.$ai_is_error)
        : false
    if (errorEventFound) {
        return (
            <LemonTag type="danger" className="font-mono max-w-50 truncate">
                {errorEventFound.properties?.$ai_error || 'Unknown error'}
            </LemonTag>
        )
    }
    const outputNormalized = normalizeMessages(row.outputState?.messages, 'assistant')
    if (!outputNormalized.length) {
        return <>–</>
    }
    return <LLMMessageDisplay message={outputNormalized.at(-1)!} isOutput={true} minimal />
}
OutputMessageColumn.displayName = 'OutputMessageColumn'
