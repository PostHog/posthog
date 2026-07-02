/* eslint-disable @typescript-eslint/no-var-requires */
// The native addon is built from `src/lib.rs` and copied to `index.node` at the package root.
const native = require('../index.node')

export interface AllowListsInput {
    /** Words kept verbatim by the text scrubber (ASCII-case-insensitive). */
    text: string[]
    /** URL path segments/params kept verbatim by the URL scrubber. */
    url: string[]
}

export interface AnonymizeResult {
    /** Scrubbed `eventsByWindowId` JSON, or `null` when nothing changed (keep the original). */
    data: string | null
    /** True if an event could not be anonymized — the caller must drop the message (fail-closed). */
    failed: boolean
    /** Failure detail when `failed` is true, else `null`. */
    error: string | null
}

/** Initialize the process-wide allow lists. Call once at startup before {@link anonymize}. */
export function initAnonymizer(allow: AllowListsInput): void {
    native.initAnonymizer(JSON.stringify(allow))
}

/**
 * Anonymize a serialized `eventsByWindowId` map ({@link https://github.com/rrweb-io/rrweb rrweb} events
 * keyed by window id). CPU work runs off the Node event loop.
 */
export function anonymize(eventsJson: string): Promise<AnonymizeResult> {
    return native.anonymize(eventsJson)
}
