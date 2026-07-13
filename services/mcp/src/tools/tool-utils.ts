import type { Context } from '@/tools/types'

/**
 * Adds a _posthogUrl field to a result. For object results it's a sibling field; for raw
 * array results the array is wrapped as `{ results, _posthogUrl }` — spreading an array into
 * an object (`{ ...arr }`) would otherwise corrupt it into `{ 0: …, 1: …, _posthogUrl: … }`.
 */
export type WithPostHogUrl<T = unknown> = T extends readonly (infer U)[]
    ? { results: U[]; _posthogUrl: string }
    : T & { _posthogUrl: string }

/** Adds _posthogUrl to a result. Wraps raw arrays in `{ results, _posthogUrl }` (see type above). */
export async function withPostHogUrl<T>(context: Context, result: T, path: string): Promise<WithPostHogUrl<T>> {
    const projectId = await context.stateManager.getProjectId()

    const baseUrl = context.api.getProjectBaseUrl(projectId)
    const fullUrl = `${baseUrl}${path}`

    if (Array.isArray(result)) {
        return { results: result, _posthogUrl: fullUrl } as unknown as WithPostHogUrl<T>
    }

    return { ...result, _posthogUrl: fullUrl } as WithPostHogUrl<T>
}

/**
 * Adds an `_agentNote` field carrying brief point-of-use guidance for the calling agent
 * (configured per tool via `agent_note` in the YAML definition). For raw array results the
 * array is wrapped as `{ results, _agentNote }`, mirroring `withPostHogUrl`.
 */
export type WithAgentNote<T = unknown> = T extends readonly (infer U)[]
    ? { results: U[]; _agentNote: string }
    : T & { _agentNote: string }

/** Adds `_agentNote` to a result. Wraps raw arrays in `{ results, _agentNote }` (see type above). */
export function withAgentNote<T>(result: T, note: string): WithAgentNote<T> {
    if (Array.isArray(result)) {
        return { results: result, _agentNote: note } as unknown as WithAgentNote<T>
    }
    return { ...result, _agentNote: note } as WithAgentNote<T>
}

/**
 * Pick only fields matching the given dot-path patterns.
 * Supports wildcards: `'groups.*.key'` iterates all array items / object keys.
 */
export function pickResponseFields<T>(obj: T, paths: string[]): Partial<T> {
    const result: Record<string, unknown> = {}
    for (const p of paths) {
        copyAtPath(obj, result, p.split('.'))
    }
    return result as Partial<T>
}

function copyAtPath(source: unknown, target: Record<string, unknown>, segments: string[]): void {
    if (source === null || source === undefined || typeof source !== 'object') {
        return
    }
    const [head, ...rest] = segments
    if (!head) {
        return
    }
    if (head === '*') {
        const src = source as Record<string, unknown>
        if (Array.isArray(source)) {
            const arr = target as unknown as unknown[]
            for (let i = 0; i < source.length; i++) {
                if (arr[i] === undefined) {
                    arr[i] = {}
                }
                if (rest.length === 0) {
                    arr[i] = structuredClone(source[i])
                } else {
                    copyAtPath(source[i], arr[i] as Record<string, unknown>, rest)
                }
            }
        } else {
            for (const key of Object.keys(src)) {
                if (target[key] === undefined) {
                    target[key] = {}
                }
                if (rest.length === 0) {
                    target[key] = structuredClone(src[key])
                } else {
                    copyAtPath(src[key], target[key] as Record<string, unknown>, rest)
                }
            }
        }
        return
    }
    const src = (source as Record<string, unknown>)[head]
    if (src === undefined) {
        return
    }
    if (rest.length === 0) {
        target[head] = structuredClone(src)
    } else {
        if (src === null || typeof src !== 'object') {
            return
        }
        if (target[head] === undefined) {
            target[head] = Array.isArray(src) ? [] : {}
        }
        copyAtPath(src, target[head] as Record<string, unknown>, rest)
    }
}

/**
 * Remove fields matching the given dot-path patterns.
 * Supports wildcards: `'groups.*.properties'` iterates all array items / object keys.
 */
export function omitResponseFields<T>(obj: T, paths: string[]): Partial<T> {
    const result = structuredClone(obj)
    for (const p of paths) {
        removeAtPath(result, p.split('.'))
    }
    return result as Partial<T>
}

