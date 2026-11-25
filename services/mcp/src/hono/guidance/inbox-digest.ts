import { createHash } from 'node:crypto'
import { z } from 'zod'

import { formatPrompt } from '@/lib/utils'
import DIGEST_PROMPT from '@/templates/guidance/inbox-digest.md'

import type { RedisLike } from '../cache/RedisCache'
import type { ResolvedState } from '../request-state-resolver'
import type { GuidanceCall, GuidanceNotice } from './engine'
import type { GuidanceProductState } from './product-state'
import { MCP_GUIDANCE_INBOX_DIGEST_FLAG } from './rules'
import { callerCacheIdentity, isSelfDrivingAudience } from './self-driving-activation'

const RULE_ID = 'inbox-digest'
const DIGEST_TOOL = 'inbox-digest-get'
const SHOWN_TTL_SECONDS = 12 * 60 * 60
const QUIET_TTL_SECONDS = 60 * 60
// Long enough for an answer that arrived after the lookup budget to reach the next call, short enough to stay current.
const PENDING_TTL_SECONDS = 5 * 60

const digestSchema = z.object({
    needs_you: z.object({ count: z.number().int().nonnegative() }),
    new_for_you: z.object({ count: z.number().int().nonnegative() }),
})
type InboxDigest = z.infer<typeof digestSchema>
const QUIET_DIGEST: InboxDigest = { needs_you: { count: 0 }, new_for_you: { count: 0 } }

// Per person and project, not per credential or session, so a person sees the notice once per window.
function shownKey(state: ResolvedState, projectId: string): string {
    const identity = createHash('sha256')
        .update(JSON.stringify([state.context.api.config.baseUrl, projectId, state.distinctId]))
        .digest('base64url')
    return `mcp:guidance:inbox-digest:shown:{${identity}}`
}

function digestText(state: ResolvedState, digest: InboxDigest): string {
    return formatPrompt(DIGEST_PROMPT, {
        needs_you: String(digest.needs_you.count),
        new_for_you: String(digest.new_for_you.count),
        digest_call: state.useSingleExec ? `\`call ${DIGEST_TOOL} {}\`` : `the \`${DIGEST_TOOL}\` tool`,
    })
}

async function readDigest(redis: RedisLike, state: ResolvedState, projectId: string): Promise<InboxDigest> {
    const key = `mcp:guidance:inbox-digest:answer:{${callerCacheIdentity(state, projectId)}}`
    const cached = await redis.get(key)
    if (cached !== null) {
        return digestSchema.parse(JSON.parse(cached))
    }
    let digest = QUIET_DIGEST
    // A failure is remembered as a quiet answer too, because this lookup runs on every eligible tool call.
    try {
        digest = digestSchema.parse(
            await state.context.api.request<unknown>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(projectId)}/signals/inbox_digest/`,
                signal: AbortSignal.timeout(1000),
            })
        )
    } finally {
        const ttl = digest.needs_you.count > 0 ? PENDING_TTL_SECONDS : QUIET_TTL_SECONDS
        await redis.set(key, JSON.stringify(digest), 'EX', ttl)
    }
    return digest
}

async function lookupDigestNotice(
    redis: RedisLike,
    state: ResolvedState,
    call: GuidanceCall,
    productState: GuidanceProductState
): Promise<GuidanceNotice | undefined> {
    const projectId = String(await state.context.stateManager.getProjectId())
    const seenKey = shownKey(state, projectId)
    // A person whose agent read the digest already knows what the notice would say.
    if (call.toolName === DIGEST_TOOL) {
        await redis.set(seenKey, '1', 'EX', SHOWN_TTL_SECONDS)
        return undefined
    }
    if (await redis.get(seenKey)) {
        return undefined
    }
    const digest = await readDigest(redis, state, projectId)
    if (digest.needs_you.count === 0 || !productState.hasBudgetLeft()) {
        return undefined
    }
    if ((await redis.set(seenKey, '1', 'EX', SHOWN_TTL_SECONDS, 'NX')) !== 'OK') {
        return undefined
    }
    if (!productState.hasBudgetLeft()) {
        await redis.del(seenKey).catch(() => undefined)
        return undefined
    }
    return { ruleId: RULE_ID, outcome: 'shown', text: digestText(state, digest) }
}

export async function inboxDigestGuidance(
    redis: RedisLike,
    state: ResolvedState,
    call: GuidanceCall,
    productState: GuidanceProductState
): Promise<GuidanceNotice | undefined> {
    if (
        call.isError ||
        (call.toolName.startsWith('inbox-') && call.toolName !== DIGEST_TOOL) ||
        state.toolFeatureFlags?.[MCP_GUIDANCE_INBOX_DIGEST_FLAG] !== true ||
        !isSelfDrivingAudience(state) ||
        !state.allTools.some((tool) => tool.name === DIGEST_TOOL)
    ) {
        return undefined
    }
    return productState.withinBudget('inbox_digest', () => lookupDigestNotice(redis, state, call, productState))
}
