import { useActions, useMountedLogic, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useEffect } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
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
import { TraceMessages, traceMessagesLazyLoaderLogic } from './traceMessagesLazyLoaderLogic'
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
    useMountedLogic(traceMessagesLazyLoaderLogic)

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
            createdAt: {
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
            __llm_sentiment: llmAnalyticsColumnRenderers.__llm_sentiment,
            __llm_tools: llmAnalyticsColumnRenderers.__llm_tools,
            errorCount: {
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

// `undefined` = cache miss (still loading). Checking the cached record
// directly avoids a one-frame dash flash before a separate loading reducer
// catches up on the first render.
function useTraceMessagesForRow(row: LLMTrace): TraceMessages | null | undefined {
    const { ensureTraceMessagesLoaded } = useActions(traceMessagesLazyLoaderLogic)
    const { getTraceMessages } = useValues(traceMessagesLazyLoaderLogic)
    useEffect(() => {
        if (row.id) {
            ensureTraceMessagesLoaded([{ id: row.id, createdAt: row.createdAt ?? null }])
        }
    }, [row.id, row.createdAt, ensureTraceMessagesLoaded])
    return getTraceMessages(row.id)
}

const InputMessageColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    const messages = useTraceMessagesForRow(row)
    if (messages === undefined) {
        return <LemonSkeleton className="h-4 w-40" />
    }
    // Three-tier fallback: clean state unwrap → generation fallback → raw state dump.
    const firstInput =
        pickFirstInputMessage(messages?.firstInput, { strict: true }) ??
        pickFirstInputMessage(messages?.firstInputFallback) ??
        pickFirstInputMessage(messages?.firstInput)
    if (!firstInput) {
        return <>–</>
    }
    return <LLMMessageDisplay message={firstInput} isOutput={false} minimal />
}
InputMessageColumn.displayName = 'InputMessageColumn'

const OutputMessageColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    const messages = useTraceMessagesForRow(row)

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

    if (messages === undefined) {
        return <LemonSkeleton className="h-4 w-40" />
    }

    const lastOutput =
        pickLastOutputMessage(messages?.lastOutput, { strict: true }) ??
        pickLastOutputMessage(messages?.lastOutputFallback) ??
        pickLastOutputMessage(messages?.lastOutput)
    if (!lastOutput) {
        return <>–</>
    }
    return <LLMMessageDisplay message={lastOutput} isOutput={true} minimal />
}
OutputMessageColumn.displayName = 'OutputMessageColumn'

type NormalizedMessage = ReturnType<typeof normalizeMessages>[number]

function hasDisplayableContent(message: NormalizedMessage): boolean {
    const { content, tool_calls } = message as NormalizedMessage & { tool_calls?: unknown }
    if (typeof content === 'string' && content.trim().length > 0) {
        return true
    }
    if (Array.isArray(content) && content.length > 0) {
        return true
    }
    if (Array.isArray(tool_calls) && tool_calls.length > 0) {
        return true
    }
    return false
}

/**
 * Preferred → fallback cascade for the trace input column. We prefer the first
 * actual user turn, but tolerate traces that open with a system prompt or a
 * tool-result by falling back down the list. When `strict` is true we reject
 * unknown state-wrapper shapes (the caller will then try the generation-level
 * fallback payload).
 */
function pickFirstInputMessage(
    raw: unknown,
    { strict }: { strict: boolean } = { strict: false }
): NormalizedMessage | null {
    const normalized = safeNormalize(raw, 'user', { strict })
    if (normalized.length === 0) {
        return null
    }
    const firstUser = normalized.find((m) => m.role === 'user' && hasDisplayableContent(m))
    if (firstUser) {
        return firstUser
    }
    const firstNonSystem = normalized.find((m) => m.role !== 'system' && hasDisplayableContent(m))
    if (firstNonSystem) {
        return firstNonSystem
    }
    const firstDisplayable = normalized.find(hasDisplayableContent)
    if (firstDisplayable) {
        return firstDisplayable
    }
    return normalized[0]
}

/**
 * Preferred → fallback cascade for the trace output column. We prefer the
 * last assistant message with real content, but fall back to the last
 * displayable message (e.g. tool_calls) so tool-calling traces still show
 * something useful instead of a dash.
 */
function pickLastOutputMessage(
    raw: unknown,
    { strict }: { strict: boolean } = { strict: false }
): NormalizedMessage | null {
    const normalized = safeNormalize(raw, 'assistant', { strict })
    if (normalized.length === 0) {
        return null
    }
    for (let i = normalized.length - 1; i >= 0; i--) {
        if (normalized[i].role === 'assistant' && hasDisplayableContent(normalized[i])) {
            return normalized[i]
        }
    }
    for (let i = normalized.length - 1; i >= 0; i--) {
        if (hasDisplayableContent(normalized[i])) {
            return normalized[i]
        }
    }
    return normalized[normalized.length - 1]
}

/**
 * Some SDKs emit the trace input/output as a state wrapper object rather than a
 * bare messages array. Langchain/LangGraph writes `$ai_input_state` /
 * `$ai_output_state` as something like `{ agent_mode, messages: [...], ... }`.
 * Drill into the known `.messages` key so the picker sees a clean array; for
 * unknown wrapper shapes (agent-specific state like `{ current_step, ... }`)
 * return `null` in strict mode so the picker can fall through to the
 * generation-level fallback rather than dumping raw JSON.
 */
function unwrapMessageContainer(raw: unknown, strict: boolean): unknown {
    if (raw == null || typeof raw !== 'object' || Array.isArray(raw)) {
        return raw
    }
    const obj = raw as Record<string, unknown>
    if (Array.isArray(obj.messages)) {
        return obj.messages
    }
    return strict ? null : raw
}

function safeNormalize(
    raw: unknown,
    defaultRole: string,
    { strict }: { strict: boolean } = { strict: false }
): ReturnType<typeof normalizeMessages> {
    const unwrapped = unwrapMessageContainer(raw, strict)
    if (unwrapped == null) {
        return []
    }
    try {
        return normalizeMessages(unwrapped, defaultRole)
    } catch (e) {
        console.warn('Error normalizing trace messages', e)
        return []
    }
}
