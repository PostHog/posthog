import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import type { traceMessagesLazyLoaderLogicType } from './traceMessagesLazyLoaderLogicType'
import { parsePartialJSON } from './utils'

export interface TraceMessages {
    firstInput: unknown
    lastOutput: unknown
}

export interface TraceMessagesDateRange {
    dateFrom: string | null
    dateTo: string | null
}

const BATCH_MAX_SIZE = 100
const BATCH_DEBOUNCE_MS = 0
/**
 * Cap per raw field in characters. Enough to fit a small conversation's worth
 * of message content while bounding network payload at ~200KB per 100-row
 * batch. Truncated JSON is recovered on the frontend via parsePartialJSON.
 */
const FIELD_TRUNCATE_CHARS = 2000
const UUID_RE = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/

function chunk<T>(arr: T[], size: number): T[][] {
    const chunks: T[][] = []
    for (let i = 0; i < arr.length; i += size) {
        chunks.push(arr.slice(i, i + size))
    }
    return chunks
}

export const traceMessagesLazyLoaderLogic = kea<traceMessagesLazyLoaderLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'traceMessagesLazyLoaderLogic']),

    actions({
        ensureTraceMessagesLoaded: (traceIds: string[]) => ({ traceIds }),
        setDateRange: (dateRange: TraceMessagesDateRange) => ({ dateRange }),
        markTraceIdsLoading: (traceIds: string[]) => ({ traceIds }),
        loadTraceMessagesBatchSuccess: (results: Record<string, TraceMessages>, requestedTraceIds: string[]) => ({
            results,
            requestedTraceIds,
        }),
        loadTraceMessagesBatchFailure: (requestedTraceIds: string[]) => ({ requestedTraceIds }),
    }),

    reducers({
        messagesByTraceId: [
            {} as Record<string, TraceMessages | null>,
            {
                loadTraceMessagesBatchSuccess: (state, { results, requestedTraceIds }) => {
                    const next = { ...state }
                    for (const traceId of requestedTraceIds) {
                        next[traceId] = results[traceId] ?? { firstInput: null, lastOutput: null }
                    }
                    return next
                },
                loadTraceMessagesBatchFailure: (state, { requestedTraceIds }) => {
                    const next = { ...state }
                    for (const traceId of requestedTraceIds) {
                        next[traceId] = null
                    }
                    return next
                },
            },
        ],

        loadingTraceIds: [
            new Set<string>(),
            {
                markTraceIdsLoading: (state, { traceIds }) => {
                    const next = new Set(state)
                    for (const traceId of traceIds) {
                        if (traceId) {
                            next.add(traceId)
                        }
                    }
                    return next
                },
                loadTraceMessagesBatchSuccess: (state, { requestedTraceIds }) => {
                    const next = new Set(state)
                    for (const traceId of requestedTraceIds) {
                        next.delete(traceId)
                    }
                    return next
                },
                loadTraceMessagesBatchFailure: (state, { requestedTraceIds }) => {
                    const next = new Set(state)
                    for (const traceId of requestedTraceIds) {
                        next.delete(traceId)
                    }
                    return next
                },
            },
        ],

        dateRange: [
            { dateFrom: null, dateTo: null } as TraceMessagesDateRange,
            {
                setDateRange: (_, { dateRange }) => dateRange,
            },
        ],
    }),

    selectors({
        getTraceMessages: [
            (s) => [s.messagesByTraceId],
            (messagesByTraceId): ((traceId: string) => TraceMessages | null | undefined) => {
                return (traceId: string) => messagesByTraceId[traceId]
            },
        ],
        isTraceLoading: [
            (s) => [s.loadingTraceIds],
            (loadingTraceIds): ((traceId: string) => boolean) => {
                return (traceId: string) => loadingTraceIds.has(traceId)
            },
        ],
    }),

    listeners(({ actions, values }) => {
        let pendingTraceIds = new Set<string>()
        let batchTimer: ReturnType<typeof setTimeout> | null = null

        return {
            ensureTraceMessagesLoaded: ({ traceIds }) => {
                const uncached = traceIds.filter(
                    (traceId) =>
                        traceId &&
                        values.messagesByTraceId[traceId] === undefined &&
                        !values.loadingTraceIds.has(traceId)
                )

                if (uncached.length === 0) {
                    return
                }

                actions.markTraceIdsLoading(uncached)

                for (const traceId of uncached) {
                    pendingTraceIds.add(traceId)
                }

                if (batchTimer) {
                    return
                }

                batchTimer = setTimeout(async () => {
                    const requestedTraceIds = Array.from(pendingTraceIds)
                    pendingTraceIds = new Set()
                    batchTimer = null

                    if (requestedTraceIds.length === 0) {
                        return
                    }

                    const { dateFrom, dateTo } = values.dateRange
                    const chunks = chunk(requestedTraceIds, BATCH_MAX_SIZE)

                    await Promise.allSettled(
                        chunks.map(async (batch) => {
                            try {
                                // Inline trace IDs and truncate size instead of using {placeholder}
                                // values. `parse_select` eagerly resolves all placeholders against
                                // the `values` dict and errors if it encounters `{filters}`, so we
                                // can't combine the two. IDs are filtered to the UUID shape as
                                // defense-in-depth before inlining.
                                const safeIds = batch.filter((id) => UUID_RE.test(id))
                                if (safeIds.length === 0) {
                                    actions.loadTraceMessagesBatchSuccess({}, batch)
                                    return
                                }
                                const idList = safeIds.map((id) => `'${id}'`).join(',')
                                const query: HogQLQuery = {
                                    kind: NodeKind.HogQLQuery,
                                    query: `
                                        SELECT
                                            properties.$ai_trace_id AS trace_id,
                                            argMin(
                                                substring(toString(properties.$ai_input), 1, ${FIELD_TRUNCATE_CHARS}),
                                                timestamp
                                            ) AS first_input,
                                            argMax(
                                                substring(toString(properties.$ai_output_choices), 1, ${FIELD_TRUNCATE_CHARS}),
                                                timestamp
                                            ) AS last_output
                                        FROM events
                                        WHERE event = '$ai_generation'
                                          AND properties.$ai_trace_id IN (${idList})
                                          AND {filters}
                                        GROUP BY trace_id
                                    `,
                                    filters: {
                                        dateRange: {
                                            date_from: dateFrom || null,
                                            date_to: dateTo || null,
                                        },
                                    },
                                }

                                const response = await api.query(query)
                                const results: Record<string, TraceMessages> = {}

                                for (const row of response.results || []) {
                                    const [traceId, firstInput, lastOutput] = row as [string, unknown, unknown]
                                    if (traceId) {
                                        results[traceId] = {
                                            firstInput: parseTruncatedJson(firstInput),
                                            lastOutput: parseTruncatedJson(lastOutput),
                                        }
                                    }
                                }

                                actions.loadTraceMessagesBatchSuccess(results, batch)
                            } catch (error) {
                                console.warn('Error loading trace messages batch', error)
                                actions.loadTraceMessagesBatchFailure(batch)
                            }
                        })
                    )
                }, BATCH_DEBOUNCE_MS)
            },
        }
    }),
])

/**
 * Parse a JSON string that ClickHouse may have truncated mid-structure.
 * Falls back to a strict parse for safety, then the partial-JSON parser
 * which closes dangling braces/brackets/strings. If everything fails the
 * raw string is returned so the normalizer can at least show something.
 */
function parseTruncatedJson(value: unknown): unknown {
    if (typeof value !== 'string') {
        return value
    }
    if (value.length === 0) {
        return null
    }
    try {
        return JSON.parse(value)
    } catch {
        // fall through to partial parse
    }
    try {
        return parsePartialJSON(value)
    } catch {
        return value
    }
}
