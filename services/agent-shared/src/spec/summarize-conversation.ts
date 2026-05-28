/**
 * Cheap session summary helpers. Used by the janitor's /sessions list view to
 * give callers (Django, MCP, debug UIs) a useful glance without paying for the
 * full conversation transcript.
 */

import { ConversationMessage } from './spec'

export interface ConversationUsageTotal {
    tokens_in: number
    tokens_out: number
    cost_input: number
    cost_output: number
    cost_total: number
}

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
 */
export function totalConversationUsage(conversation: ConversationMessage[]): ConversationUsageTotal {
    const out: ConversationUsageTotal = {
        tokens_in: 0,
        tokens_out: 0,
        cost_input: 0,
        cost_output: 0,
        cost_total: 0,
    }
    for (const m of conversation) {
        if (m.role !== 'assistant' || !m.usage) {
            continue
        }
        out.tokens_in += m.usage.input ?? 0
        out.tokens_out += m.usage.output ?? 0
        out.cost_input += m.usage.cost?.input ?? 0
        out.cost_output += m.usage.cost?.output ?? 0
        out.cost_total += m.usage.cost?.total ?? 0
    }
    return out
}
