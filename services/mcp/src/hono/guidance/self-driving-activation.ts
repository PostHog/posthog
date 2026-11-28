import { createHash } from 'node:crypto'
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { isCustomerAgentCaller } from '@/lib/event-source'
import { resolveScopePreset } from '@/lib/scope-preset'
import { formatPrompt } from '@/lib/utils'
import ACTIVATION_PROMPT from '@/templates/guidance/self-driving-activation.md'
import type { Context } from '@/tools/types'

import type { RedisLike } from '../cache/RedisCache'
import type { ResolvedState } from '../request-state-resolver'
import type { GuidanceCall, GuidanceNotice } from './engine'
import type { GuidanceProductState } from './product-state'
import { MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG } from './rules'

const RULE_ID = 'error-tracking-sd-activation'
const SESSION_TTL_SECONDS = 24 * 60 * 60
const CALLER_TTL_SECONDS = 30 * 60
const INELIGIBLE_TTL_SECONDS = 30
const REQUIRED_TOOLS = [
    'self-driving-status-get',
    'inbox-reports-list',
    'inbox-reports-retrieve',
    'inbox-report-artefacts-list',
]
const SETUP_NOT_STARTED: Schemas.InboxSetupStateEnum = 'not_started'
const inboxStatusSchema = z.object({ setup_state: z.string() })

/**
 * Reads the inbox status rather than onboarding progress, because a project can watch through an enabled source, a scout or a replay scanner without ever completing onboarding.
 * Undefined when the response does not parse. A failed request throws.
 */
