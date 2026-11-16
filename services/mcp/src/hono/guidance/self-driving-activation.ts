import { createHash } from 'node:crypto'
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { isCustomerAgentCaller } from '@/lib/event-source'
import { resolveScopePreset } from '@/lib/scope-preset'
import { formatPrompt } from '@/lib/utils'
import IN_CHAT_ACTIVATION_PROMPT from '@/templates/guidance/self-driving-activation-in-chat.md'
import WITHOUT_GITHUB_OFFER from '@/templates/guidance/self-driving-activation-without-github.md'
import ACTIVATION_PROMPT from '@/templates/guidance/self-driving-activation.md'

import type { RedisLike } from '../cache/RedisCache'
import type { ResolvedState } from '../request-state-resolver'
import type { GuidanceCall, GuidanceNotice } from './engine'
import type { GuidanceProductState } from './product-state'
import { MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG, MCP_SELF_DRIVING_PAGELESS_ACTIVATION_FLAG } from './rules'

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
const IN_CHAT_ACTIVATION_TOOLS = [
    'self-driving-activation-preview',
    'self-driving-activate-prepare',
    'self-driving-activate-execute',
]
const onboardingSchema = z.object({
    completed_at: z.string().nullable(),
    draft: z.record(z.string(), z.unknown()).nullable(),
    github_connected: z.boolean().optional().default(false),
    github_optional_available: z.boolean().optional().default(false),
})
type OnboardingState = z.infer<typeof onboardingSchema>

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

// GitHub authorization needs a browser, so only a project that is already connected can activate in chat.
function offersInChatActivation(state: ResolvedState, onboarding: OnboardingState): boolean {
    return (
        onboarding.github_connected &&
        state.toolFeatureFlags?.[MCP_SELF_DRIVING_PAGELESS_ACTIVATION_FLAG] === true &&
        IN_CHAT_ACTIVATION_TOOLS.every((name) => state.allTools.some((tool) => tool.name === name))
    )
}

function activationText(projectUrl: string, onboarding: OnboardingState, inChat: boolean): string {
    const vars = { project_url: projectUrl }
    if (inChat) {
        return formatPrompt(IN_CHAT_ACTIVATION_PROMPT, vars)
    }
    return formatPrompt(ACTIVATION_PROMPT, {
        ...vars,
        github_optional_offer: onboarding.github_optional_available ? formatPrompt(WITHOUT_GITHUB_OFFER, vars) : '',
    }).replace(/\n{3,}/g, '\n\n')
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
    if (reserved !== 'OK') {
        return undefined
    }
    const ownedKeys = [countingKey]
    let keepReservation = false
    try {
        if (!productState.hasBudgetLeft()) {
            return undefined
        }
        // Keep the caller-scoped reservation when the client starts echoing its newly minted conversation handle.
        const mintedHandle = state.requestContext.mcpConversationId
        if (!suppliedHandle && mintedHandle) {
            const mirrorKey = sessionKey(state, mintedHandle)
            if ((await redis.set(mirrorKey, '1', 'EX', SESSION_TTL_SECONDS, 'NX')) === 'OK') {
                ownedKeys.push(mirrorKey)
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
            ...(outcome === 'shown'
                ? { text: activationText(projectUrl, onboarding.data, offersInChatActivation(state, onboarding.data)) }
                : {}),
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
    productState: GuidanceProductState
): Promise<GuidanceNotice | undefined> {
    if (!isEligibleCall(state, call)) {
        return undefined
    }
    return productState.withinBudget('self_driving_activation', () =>
        lookupActivationGuidance(redis, state, productState)
    )
}
