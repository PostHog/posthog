/**
 * Cheap session summary helpers. Used by the janitor's /sessions list view to
 * give callers (Django, MCP, debug UIs) a useful glance without paying for the
 * full conversation transcript.
 */

import { AssistantMessageRecord, ConversationMessage, EMPTY_USAGE_TOTAL, SessionUsageTotal } from './spec'

/** @deprecated Use SessionUsageTotal — the 9-field shape persisted on agent_session. */
export type ConversationUsageTotal = SessionUsageTotal

const PREVIEW_MAX = 120

/**
 * Last assistant text block, trimmed to ~120 chars with a trailing "…" when
 * truncated. Returns null when no assistant message has surfaced yet (e.g. the
 * session is still in `queued` or hasn't produced text).
 */
export function lastAssistantTextPreview(
    conversation: ConversationMessage[],
    max: number = PREVIEW_MAX
): string | null {
    for (let i = conversation.length - 1; i >= 0; i--) {
        const m = conversation[i]
        if (m.role !== 'assistant') {
            continue
        }
        const textBlock = m.content.find((c) => c.type === 'text')
        if (!textBlock || typeof textBlock.text !== 'string') {
            continue
        }
        const collapsed = textBlock.text.replace(/\s+/g, ' ').trim()
        return collapsed.length > max ? `${collapsed.slice(0, max - 1)}…` : collapsed
    }
    return null
}

/**
 * Aggregate token + cost numbers across every assistant message in the
 * conversation. Returns all-zeroes when no assistant has run yet (or when the
 * model didn't report usage — e.g. faux providers in tests).
 *
 * Same shape the runner persists into `agent_session.usage_total` — use this
 * helper for backfill and ad-hoc derivation, but read off the column for
 * live sessions.
 */
export function totalConversationUsage(conversation: ConversationMessage[]): SessionUsageTotal {
    let out: SessionUsageTotal = { ...EMPTY_USAGE_TOTAL }
    for (const m of conversation) {
        if (m.role !== 'assistant' || !m.usage) {
            continue
        }
        out = accumulateUsage(out, m)
    }
    return out
}

/**
 * Fold one assistant message's `usage` into a running total. Used by both
 * the runner's per-turn accumulator and the backfill walk.
 *
 * `useGatewayCost: true` means the model went through PostHog's
 * llm-gateway — pi-ai's cost fields in that path are unreliable estimates,
 * so we keep token counts but zero the cost contribution. The gateway is
 * the source of truth for cost on that path; a future revision pulls our
 * own price-table calc in here.
 */
export function accumulateUsage(
    prev: SessionUsageTotal,
    msg: AssistantMessageRecord,
    opts: { useGatewayCost?: boolean } = {}
): SessionUsageTotal {
    const usage = msg.usage
    if (!usage) {
        return prev
    }
    const trustCost = !opts.useGatewayCost
    return {
        tokens_in: prev.tokens_in + (usage.input ?? 0),
        tokens_out: prev.tokens_out + (usage.output ?? 0),
        cache_read: prev.cache_read + (usage.cacheRead ?? 0),
        cache_write: prev.cache_write + (usage.cacheWrite ?? 0),
        cost_input: prev.cost_input + (trustCost ? (usage.cost?.input ?? 0) : 0),
        cost_output: prev.cost_output + (trustCost ? (usage.cost?.output ?? 0) : 0),
        cost_cache_read: prev.cost_cache_read + (trustCost ? (usage.cost?.cacheRead ?? 0) : 0),
        cost_cache_write: prev.cost_cache_write + (trustCost ? (usage.cost?.cacheWrite ?? 0) : 0),
        cost_total: prev.cost_total + (trustCost ? (usage.cost?.total ?? 0) : 0),
    }
}