export async function fetchSelfDrivingSetupNotStarted(
    context: Context,
    projectId: string,
    signal: AbortSignal
): Promise<boolean | undefined> {
    const status = inboxStatusSchema.safeParse(
        await context.api.request<Schemas.InboxStatus>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(projectId)}/signals/inbox_status/`,
            signal,
        })
    )
    return status.success ? status.data.setup_state === SETUP_NOT_STARTED : undefined
}

// Mirrors EVAL_INTERACTION_ORIGIN in products/tasks/backend/constants.py. The eval harness runs the agent as a
// sandboxed task, so its token and headers fail the customer-caller checks below. The caller can set this header
// itself, which is safe only because the rule runs in development and test alone.
const EVAL_HARNESS_CONSUMER = 'eval'

function isCustomerCaller(state: ResolvedState): boolean {
    return (
        !state.isTaskBound &&
        !state.sandboxTaskId &&
        resolveScopePreset(state.apiKeyScopes) === 'user' &&
        isCustomerAgentCaller({
            mcpConsumer: state.clientProfile.consumer,
            clientUserAgent: state.requestContext.clientUserAgent,
            apiKeyScopes: state.apiKeyScopes,
            oauthClientId: state.oauthClientId,
        })
    )
}

function isEligibleCall(state: ResolvedState, call: GuidanceCall): boolean {
    return (
        (call.toolName === 'query-error-tracking-issues-list' ||
            (call.toolName === 'query-error-tracking-issue' && typeof call.args?.issueId === 'string')) &&
        !call.isError &&
        !state.isImpersonated &&
        !state.suppressAnalytics &&
        state.aiConsentGiven === true &&
        (state.clientProfile.consumer === EVAL_HARNESS_CONSUMER || isCustomerCaller(state)) &&
        typeof state.toolFeatureFlags?.[MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG] === 'boolean' &&
        REQUIRED_TOOLS.every((name) => state.allTools.some((tool) => tool.name === name))
    )
}

function sessionKey(state: ResolvedState, handle: string): string {
    const identity = createHash('sha256').update(`${state.distinctId}|${handle}`).digest('base64url').slice(0, 22)
    return `mcp:guidance:sd-activation:{${identity}}`
}

function ineligibleKey(state: ResolvedState, projectId: string): string {
    const identity = createHash('sha256')
        .update(
            JSON.stringify([
                state.context.api.config.baseUrl,
                projectId,
                state.distinctId,
                state.context.api.config.apiToken,
                [...state.apiKeyScopes].sort(),
            ])
        )
        .digest('base64url')
    return `mcp:guidance:sd-activation:ineligible:{${identity}}`
}

function activationText(projectUrl: string): string {
    return formatPrompt(ACTIVATION_PROMPT, { project_url: projectUrl }).replace(/\n{3,}/g, '\n\n')
}

async function lookupActivationGuidance(
    redis: RedisLike,
    state: ResolvedState,
    productState: GuidanceProductState,
    firstSessionCall: boolean
): Promise<GuidanceNotice | undefined> {
    const suppliedHandle = firstSessionCall ? undefined : state.carriedContextSessionKey
    const countingKey = sessionKey(state, suppliedHandle ?? '')
    const ttl = suppliedHandle ? SESSION_TTL_SECONDS : CALLER_TTL_SECONDS
    const alreadyShown = await redis.get(countingKey)
    if (!productState.hasBudgetLeft()) {
        return undefined
    }
    if (alreadyShown) {
        await redis.expire(countingKey, ttl)
        return undefined
    }

    const projectId = await state.context.stateManager.getProjectId()
    if (!productState.hasBudgetLeft()) {
        return undefined
    }
    const negativeKey = ineligibleKey(state, String(projectId))
    const ineligible = await redis.get(negativeKey)
    if (ineligible || !productState.hasBudgetLeft()) {
        return undefined
    }
    // Let a failed request throw, because the product-state budget records the rejection as a lookup error.
    const notStarted = await fetchSelfDrivingSetupNotStarted(
        state.context,
        String(projectId),
        AbortSignal.timeout(1000)
    )
    if (notStarted === undefined || !productState.hasBudgetLeft()) {
        return undefined
    }
    if (!notStarted) {
        await redis.set(negativeKey, '1', 'EX', INELIGIBLE_TTL_SECONDS)
        return undefined
    }
    const reserved = await redis.set(countingKey, '1', 'EX', ttl, 'NX')
    if (reserved !== 'OK') {
        return undefined
    }
    const ownedKeys = [countingKey]
    let keepReservation = false
    try {
        if (!productState.hasBudgetLeft()) {
            return undefined
        }
        // Keep the caller-scoped reservation when the client goes on using this session or its minted handle.
        const handleToMirror = firstSessionCall
            ? state.carriedContextSessionKey
            : state.requestContext.mcpConversationId
        if (!suppliedHandle && handleToMirror) {
            const mirrorKey = sessionKey(state, handleToMirror)
            if ((await redis.set(mirrorKey, '1', 'EX', SESSION_TTL_SECONDS, 'NX')) === 'OK') {
                ownedKeys.push(mirrorKey)
            } else if (firstSessionCall) {
                // A concurrent later call on this session already holds its reservation.
                return undefined
            }
        }
        if (!productState.hasBudgetLeft()) {
            return undefined
        }

        const outcome =
            state.toolFeatureFlags?.[MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG] === true ? 'shown' : 'flag_off'
        const projectUrl = state.context.api.getProjectBaseUrl(String(projectId))
        const notice: GuidanceNotice = {
            ruleId: RULE_ID,
            outcome,
            ...(outcome === 'shown' ? { text: activationText(projectUrl) } : {}),
        }
        keepReservation = true
        return notice
    } finally {
        if (!keepReservation) {
            await Promise.all(ownedKeys.map((key) => redis.del(key).catch(() => undefined)))
        }
    }
}

export async function selfDrivingActivationGuidance(
    redis: RedisLike,
    state: ResolvedState,
    call: GuidanceCall,
    productState: GuidanceProductState,
    firstSessionCall: boolean
): Promise<GuidanceNotice | undefined> {
    if (process.env.NODE_ENV !== 'development' && process.env.NODE_ENV !== 'test') {
        return undefined
    }
    if (!isEligibleCall(state, call)) {
        return undefined
    }
    return productState.withinBudget('self_driving_activation', () =>
        lookupActivationGuidance(redis, state, productState, firstSessionCall)
    )
}
