// Resolve the person and session a whole trace belongs to, so the drawer can answer "who was
// this?" in its header instead of leaving the answer in a span's attribute table.

// The key-matching helpers and their convention lists are shared with Logs, because both products
// resolve the same SDK-emitted attribute keys (posthogDistinctId, sessionId, ...).
import { isDistinctIdKey, isSessionIdKey } from 'products/logs/frontend/utils'

import type { Span } from './types'

export interface TraceIdentity {
    /** Null when no loaded span carries a distinct-id key, or when the loaded spans disagree. */
    distinctId: string | null
    /** Null when no loaded span carries a session-id key, or when the loaded spans disagree. */
    sessionId: string | null
}

// Precedence mirrors Logs' getSessionIdWithKey so a value resolves to the same identity in both
// products: the team's configured keys first in list order, then the built-in conventions, and
// within each pass span attributes before resource attributes.
function resolveSpanValue(
    span: Span,
    configuredKeys: string[] | undefined,
    matchesConventionKey: (key: string) => boolean
): string | null {
    const attributes = span.attributes ?? {}
    const resourceAttributes = span.resource_attributes ?? {}

    for (const key of configuredKeys ?? []) {
        if (attributes[key]) {
            return attributes[key]
        }
        if (resourceAttributes[key]) {
            return resourceAttributes[key]
        }
    }
    for (const [key, value] of Object.entries(attributes)) {
        if (value && matchesConventionKey(key)) {
            return value
        }
    }
    for (const [key, value] of Object.entries(resourceAttributes)) {
        if (value && matchesConventionKey(key)) {
            return value
        }
    }
    return null
}

function singleValueAcrossSpans(
    spans: Span[],
    configuredKeys: string[] | undefined,
    matchesConventionKey: (key: string) => boolean
): string | null {
    let resolved: string | null = null

    for (const span of spans) {
        const value = resolveSpanValue(span, configuredKeys, matchesConventionKey)
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
        distinctId: singleValueAcrossSpans(spans, configuredDistinctIdKeys, isDistinctIdKey),
        sessionId: singleValueAcrossSpans(spans, configuredSessionIdKeys, isSessionIdKey),
    }
}
