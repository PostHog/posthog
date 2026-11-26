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
const LIST_TOOL = 'inbox-reports-list'
const FOR_YOU_VIEW = 'for_you'
const SHOWN_TTL_SECONDS = 12 * 60 * 60
const QUIET_TTL_SECONDS = 60 * 60
// Long enough for an answer that arrived after the lookup budget to reach the next call, short enough to stay current.
const PENDING_TTL_SECONDS = 5 * 60

const countSchema = z.object({ count: z.number().int().nonnegative() })

function readsOwnInbox(call: GuidanceCall): boolean {
    return call.toolName === LIST_TOOL && call.args?.view === FOR_YOU_VIEW
}

// Per person and project, not per credential or session, so a person sees the notice once per window.
function shownKey(state: ResolvedState, projectId: string): string {
    const identity = createHash('sha256')
        .update(JSON.stringify([state.context.api.config.baseUrl, projectId, state.distinctId]))
        .digest('base64url')
    return `mcp:guidance:inbox-digest:shown:{${identity}}`
}

function digestText(state: ResolvedState, count: number): string {
    const input = JSON.stringify({ view: FOR_YOU_VIEW })
    return formatPrompt(DIGEST_PROMPT, {
        count: String(count),
        list_call: state.useSingleExec
            ? `\`call ${LIST_TOOL} ${input}\``
            : `the \`${LIST_TOOL}\` tool and \`${input}\``,
    })
}

async function readCount(redis: RedisLike, state: ResolvedState, projectId: string): Promise<number> {
    const key = `mcp:guidance:inbox-digest:answer:{${callerCacheIdentity(state, projectId)}}`
    const cached = await redis.get(key)
    if (cached !== null) {
        return countSchema.parse(JSON.parse(cached)).count
    }
    let count = 0
    // A failure is remembered as a quiet answer too, because this lookup runs on every eligible tool call.
    try {
        count = countSchema.parse(
            await state.context.api.request<unknown>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(projectId)}/signals/reports/`,
                query: { view: FOR_YOU_VIEW, count_only: true },
                signal: AbortSignal.timeout(1000),
            })
        ).count
    } finally {
        await redis.set(key, JSON.stringify({ count }), 'EX', count > 0 ? PENDING_TTL_SECONDS : QUIET_TTL_SECONDS)
    }
    return count
}

async function lookupDigestNotice(
    redis: RedisLike,
    state: ResolvedState,
    call: GuidanceCall,
    productState: GuidanceProductState
): Promise<GuidanceNotice | undefined> {
    const projectId = String(await state.context.stateManager.getProjectId())
    const seenKey = shownKey(state, projectId)
    // A person whose agent read their own inbox already knows what the notice would say.
    if (readsOwnInbox(call)) {
        await redis.set(seenKey, '1', 'EX', SHOWN_TTL_SECONDS)
        return undefined
    }
    if (await redis.get(seenKey)) {
        return undefined
    }
    const count = await readCount(redis, state, projectId)
    if (count === 0 || !productState.hasBudgetLeft()) {
        return undefined
    }
    if ((await redis.set(seenKey, '1', 'EX', SHOWN_TTL_SECONDS, 'NX')) !== 'OK') {
        return undefined
    }
    if (!productState.hasBudgetLeft()) {
        await redis.del(seenKey).catch(() => undefined)
        return undefined
    }
    return { ruleId: RULE_ID, outcome: 'shown', text: digestText(state, count) }
}

export async function inboxDigestGuidance(
    redis: RedisLike,
    state: ResolvedState,
    call: GuidanceCall,
    productState: GuidanceProductState
): Promise<GuidanceNotice | undefined> {
    if (
        call.isError ||
        (call.toolName.startsWith('inbox-') && !readsOwnInbox(call)) ||
        state.toolFeatureFlags?.[MCP_GUIDANCE_INBOX_DIGEST_FLAG] !== true ||
        !isSelfDrivingAudience(state) ||
        !state.allTools.some((tool) => tool.name === LIST_TOOL)
    ) {
        return undefined
    }
    return productState.withinBudget('inbox_digest', () => lookupDigestNotice(redis, state, call, productState))
}
