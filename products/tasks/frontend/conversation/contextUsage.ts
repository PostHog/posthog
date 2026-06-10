/**
 * Context-window usage and session resource helpers.
 *
 * Ported from apps/code/src/renderer/features/sessions/hooks/useContextUsage.ts
 * and components/accumulateSessionResources.ts. Pure and dependency-free
 * (no React) so they stay cheap units to test; components re-derive per render.
 */
import { type AcpMessage, isJsonRpcNotification, type JsonRpcMessage } from './acp-types'
import { isNotification, POSTHOG_NOTIFICATIONS } from './lib/acpExtensions'

export { CONTEXT_CATEGORIES, formatTokensCompact, getOverallUsageColor } from './lib/contextColors'
export type { CategoryStyle, ContextCategoryKey } from './lib/contextColors'

export interface ContextBreakdown {
    systemPrompt: number
    tools: number
    rules: number
    skills: number
    mcp: number
    subagents: number
    conversation: number
}

export interface ContextUsage {
    used: number
    size: number
    percentage: number
    cost: { amount: number; currency: string } | null
    breakdown: ContextBreakdown | null
}

export interface ResourceProduct {
    /** Product identifier from the agent (e.g. `feature_flags`); kept open since new ids can arrive before the UI knows them. */
    id: string
    label: string
}

/**
 * Extract the latest context window usage from session events. Scans backwards
 * for the most recent `usage_update` aggregate and `_posthog/usage_update`
 * breakdown, so it stays cheap even on long transcripts.
 */
export function deriveContextUsage(events: AcpMessage[]): ContextUsage | null {
    let aggregate: Omit<ContextUsage, 'breakdown'> | null = null
    let breakdown: ContextBreakdown | null = null

    for (let i = events.length - 1; i >= 0; i--) {
        const msg = events[i].message
        if (!aggregate) {
            aggregate = extractAggregate(msg)
        }
        if (!breakdown) {
            breakdown = extractBreakdown(msg)
        }
        if (aggregate && breakdown) {
            break
        }
    }

    if (!aggregate) {
        return null
    }
    return { ...aggregate, breakdown }
}

function extractAggregate(msg: JsonRpcMessage): Omit<ContextUsage, 'breakdown'> | null {
    if (!isJsonRpcNotification(msg) || msg.method !== 'session/update') {
        return null
    }
    const params = msg.params as
        | {
              update?: {
                  sessionUpdate?: string
                  used?: number
                  size?: number
                  cost?: { amount: number; currency: string } | null
              }
          }
        | undefined
    const update = params?.update
    if (
        update?.sessionUpdate !== 'usage_update' ||
        typeof update.used !== 'number' ||
        typeof update.size !== 'number'
    ) {
        return null
    }
    const percentage = update.size > 0 ? Math.min(100, Math.round((update.used / update.size) * 100)) : 0
    return {
        used: update.used,
        size: update.size,
        percentage,
        cost: update.cost ?? null,
    }
}

function extractBreakdown(msg: JsonRpcMessage): ContextBreakdown | null {
    if (!isJsonRpcNotification(msg)) {
        return null
    }
    // `isNotification` also matches the `__posthog/` double-prefix that
    // extNotification transports can produce.
    if (!isNotification(msg.method, POSTHOG_NOTIFICATIONS.USAGE_UPDATE)) {
        return null
    }
    const params = msg.params as { breakdown?: ContextBreakdown } | undefined
    return params?.breakdown ?? null
}

/**
 * Accumulate the de-duplicated, first-seen-ordered list of PostHog products
 * used across the whole session, from its `_posthog/resources_used`
 * notifications. Works for both live streaming and log replay, since both feed
 * the same `events` array. A product used on several turns appears once.
 */
export function accumulateSessionResources(events: AcpMessage[]): ResourceProduct[] {
    const byId = new Map<string, ResourceProduct>()
    for (const event of events) {
        const msg = event.message
        if (!isJsonRpcNotification(msg)) {
            continue
        }
        if (!isNotification(msg.method, POSTHOG_NOTIFICATIONS.RESOURCES_USED)) {
            continue
        }
        const products = (msg.params as { products?: ResourceProduct[] } | undefined)?.products
        if (!products) {
            continue
        }
        for (const product of products) {
            if (product && !byId.has(product.id)) {
                byId.set(product.id, product)
            }
        }
    }
    return [...byId.values()]
}
