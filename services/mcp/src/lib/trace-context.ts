/**
 * W3C trace context propagation helpers.
 * See: https://www.w3.org/TR/trace-context/
 *
 * Format: `<version>-<trace-id>-<parent-id>-<flags>`
 *   - version: `00`
 *   - trace-id: 16 random bytes, hex-encoded (32 chars)
 *   - parent-id: 8 random bytes, hex-encoded (16 chars)
 *   - flags: `01` = sampled, `00` = unsampled
 *
 * We do NOT export Worker-side OTLP spans today. These helpers exist solely
 * to give Django's auto-instrumented spans something to root under, so the
 * Worker→Django hop produces a linked trace tree instead of merely
 * attribute-correlated rows. When/if Worker-side OTLP export lands, the
 * span ids we emit here become real and parent-child relationships line up
 * end-to-end.
 *
 * ## Sampling
 *
 * Django is configured with `parentbased_traceidratio` and arg `0`, so
 * traces without an inbound `traceparent` are sampled at 0% — Django would
 * never record anything we don't explicitly mark as sampled. We therefore
 * make the sampling decision at the Worker edge:
 *
 *   - If the inbound request carries a `traceparent`, we propagate the
 *     caller's sampling flag faithfully (W3C-spec behaviour for
 *     intermediaries).
 *   - When we mint a fresh `traceparent`, we make a *deterministic*
 *     sampling decision keyed (in order) on `mcp-conversation-id` →
 *     `mcp-session-id` → the freshly-minted trace id. Same conversation /
 *     session → same verdict, so all tool calls in one agent run are
 *     either traced together or dropped together. The fallback to trace id
 *     matches OTel's built-in `traceidratio` sampler.
 */

const TRACE_VERSION = '00'
const TRACE_FLAGS_SAMPLED = '01'
const TRACE_FLAGS_UNSAMPLED = '00'
const TRACE_ID_BYTES = 16
const SPAN_ID_BYTES = 8

/**
 * Default per-trace sample rate when minting at the Worker edge. Picked
 * conservatively while we measure the Django-side OTLP volume impact; raise
 * once we have signal that the volume is sustainable.
 */
const DEFAULT_TRACE_SAMPLE_RATIO = 0.1

function randomHex(byteCount: number): string {
    const bytes = crypto.getRandomValues(new Uint8Array(byteCount))
    let hex = ''
    for (const b of bytes) {
        hex += b.toString(16).padStart(2, '0')
    }
    return hex
}

/**
 * Deterministic ratio decision keyed on `key`. Takes the first 8 hex chars
 * of the key as a u32 and compares to `ratio * 0xffffffff`. Same key → same
 * verdict. Returns `false` (fail-safe) if the slice isn't hex.
 */
function sampleByKey(key: string, ratio: number): boolean {
    const slice = key.slice(0, 8)
    const value = parseInt(slice, 16)
    if (Number.isNaN(value)) {
        return false
    }
    return value / 0xffffffff < ratio
}

/**
 * Decide whether a freshly-minted trace should be sampled.
 *
 * Preference order: conversation id → session id → trace id. The first
 * non-empty value wins, so requests within the same agent conversation (or
 * the same transport session) share a sampling verdict and produce a
 * coherent trace tree across hops. Falling back to the trace id matches
 * OTel's built-in `traceidratio` sampler when no MCP context is available.
 */
export function decideTraceSampling(opts: {
    mcpConversationId?: string | undefined
    mcpSessionId?: string | undefined
    traceId: string
    ratio?: number | undefined
}): boolean {
    const ratio = opts.ratio ?? DEFAULT_TRACE_SAMPLE_RATIO
    if (ratio >= 1) {
        return true
    }
    if (ratio <= 0) {
        return false
    }
    const key = opts.mcpConversationId || opts.mcpSessionId || opts.traceId
    return sampleByKey(key, ratio)
}

/**
 * Mint a fresh `traceparent` value with random trace id + span id. The
 * sampled flag is computed via `decideTraceSampling` using the supplied
 * MCP context.
 */
export function mintTraceparent(opts?: {
    mcpConversationId?: string | undefined
    mcpSessionId?: string | undefined
    ratio?: number
}): string {
    const traceId = randomHex(TRACE_ID_BYTES)
    const spanId = randomHex(SPAN_ID_BYTES)
    const sampled = decideTraceSampling({
        mcpConversationId: opts?.mcpConversationId,
        mcpSessionId: opts?.mcpSessionId,
        traceId,
        ratio: opts?.ratio,
    })
    const flags = sampled ? TRACE_FLAGS_SAMPLED : TRACE_FLAGS_UNSAMPLED
    return `${TRACE_VERSION}-${traceId}-${spanId}-${flags}`
}

/**
 * Build a child traceparent: reuse the trace id of `parent`, mint a fresh
 * span id, and *preserve the parent's flags byte* so intermediaries don't
 * silently override the original tracer's sampling decision (W3C §3.2.2.5).
 * Returns `parent` unchanged if it doesn't parse — we'd rather forward an
 * opaque value than drop trace continuity.
 */
export function childTraceparent(parent: string): string {
    const parts = parent.split('-')
    if (
        parts.length !== 4 ||
        parts[0] !== TRACE_VERSION ||
        parts[1]?.length !== 32 ||
        parts[2]?.length !== 16 ||
        parts[3]?.length !== 2
    ) {
        return parent
    }
    return `${TRACE_VERSION}-${parts[1]}-${randomHex(SPAN_ID_BYTES)}-${parts[3]}`
}
