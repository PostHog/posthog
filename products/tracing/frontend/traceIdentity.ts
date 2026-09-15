// Resolve the person and session a whole trace belongs to, so the drawer can answer "who was
// this?" in its header instead of leaving the answer in a span's attribute table.

// The per-span precedence and the convention key lists are shared with Logs, because both
// products resolve the same SDK-emitted attribute keys (posthogDistinctId, sessionId, ...).
import { getDistinctIdWithKey, getSessionIdWithKey } from 'products/logs/frontend/utils'

import type { Span } from './types'

export interface TraceIdentity {
    readonly distinctId: string | null
    readonly sessionId: string | null
}

// One shared instance, so a caller that resolves nothing does not invalidate its consumers.
export const EMPTY_TRACE_IDENTITY: TraceIdentity = { distinctId: null, sessionId: null }

type IdentityResolver = typeof getDistinctIdWithKey

function singleValueAcrossSpans(
    spans: Span[],
    resolve: IdentityResolver,
    configuredKeys: string[] | undefined
): string | null {
    let resolved: string | null = null

    for (const span of spans) {
        const value = resolve(span.attributes, span.resource_attributes, configuredKeys)?.value
        if (!value) {
            continue
        }
        if (resolved !== null && resolved !== value) {
            // A trace that touches more than one identity, which a batch consumer working
            // through several users' items does. Promoting either value would state a fact the
            // trace does not support, so the span attribute table stays the only place it appears.
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
    if (spans.length === 0) {
        return EMPTY_TRACE_IDENTITY
    }
    return {
        distinctId: singleValueAcrossSpans(spans, getDistinctIdWithKey, configuredDistinctIdKeys),
        sessionId: singleValueAcrossSpans(spans, getSessionIdWithKey, configuredSessionIdKeys),
    }
}
