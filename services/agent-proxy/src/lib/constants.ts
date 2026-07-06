// Wire-protocol constants for the agent-proxy Redis stream plane.
//
// Every value here must stay byte-identical to the Python implementation in
// products/tasks/backend/stream/redis_stream.py and
// products/tasks/backend/services/sandbox_config.py — Django and this Node
// service share the SAME Redis stream during the cutover window.

// SANDBOX_TTL_SECONDS from sandbox_config.py (production value only; the TEST
// branch short-circuits to 15 min but Node never runs in Django TEST mode).
export const STREAM_TTL_SECONDS = 6 * 60 * 60 // 21600

// TTL for last-seq and completed keys = SANDBOX_TTL_SECONDS + 1 hour buffer
// (mirrors SANDBOX_EVENT_INGEST_TOKEN_TTL in connection_token.py).
export const SEQUENCE_TTL_SECONDS = STREAM_TTL_SECONDS + 3600 // 25200

// Redis XADD MAXLEN ~ (approximate trim, not exact).
export const STREAM_MAX_LENGTH = 20_000

// XREAD tuning
export const READ_COUNT = 16
export const BLOCK_MS = 100

// wait_for_stream linear backoff (mirrors Python constants, converted to ms)
export const WAIT_INITIAL_DELAY_MS = 50
export const WAIT_DELAY_INCREMENT_MS = 150
export const WAIT_MAX_DELAY_MS = 2_000
export const WAIT_TIMEOUT_MS = 300_000

// Idle threshold before emitting a keepalive SSE event
export const KEEPALIVE_INTERVAL_MS = 20_000

// Redis SET NX EX throttle window for the Temporal heartbeat callback (seconds)
export const HEARTBEAT_THROTTLE_SECONDS = 30

// Redis key prefix (byte-identical to TASK_RUN_STREAM_PREFIX in Python)
export const STREAM_PREFIX = 'task-run-stream:'

// Redis key builder functions (byte-identical to Python get_task_run_stream_*_key)

export function getStreamKey(runId: string): string {
    return `${STREAM_PREFIX}${runId}`
}

export function getSequenceKey(streamKey: string): string {
    return `${streamKey}:last-seq`
}

export function getCompletedKey(streamKey: string): string {
    return `${streamKey}:completed`
}

export function getAgentActiveKey(streamKey: string): string {
    return `${streamKey}:ingest-agent-active`
}

export function getHeartbeatKey(streamKey: string): string {
    return `${streamKey}:ingest-heartbeat`
}

// Sentinel factory helpers (values must match Python's json.dumps output)

export function makeCompleteSentinel(): Record<string, string> {
    return { type: 'STREAM_STATUS', status: 'complete' }
}

export function makeErrorSentinel(error: string): Record<string, string> {
    return { type: 'STREAM_STATUS', status: 'error', error: error.slice(0, 500) }
}

// Control type used in the NDJSON completion line from the sandbox ingest client
export const STREAM_COMPLETE_CONTROL_TYPE = '_posthog/stream_complete'

// NDJSON ingest byte limits (byte-identical to Python event_ingest.py)
export const MAX_EVENT_LINE_BYTES = 1_000_000
export const MAX_REQUEST_BYTES = 5_000_000
export const MAX_EVENTS_PER_REQUEST = 1_000

// CORS headers (must match the Python ASGI middleware values exactly)
export const CORS_ALLOW_METHODS = 'GET, POST, OPTIONS'
export const CORS_ALLOW_HEADERS =
    'authorization, last-event-id, content-type, accept, x-csrftoken, x-posthog-distinct-id, x-posthog-session-id'
export const CORS_MAX_AGE = '600'

// JWT audience strings (must match Python validate_* helpers)
export const STREAM_READ_AUDIENCE = 'posthog:stream_read'
export const SANDBOX_EVENT_INGEST_AUDIENCE = 'posthog:sandbox_event_ingest'

// SSE event names (keepalive and terminal events carry a named "event:" line;
// normal stream events do not — they carry only "id:" and "data:").
export const SSE_EVENT_KEEPALIVE = 'keepalive'
export const SSE_EVENT_STREAM_END = 'stream-end'
export const SSE_EVENT_ERROR = 'error'

// SSE payload shapes (byte-identical to Python format_sse_event call sites)
export const SSE_PAYLOAD_KEEPALIVE: Record<string, string> = { type: 'keepalive' }
export const SSE_PAYLOAD_STREAM_END: Record<string, string> = { status: 'complete' }

export function makeSseErrorPayload(error: string): Record<string, string> {
    return { error }
}
