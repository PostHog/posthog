import { createHash } from 'node:crypto'
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { isCustomerAgentCaller } from '@/lib/event-source'
import { resolveScopePreset } from '@/lib/scope-preset'

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
const onboardingSchema = z.object({
    completed_at: z.string().nullable(),
    draft: z.record(z.string(), z.unknown()).nullable(),
    github_optional_available: z.boolean().optional().default(false),
})

function isEligibleCall(state: ResolvedState, call: GuidanceCall): boolean {
    return (
        (call.toolName === 'query-error-tracking-issues-list' ||
            (call.toolName === 'query-error-tracking-issue' && typeof call.args?.issueId === 'string')) &&
        !call.isError &&
        !state.isImpersonated &&
        !state.suppressAnalytics &&
        !state.isTaskBound &&
        !state.sandboxTaskId &&
        state.aiConsentGiven === true &&
        resolveScopePreset(state.apiKeyScopes) === 'user' &&
        isCustomerAgentCaller({
            mcpConsumer: state.clientProfile.consumer,
            clientUserAgent: state.requestContext.clientUserAgent,
            apiKeyScopes: state.apiKeyScopes,
            oauthClientId: state.oauthClientId,
        }) &&
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

function activationText(projectUrl: string, githubOptional: boolean): string {
    return [
        'Self-driving setup has not started for this project. Briefly recommend activation alongside your answer to the current error investigation.',
        "Explain the connection to the customer's task: Self-driving investigates errors in the background and saves reports with findings and work logs. Future investigations can start from those reports, reuse the evidence, and explore only the remaining gaps instead of repeating the full investigation.",
        `Offer: "[Connect GitHub and activate Self-driving](${projectUrl}/inbox/activate) to investigate errors in the background. Next time, we can start with an existing report and skip repeated investigation. It includes a free tier and default usage limit."`,
        ...(githubOptional
            ? [
                  `Also briefly offer: "GitHub connects your data to code so agents can find root causes and suggest changes. Prefer to [start without GitHub](${projectUrl}/inbox/activate/without-github)? Self-driving can still surface issues and data correlations."`,
              ]
            : []),
        'The customer activates in the linked page. Do not activate through tools or ask them to configure sources or scouts in chat.',
        'After sending the link, poll `self-driving-status-get` for the same project every 10 seconds for up to five minutes.',
        'Stop on a non-null `completed_at`, an error, a project switch, or the time limit. If still pending, briefly ask the customer to confirm when setup finishes.',
        'Continue helping with the current task while they set up. Once setup completes, briefly say you will check existing reports first next time.',
        'After completion, and before later investigations in this conversation,',
        'use `inbox-reports-list` with `search` set to specific issue or error terms and `limit=3`; read matching reports and work logs before repeating research.',
        'Use relevant findings to answer the customer and investigate only gaps that the reports leave open.',
        'Check freshness and linked PR status. A reference or linked PR does not prove a fix, and an empty search does not prove there is no relevant research.',
        'Then resume the interrupted task or follow their next request. Do not claim activation means a report is already ready.',
    ].join(' ')
}

async function lookupActivationGuidance(
    redis: RedisLike,
    state: ResolvedState,
    productState: GuidanceProductState
): Promise<GuidanceNotice | undefined> {
    const suppliedHandle = state.carriedContextSessionKey
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
    const onboarding = onboardingSchema.safeParse(
        await state.context.api.request<Schemas.InboxOnboardingState>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/onboarding/`,
            signal: AbortSignal.timeout(1000),
        })
    )
    if (!onboarding.success || !productState.hasBudgetLeft()) {
        return undefined
    }
    if (onboarding.data.completed_at !== null || onboarding.data.draft !== null) {
        await redis.set(negativeKey, '1', 'EX', INELIGIBLE_TTL_SECONDS)
        return undefined
    }

    const reserved = await redis.set(countingKey, '1', 'EX', ttl, 'NX')
    if (reserved !== 'OK' || !productState.hasBudgetLeft()) {
        return undefined
    }
    // Keep the caller-scoped reservation when the client starts echoing its newly minted conversation handle.
    const mintedHandle = state.requestContext.mcpConversationId
    if (!suppliedHandle && mintedHandle) {
        await redis.set(sessionKey(state, mintedHandle), '1', 'EX', SESSION_TTL_SECONDS, 'NX')
    }

    const outcome = state.toolFeatureFlags?.[MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG] === true ? 'shown' : 'flag_off'
    const projectUrl = state.context.api.getProjectBaseUrl(String(projectId))
    return {
        ruleId: RULE_ID,
        outcome,
        ...(outcome === 'shown' ? { text: activationText(projectUrl, onboarding.data.github_optional_available) } : {}),
    }
}

export async function selfDrivingActivationGuidance(
    redis: RedisLike,
    state: ResolvedState,
    call: GuidanceCall,
    productState: GuidanceProductState
): Promise<GuidanceNotice | undefined> {
    if (!isEligibleCall(state, call)) {
        return undefined
    }
    return productState.withinBudget('self_driving_activation', () =>
        lookupActivationGuidance(redis, state, productState)
    )
}
