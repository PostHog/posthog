import type { ResolvedState } from '@/hono/request-state-resolver'
import { AnalyticsEvent, buildMCPAnalyticsGroups } from '@/lib/posthog/analytics'
import { type EvaluatedFlags, evaluateFeatureFlags } from '@/lib/posthog/flags'
import type { CachedAgentNotice } from '@/tools/types'

const RESOLVE_TIMEOUT_MS = 1500

type ContentItem = { type: string; text?: string }

function hasInjectableContent(payload: unknown): payload is { content: ContentItem[]; isError?: boolean } {
    return (
        typeof payload === 'object' &&
        payload !== null &&
        Array.isArray((payload as { content?: unknown }).content) &&
        (payload as { isError?: boolean }).isError !== true
    )
}

async function resolvePendingNotices(
    state: ResolvedState,
    delivered: string[]
): Promise<CachedAgentNotice[] | undefined> {
    const notices = await state.context.stateManager.getCachedOrFetchAgentNotices()
    if (!notices?.length) {
        return undefined
    }

    // Re-check expiry here: the token cache holds notices for up to 10 minutes.
    const now = Date.now()
    const pending = notices.filter((n) => !delivered.includes(n.id) && Date.parse(n.expires_at) > now)

    const gatedKeys = [...new Set(pending.map((n) => n.feature_flag_key).filter((k): k is string => !!k))]
    if (!gatedKeys.length) {
        return pending
    }

    // Flag-gated notices are targeting: a flag's person/group conditions decide
    // who receives the notice. Evaluated like tool flags (org + project groups).
    // Fail closed for gated notices only — ungated ones still deliver.
    let flags: EvaluatedFlags = {}
    try {
        const analyticsContext = await state.reqCtx.getAnalyticsContextSafe(state.context)
        const groups = analyticsContext ? buildMCPAnalyticsGroups(analyticsContext) : undefined
        flags = await evaluateFeatureFlags(gatedKeys, state.distinctId, groups)
    } catch {
        flags = {}
    }
    return pending.filter((n) => !n.feature_flag_key || flags[n.feature_flag_key] === true)
}

/**
 * Appends pending agent notices (staff-authored, org- or flag-targeted messages) to
 * a tool result, at most once per notice per MCP session. Strictly fail-open: any
 * error or slow resolution returns the payload unchanged, and undelivered notices
 * retry on the next successful tool call.
 */
export async function maybeInjectAgentNotice(
    payload: unknown,
    state: ResolvedState,
    toolName: string
): Promise<unknown> {
    try {
        if (!state.agentNoticesEnabled || !state.requestContext.mcpSessionId || !hasInjectableContent(payload)) {
            return payload
        }

        const delivered = (await state.reqCtx.sessionCache.get('agentNoticesDelivered')) ?? []

        const pending = await Promise.race([
            resolvePendingNotices(state, delivered),
            new Promise<undefined>((resolve) => setTimeout(() => resolve(undefined), RESOLVE_TIMEOUT_MS)),
        ])
        if (!pending?.length) {
            return payload
        }

        // Re-read and record delivery before touching the payload: overlapping tool
        // calls race on the first read, and the slow notice fetch sits between read
        // and write. Re-checking here shrinks that window to adjacent cache ops —
        // a duplicate on a true tie is harmless and RedisCache has no atomic CAS.
        const deliveredNow = (await state.reqCtx.sessionCache.get('agentNoticesDelivered')) ?? []
        const toDeliver = pending.filter((n) => !deliveredNow.includes(n.id))
        if (!toDeliver.length) {
            return payload
        }
        await state.reqCtx.sessionCache.set('agentNoticesDelivered', [...deliveredNow, ...toDeliver.map((n) => n.id)])

        const messages = toDeliver.map((n) => n.message).join('\n---\n')
        const text = `<posthog-notice>\nNotice from PostHog — surface this to the user:\n${messages}\n</posthog-notice>`
        payload.content.push({ type: 'text', text })

        void state.context.trackEvent(AnalyticsEvent.MCP_AGENT_NOTICE_DELIVERED, {
            notice_ids: toDeliver.map((n) => n.id),
            tool_name: toolName,
        })

        return payload
    } catch {
        return payload
    }
}
