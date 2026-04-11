import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import type { traceMessagesLazyLoaderLogicType } from './traceMessagesLazyLoaderLogicType'
import { parsePartialJSON } from './utils'

export interface TraceMessages {
    firstInput: unknown
    lastOutput: unknown
    /**
     * Fallback payloads drawn from the first/last `$ai_generation` on the
     * trace, used when the preferred `$ai_trace` state wrapper is missing or
     * resolves to an empty messages array.
     */
    firstInputFallback: unknown
    lastOutputFallback: unknown
}

const BATCH_MAX_SIZE = 100
const BATCH_DEBOUNCE_MS = 0
/**
 * Cap per raw field in characters. Enough to fit a small conversation's worth
 * of message content while bounding network payload at ~200KB per 100-row
 * batch. Truncated JSON is recovered on the frontend via parsePartialJSON.
 */
const FIELD_TRUNCATE_CHARS = 2000
/**
 * Upper bound on a trace ID length before we refuse to inline it into the
 * HogQL string. Real trace IDs are UUIDs (36 chars) or short nanoid-style
 * tokens. This guards against pathological IDs.
 */
const TRACE_ID_MAX_LENGTH = 128

function chunk<T>(arr: T[], size: number): T[][] {
    const chunks: T[][] = []
    for (let i = 0; i < arr.length; i += size) {
        chunks.push(arr.slice(i, i + size))
    }
    return chunks
}

/**
 * Escape a trace ID for safe inlining into a single-quoted HogQL string
 * literal. HogQL accepts both SQL-standard `''` and C-style `\'` escapes;
 * we normalize backslashes first, then double up any embedded quotes.
 */
function escapeHogqlString(value: string): string {
    return value.replace(/\\/g, '\\\\').replace(/'/g, "''")
}

export const traceMessagesLazyLoaderLogic = kea<traceMessagesLazyLoaderLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'traceMessagesLazyLoaderLogic']),

    actions({
        ensureTraceMessagesLoaded: (traceIds: string[]) => ({ traceIds }),
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
                        next[traceId] = results[traceId] ?? {
                            firstInput: null,
                            lastOutput: null,
                            firstInputFallback: null,
                            lastOutputFallback: null,
                        }
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
    }),

    selectors({
        getTraceMessages: [
            (s) => [s.messagesByTraceId],
            (messagesByTraceId): ((traceId: string) => TraceMessages | null | undefined) => {
                return (traceId: string) => messagesByTraceId[traceId]
            },
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        ensureTraceMessagesLoaded: ({ traceIds }) => {
            const uncached = traceIds.filter(
                (traceId) =>
                    traceId && values.messagesByTraceId[traceId] === undefined && !values.loadingTraceIds.has(traceId)
            )

            if (uncached.length === 0) {
                return
            }

            actions.markTraceIdsLoading(uncached)

            const pendingTraceIds = cache.pendingTraceIds as Set<string>
            for (const traceId of uncached) {
                pendingTraceIds.add(traceId)
            }

            if (cache.batchTimer) {
                return
            }

            cache.batchTimer = setTimeout(async () => {
                const requestedTraceIds = Array.from(pendingTraceIds)
                pendingTraceIds.clear()
                cache.batchTimer = null

                if (requestedTraceIds.length === 0) {
                    return
                }

                const chunks = chunk(requestedTraceIds, BATCH_MAX_SIZE)

                await Promise.allSettled(
                    chunks.map(async (batch) => {
                        try {
                            // Drop pathologically long IDs and inline the rest as properly
                            // escaped HogQL string literals. We can't use the `{traceIds}`
                            // value placeholder here because combining `values` with
                            // `{filters}` makes `parse_select` resolve all placeholders
                            // eagerly against the values dict. The inline path means
                            // escaping is our responsibility, so each ID is routed through
                            // `escapeHogqlString`.
                            const safeIds = batch.filter((id) => id && id.length <= TRACE_ID_MAX_LENGTH)
                            if (safeIds.length === 0) {
                                actions.loadTraceMessagesBatchFailure(batch)
                                return
                            }
                            const idList = safeIds.map((id) => `'${escapeHogqlString(id)}'`).join(',')
                            // Return two candidates per direction: the top-level `$ai_trace`
                            // state (preferred when present — represents the clean
                            // user-query / final-answer for langchain/LangGraph traces) and
                            // the first/last `$ai_generation` payload (fallback for plain
                            // OpenAI/Anthropic/Vercel traces, or when the state wrapper
                            // resolves to empty messages after unwrap). Picker code on the
                            // frontend decides which to render.
                            //
                            // We intentionally do NOT filter by date range. The trace ID
                            // IN (...) clause is selective enough on its own, and matching
                            // the trace query runner's ±10 minute boundary buffer would
                            // add complexity for a marginal perf benefit. Skipping the
                            // date filter also means the cached per-trace preview is
                            // stable across date-range changes in the UI — `argMin/argMax`
                            // over the same trace ID always returns the same events.
                            const query: HogQLQuery = {
                                kind: NodeKind.HogQLQuery,
                                query: `
                                    SELECT
                                        properties.$ai_trace_id AS trace_id,
                                        anyIf(
                                            substring(toString(properties.$ai_input_state), 1, ${FIELD_TRUNCATE_CHARS}),
                                            event = '$ai_trace'
                                                AND length(toString(properties.$ai_input_state)) > 0
                                        ) AS first_input,
                                        anyIf(
                                            substring(toString(properties.$ai_output_state), 1, ${FIELD_TRUNCATE_CHARS}),
                                            event = '$ai_trace'
                                                AND length(toString(properties.$ai_output_state)) > 0
                                        ) AS last_output,
                                        argMinIf(
                                            substring(toString(properties.$ai_input), 1, ${FIELD_TRUNCATE_CHARS}),
                                            timestamp,
                                            event = '$ai_generation'
                                                AND length(toString(properties.$ai_input)) > 0
                                        ) AS first_input_fallback,
                                        argMaxIf(
                                            substring(toString(properties.$ai_output_choices), 1, ${FIELD_TRUNCATE_CHARS}),
                                            timestamp,
                                            event = '$ai_generation'
                                                AND length(toString(properties.$ai_output_choices)) > 0
                                        ) AS last_output_fallback
                                    FROM events
                                    WHERE event IN ('$ai_trace', '$ai_generation')
                                      AND properties.$ai_trace_id IN (${idList})
                                    GROUP BY trace_id
                                `,
                            }

                            const response = await api.query(query)
                            const results: Record<string, TraceMessages> = {}

                            for (const row of response.results || []) {
                                const [traceId, firstInput, lastOutput, firstInputFallback, lastOutputFallback] =
                                    row as [string, unknown, unknown, unknown, unknown]
                                if (traceId) {
                                    results[traceId] = {
                                        firstInput: parseTruncatedJson(firstInput),
                                        lastOutput: parseTruncatedJson(lastOutput),
                                        firstInputFallback: parseTruncatedJson(firstInputFallback),
                                        lastOutputFallback: parseTruncatedJson(lastOutputFallback),
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
    })),

    events(({ cache }) => ({
        afterMount: () => {
            cache.pendingTraceIds = new Set<string>()
            cache.batchTimer = null
        },
        beforeUnmount: () => {
            if (cache.batchTimer) {
                clearTimeout(cache.batchTimer)
                cache.batchTimer = null
            }
            if (cache.pendingTraceIds instanceof Set) {
                cache.pendingTraceIds.clear()
            }
        },
    })),
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