function removeAtPath(obj: unknown, segments: string[]): void {
    if (obj === null || obj === undefined || typeof obj !== 'object') {
        return
    }
    const [head, ...rest] = segments
    if (!head) {
        return
    }
    if (head === '*') {
        const items = Array.isArray(obj) ? obj : Object.values(obj)
        for (const item of items) {
            if (rest.length === 0) {
                // Wildcard at leaf makes no sense for omit — skip
            } else {
                removeAtPath(item, rest)
            }
        }
        return
    }
    const record = obj as Record<string, unknown>
    if (rest.length === 0) {
        delete record[head]
    } else {
        removeAtPath(record[head], rest)
    }
}

// --- LLM trace response truncation ---------------------------------------------------------------
//
// A single LLM/agent trace can serialize to millions of tokens: every generation carries the full
// prompt (`$ai_input`), completion (`$ai_output` / `$ai_output_choices`), span state, tool
// definitions, and — for embeddings — large numeric vectors, and a trace can contain thousands of
// events. Returned verbatim to a calling agent, that overflows the context window. These caps bound
// the response along all three axes (per-field size, total content size, event count) while keeping
// the tree structure and every event's lightweight metadata (ids, model, tokens, costs, latency)
// intact. The full, untruncated trace remains available in the PostHog UI via `_posthogUrl`.

/** Event properties that carry unbounded content and must be capped. */
const TRACE_HEAVY_PROPS = [
    '$ai_input',
    '$ai_output',
    '$ai_output_choices',
    '$ai_input_state',
    '$ai_output_state',
    '$ai_tools',
] as const

/** Max events returned per trace; excess (chronologically latest) events are dropped. */
export const TRACE_MAX_EVENTS = 250
/** Max characters kept for a single heavy field (before the global budget also applies). */
export const TRACE_MAX_FIELD_CHARS = 20_000
/** Global budget (characters) for heavy content across the whole response, ~tens of thousands of tokens. */
export const TRACE_MAX_TOTAL_HEAVY_CHARS = 120_000

const TRACE_FULL_CONTENT_HINT = 'open the full trace in PostHog via `_posthogUrl`'

function isRecord(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function safeStringify(value: unknown): string {
    try {
        return typeof value === 'string' ? value : (JSON.stringify(value) ?? '')
    } catch {
        return ''
    }
}

export interface TraceTruncationSummary {
    truncated: boolean
    /** Number of trace events dropped because the trace exceeded `TRACE_MAX_EVENTS`. */
    omittedEvents: number
}

/**
 * Truncate an LLM trace query response in place so it stays within an agent-consumable size.
 * `results` is the `TraceQueryResponse.results` array (`LLMTrace[]`); non-array or non-trace input
 * is a no-op. Typical (small) traces are returned untouched — only the bloated tail is capped.
 */
export function truncateTraceContent(results: unknown): TraceTruncationSummary {
    const summary: TraceTruncationSummary = { truncated: false, omittedEvents: 0 }
    if (!Array.isArray(results)) {
        return summary
    }

    let heavyBudget = TRACE_MAX_TOTAL_HEAVY_CHARS

    const capField = (container: Record<string, unknown>, key: string): void => {
        const value = container[key]
        if (value === undefined || value === null) {
            return
        }
        if (heavyBudget <= 0) {
            container[key] = `[omitted — response size limit reached; ${TRACE_FULL_CONTENT_HINT}]`
            summary.truncated = true
            return
        }
        const serialized = safeStringify(value)
        const keep = Math.min(TRACE_MAX_FIELD_CHARS, heavyBudget)
        if (serialized.length <= keep) {
            heavyBudget -= serialized.length
            return
        }
        container[key] =
            `${serialized.slice(0, keep)}… [truncated ${serialized.length - keep} chars — ${TRACE_FULL_CONTENT_HINT}]`
        heavyBudget -= keep
        summary.truncated = true
    }

    for (const trace of results) {
        if (!isRecord(trace)) {
            continue
        }
        capField(trace, 'inputState')
        capField(trace, 'outputState')

        const events = trace.events
        if (!Array.isArray(events)) {
            continue
        }
        if (events.length > TRACE_MAX_EVENTS) {
            summary.omittedEvents += events.length - TRACE_MAX_EVENTS
            trace.events = events.slice(0, TRACE_MAX_EVENTS)
            summary.truncated = true
        }
        for (const event of trace.events as unknown[]) {
            if (!isRecord(event) || !isRecord(event.properties)) {
                continue
            }
            for (const prop of TRACE_HEAVY_PROPS) {
                if (prop in event.properties) {
                    capField(event.properties, prop)
                }
            }
        }
    }

    return summary
}
