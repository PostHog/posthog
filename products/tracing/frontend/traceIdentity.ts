// Resolve the person and session a whole trace belongs to, so the drawer can answer "who was
// this?" in its header instead of leaving the answer in a span's attribute table.

// The per-span precedence and the convention key lists are shared with Logs, because both
// products resolve the same SDK-emitted attribute keys (posthogDistinctId, sessionId, ...).
import { getDistinctIdWithKey, getSessionIdWithKey, type SessionIdMatch } from 'products/logs/frontend/utils'

import type { Span } from './types'

export interface TraceIdentity {
    /** Each is null when no span carries the key, or when the spans disagree on its value. */
    distinctId: string | null
    sessionId: string | null
}

export const EMPTY_TRACE_IDENTITY: TraceIdentity = { distinctId: null, sessionId: null }

type SpanResolver = (span: Span, configuredKeys: string[] | undefined) => SessionIdMatch | null

function singleValueAcrossSpans(
    spans: Span[],
    configuredKeys: string[] | undefined,
    resolve: SpanResolver
): string | null {
    let resolved: string | null = null

    for (const span of spans) {
        const value = resolve(span, configuredKeys)?.value
        if (!value) {
            continue
        }
        if (resolved !== null && resolved !== value) {
            // The trace touches more than one identity, which a batch consumer working through
            // several users' items does. Promoting either value to the header would state a fact
            // the trace does not support, so the header shows nothing and the span attribute
            // table stays the only place the values appear.
            return null
        }
        resolved = value
    }
    return resolved
}

export function resolveTraceIdentity(
    spans: Span[],
    configuredDistinctIdKeys: string[] | undefined,
    configuredSessionIdKeys: string[] | undefined
): TraceIdentity {
    return {
        distinctId: singleValueAcrossSpans(spans, configuredDistinctIdKeys, (span, keys) =>
            getDistinctIdWithKey(span.attributes, span.resource_attributes, keys)
        ),
        sessionId: singleValueAcrossSpans(spans, configuredSessionIdKeys, (span, keys) =>
            getSessionIdWithKey(span.attributes, span.resource_attributes, keys)
        ),
    }
}
