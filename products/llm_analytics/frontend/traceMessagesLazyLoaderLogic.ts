import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import type { traceMessagesLazyLoaderLogicType } from './traceMessagesLazyLoaderLogicType'
import { parsePartialJSON } from './utils'

export interface TraceMessages {
    firstInput: unknown
    lastOutput: unknown
    // First/last $ai_generation payloads, used when the preferred $ai_trace
    // state wrapper is missing or resolves to an empty messages array.
    firstInputFallback: unknown
    lastOutputFallback: unknown
}

export interface TraceLazyLoadRequest {
    id: string
    createdAt: string | null
}

const BATCH_MAX_SIZE = 100
const BATCH_DEBOUNCE_MS = 0
// Cap per field in characters. Bounds network payload and ClickHouse
// aggregation state; truncated JSON is recovered with parsePartialJSON.
const FIELD_TRUNCATE_CHARS = 2000
const TRACE_ID_MAX_LENGTH = 128
// Matches TracesQueryDateRange.CAPTURE_RANGE_MINUTES on the backend runner.
const BATCH_WINDOW_BUFFER_MINUTES = 10

function chunk<T>(arr: T[], size: number): T[][] {
    const chunks: T[][] = []
    for (let i = 0; i < arr.length; i += size) {
        chunks.push(arr.slice(i, i + size))
    }
    return chunks
}

// Escape a trace ID for safe inlining into a single-quoted HogQL string.
function escapeHogqlString(value: string): string {
    return value.replace(/\\/g, '\\\\').replace(/'/g, "''")
}

// "2026-04-11T19:20:55.828Z" → "2026-04-11 19:20:55" (ClickHouse toDateTime format, UTC).
function formatHogqlDateTime(d: Date): string {
    return d.toISOString().replace('T', ' ').slice(0, 19)
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
                            // Drop IDs that are too long to inline safely or whose
                            // createdAt we can't parse into a scan window anchor.
                            const safe = batch.flatMap((r) => {
                                const createdAtMs = r.createdAt ? Date.parse(r.createdAt) : NaN
                                return r.id && r.id.length <= TRACE_ID_MAX_LENGTH && Number.isFinite(createdAtMs)
                                    ? [{ id: r.id, createdAtMs }]
                                    : []
                            })
                            // Mark the dropped entries as failed upfront so they
                            // aren't silently counted as "successfully loaded with
                            // no data" alongside the real response.
                            const safeIdSet = new Set(safe.map((s) => s.id))
                            const invalidIds = batch.map((r) => r.id).filter((id) => !safeIdSet.has(id))
                            if (invalidIds.length > 0) {
                                actions.loadTraceMessagesBatchFailure(invalidIds)
                            }
                            if (safe.length === 0) {
                                return
                            }

                            // Union window across the batch (min/max createdAt ± buffer).
                            // Stays narrow when rows are clustered in time, so ClickHouse
                            // can prune partitions regardless of the UI date filter.
                            const bufferMs = BATCH_WINDOW_BUFFER_MINUTES * 60 * 1000
                            const createdAtList = safe.map((s) => s.createdAtMs)
                            const fromStr = formatHogqlDateTime(new Date(Math.min(...createdAtList) - bufferMs))
                            const toStr = formatHogqlDateTime(new Date(Math.max(...createdAtList) + bufferMs))

                            // Inlining IDs + timestamps rather than using a values dict: we
                            // can't combine `{values}` with `{filters}`-style placeholders
                            // because parse_select eagerly resolves all placeholders against
                            // the values dict before find_placeholders runs. Each ID is
                            // escaped via escapeHogqlString.
                            const idList = safe.map((s) => `'${escapeHogqlString(s.id)}'`).join(',')
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
                                      AND timestamp >= toDateTime('${fromStr}', 'UTC')
                                      AND timestamp <= toDateTime('${toStr}', 'UTC')
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
                                safe.map((s) => s.id)
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
            cache.pendingTraces?.clear?.()
        },
    })),
])

// Parse ClickHouse-truncated JSON: strict parse, then partial-JSON recovery,
// then raw string so the normalizer can still show something.
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
        try {
            return parsePartialJSON(value)
        } catch {
            return value
        }
    }
}
