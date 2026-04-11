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

/**
 * Pair of (id, createdAt) for a trace we want to load a preview for. The
 * `createdAt` anchors the timestamp window used in the HogQL scan so
 * ClickHouse can prune partitions using the events table's
 * `(team_id, toDate(timestamp), event, ...)` primary key, regardless of how
 * wide the user's UI date filter is.
 */
export interface TraceLazyLoadRequest {
    id: string
    createdAt: string | null
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
/**
 * Minutes to buffer each side of the min/max `createdAt` in a batch. Matches
 * `TracesQueryDateRange.CAPTURE_RANGE_MINUTES` on the backend runner, which
 * assumes a trace finishes generating within 10 minutes of its first event.
 */
const BATCH_WINDOW_BUFFER_MINUTES = 10

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

/**
 * Format a Date as the `YYYY-MM-DD HH:MM:SS` ClickHouse `toDateTime` literal
 * form in UTC, avoiding timezone / locale ambiguity.
 */
function formatHogqlDateTime(d: Date): string {
    const pad = (n: number): string => String(n).padStart(2, '0')
    return (
        `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
        `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`
    )
}

export const traceMessagesLazyLoaderLogic = kea<traceMessagesLazyLoaderLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'traceMessagesLazyLoaderLogic']),

    actions({
        ensureTraceMessagesLoaded: (requests: TraceLazyLoadRequest[]) => ({ requests }),
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
        ensureTraceMessagesLoaded: ({ requests }) => {
            const uncached = requests.filter(
                (r) => r.id && values.messagesByTraceId[r.id] === undefined && !values.loadingTraceIds.has(r.id)
            )

            if (uncached.length === 0) {
                return
            }

            actions.markTraceIdsLoading(uncached.map((r) => r.id))

            const pendingTraces = cache.pendingTraces as Map<string, TraceLazyLoadRequest>
            for (const r of uncached) {
                pendingTraces.set(r.id, r)
            }

            if (cache.batchTimer) {
                return
            }

            cache.batchTimer = setTimeout(async () => {
                const requestedTraces = Array.from(pendingTraces.values())
                pendingTraces.clear()
                cache.batchTimer = null

                if (requestedTraces.length === 0) {
                    return
                }

                const chunks = chunk(requestedTraces, BATCH_MAX_SIZE)

                await Promise.allSettled(
                    chunks.map(async (batch) => {
                        try {
                            // Drop pathologically long IDs and traces whose createdAt
                            // we can't parse — we need a real timestamp anchor to
                            // build the scan window.
                            const safe: { id: string; createdAtMs: number }[] = []
                            for (const r of batch) {
                                if (!r.id || r.id.length > TRACE_ID_MAX_LENGTH) {
                                    continue
                                }
                                const createdAtMs = r.createdAt ? Date.parse(r.createdAt) : NaN
                                if (!Number.isFinite(createdAtMs)) {
                                    continue
                                }
                                safe.push({ id: r.id, createdAtMs })
                            }
                            if (safe.length === 0) {
                                actions.loadTraceMessagesBatchFailure(batch.map((r) => r.id))
                                return
                            }

                            // Union window across the batch: earliest createdAt minus
                            // the buffer to latest createdAt plus the buffer. In the
                            // common case (a page of traces clustered in time) this
                            // is a handful of minutes to hours wide — much narrower
                            // than the user's UI date filter, so ClickHouse can use
                            // the events table primary key to prune partitions
                            // regardless of whether the user picked `-1h` or
                            // `-30d`.
                            const bufferMs = BATCH_WINDOW_BUFFER_MINUTES * 60 * 1000
                            let minMs = Number.POSITIVE_INFINITY
                            let maxMs = Number.NEGATIVE_INFINITY
                            for (const s of safe) {
                                if (s.createdAtMs < minMs) {
                                    minMs = s.createdAtMs
                                }
                                if (s.createdAtMs > maxMs) {
                                    maxMs = s.createdAtMs
                                }
                            }
                            const fromStr = formatHogqlDateTime(new Date(minMs - bufferMs))
                            const toStr = formatHogqlDateTime(new Date(maxMs + bufferMs))

                            const idList = safe.map((s) => `'${escapeHogqlString(s.id)}'`).join(',')
                            // Return two candidates per direction: the top-level `$ai_trace`
                            // state (preferred when present — represents the clean
                            // user-query / final-answer for langchain/LangGraph traces) and
                            // the first/last `$ai_generation` payload (fallback for plain
                            // OpenAI/Anthropic/Vercel traces, or when the state wrapper
                            // resolves to empty messages after unwrap). Picker code on the
                            // frontend decides which to render.
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
                                      AND timestamp >= toDateTime('${fromStr}')
                                      AND timestamp <= toDateTime('${toStr}')
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

                            actions.loadTraceMessagesBatchSuccess(
                                results,
                                batch.map((r) => r.id)
                            )
                        } catch (error) {
                            console.warn('Error loading trace messages batch', error)
                            actions.loadTraceMessagesBatchFailure(batch.map((r) => r.id))
                        }
                    })
                )
            }, BATCH_DEBOUNCE_MS)
        },
    })),

    events(({ cache }) => ({
        afterMount: () => {
            cache.pendingTraces = new Map<string, TraceLazyLoadRequest>()
            cache.batchTimer = null
        },
        beforeUnmount: () => {
            if (cache.batchTimer) {
                clearTimeout(cache.batchTimer)
                cache.batchTimer = null
            }
            if (cache.pendingTraces instanceof Map) {
                cache.pendingTraces.clear()
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
