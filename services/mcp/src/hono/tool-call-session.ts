import type { RequestContext } from '@/hono/request-context'

/**
 * Per-session counters behind `$mcp_session_tool_call_index`, `$mcp_session_age_ms`
 * and `$mcp_schema_read_before_call`, kept as one JSON blob in the session Redis
 * cache next to the skills-first gate markers (same key scope, same 24 h TTL).
 *
 * The blob is read, updated and written back once per request. Two requests on
 * one session that interleave can drop each other's update; the counters are
 * telemetry, so an off-by-one on a concurrent session is accepted over a lock.
 */
export interface ToolCallSessionRecord {
    /** Epoch ms of the first observed request on this session. */
    startedAt: number
    /** How many `call` requests the session has made, including the current one. */
    callCount: number
    /** Tools whose schema the session read through `info` or `schema`, newest last. */
    schemaReadTools: string[]
}

/** Bounds the blob; a session that reads more schemas than this forgets the oldest. */
const MAX_SCHEMA_READ_TOOLS = 100

const SESSION_RECORD_KEY = 'toolCallSession'

export interface ToolCallObservation {
    /** The exec verb, or `call` for a direct-mode tool call. */
    verb: string | undefined
    /** The tool the verb targeted, when it named one the catalog knows. */
    targetTool: string | undefined
    /**
     * Whether the caller had to ask for the schema. In exec mode it is only
     * available through `info`/`schema`; in tools mode it arrives in the tool
     * listing, so `$mcp_schema_read_before_call` is not meaningful there.
     */
    schemaRequiresRead: boolean
}

export interface ToolCallSessionState {
    /** Records the request and returns the session properties for its event. */
    observe(observation: ToolCallObservation): Promise<Record<string, unknown>>
}

/** No session id means no session: the properties are simply absent. */
export function buildToolCallSessionState(
    reqCtx: RequestContext,
    mcpSessionId: string | undefined
): ToolCallSessionState | undefined {
    if (!mcpSessionId) {
        return undefined
    }
    const cache = reqCtx.getSessionCache(mcpSessionId)
    return {
        async observe(observation) {
            const now = Date.now()
            const previous = (await cache.get(SESSION_RECORD_KEY)) ?? {
                startedAt: now,
                callCount: 0,
                schemaReadTools: [],
            }
            const next = advance(previous, observation)
            await cache.set(SESSION_RECORD_KEY, next)
            return describe(previous, next, observation, now)
        },
    }
}

/** The record after this request. Exported for tests; the store is the only production caller. */
export function advance(record: ToolCallSessionRecord, observation: ToolCallObservation): ToolCallSessionRecord {
    const isSchemaRead = (observation.verb === 'info' || observation.verb === 'schema') && !!observation.targetTool
    const schemaReadTools =
        isSchemaRead && !record.schemaReadTools.includes(observation.targetTool!)
            ? [...record.schemaReadTools, observation.targetTool!].slice(-MAX_SCHEMA_READ_TOOLS)
            : record.schemaReadTools
    return {
        startedAt: record.startedAt,
        callCount: observation.verb === 'call' ? record.callCount + 1 : record.callCount,
        schemaReadTools,
    }
}

function describe(
    previous: ToolCallSessionRecord,
    next: ToolCallSessionRecord,
    observation: ToolCallObservation,
    now: number
): Record<string, unknown> {
    const properties: Record<string, unknown> = {
        $mcp_session_tool_call_index: next.callCount,
        $mcp_session_age_ms: Math.max(0, now - next.startedAt),
    }
    if (observation.verb === 'call' && observation.targetTool && observation.schemaRequiresRead) {
        properties.$mcp_schema_read_before_call = previous.schemaReadTools.includes(observation.targetTool)
    }
    return properties
}
