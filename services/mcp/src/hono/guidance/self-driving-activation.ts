import { createHash } from 'node:crypto'
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { EVENT_SOURCE, resolveEventSource } from '@/lib/event-source'
import { resolveScopePreset } from '@/lib/scope-preset'

import type { RedisLike } from '../cache/RedisCache'
import type { ResolvedState } from '../request-state-resolver'
import type { GuidanceCall, GuidanceNotice } from './engine'
import { MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG } from './rules'

const RULE_ID = 'error-tracking-sd-activation'
const SESSION_TTL_SECONDS = 24 * 60 * 60
const INELIGIBLE_TTL_SECONDS = 30
const REPORT_TOOLS = ['inbox-reports-list', 'inbox-reports-retrieve', 'inbox-report-artefacts-list']
const onboardingSchema = z.object({
    completed_at: z.string().nullable(),
    draft: z.record(z.string(), z.unknown()).nullable(),
    github_optional_available: z.boolean().optional().default(false),
})

function isEligibleCall(state: ResolvedState, call: GuidanceCall): boolean {
    return (
        call.toolName === 'query-error-tracking-issue' &&
        !call.isError &&
        typeof call.args?.issueId === 'string' &&
        !state.isImpersonated &&
        !state.suppressAnalytics &&
        !state.isTaskBound &&
        !state.sandboxTaskId &&
        state.aiConsentGiven === true &&
        resolveScopePreset(state.apiKeyScopes) === 'user' &&
        resolveEventSource({
            mcpConsumer: state.clientProfile.consumer,
            clientUserAgent: state.requestContext.clientUserAgent,
            apiKeyScopes: state.apiKeyScopes,
            oauthClientId: state.oauthClientId,
        }) === EVENT_SOURCE.MCP &&
        typeof state.toolFeatureFlags?.[MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG] === 'boolean' &&
        REPORT_TOOLS.every((name) => state.allTools.some((tool) => tool.name === name))
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

function activationText(setupUrl: string, githubOptional: boolean): string {
    return [
        'Self-driving setup has not started for this project. Keep all customer-facing messages very brief.',
        `Offer: "[Activate Self-driving](${setupUrl}) for background error investigations, with a free tier and default usage limit. Tell me when it's on; next time I'll check existing reports first."`,
        ...(githubOptional
            ? [
                  'Also briefly offer: "GitHub helps agents connect your data to code, find root causes and suggest changes. Prefer to start without it? Self-driving can still surface issues and data correlations."',
                  'If they prefer setup without GitHub, send the same activation link; that page supports it for this project.',
              ]
            : []),
        'The customer activates in the linked page. Do not activate through tools or ask them to configure sources or scouts in chat.',
        'Continue helping with the current task while they set up. After they confirm, and before later investigations in this conversation,',
        'use `inbox-reports-list` with `search` set to specific issue or error terms and `limit=3`; read matching reports and work logs before repeating research.',
        'Check freshness and linked PR status. A reference or linked PR does not prove a fix, and an empty search does not prove there is no relevant research.',
        'Then resume the interrupted task or follow their next request. Do not claim activation means a report is already ready.',
    ].join(' ')
}

export async function selfDrivingActivationGuidance(
    redis: RedisLike,
    state: ResolvedState,
    call: GuidanceCall
): Promise<GuidanceNotice | undefined> {
    if (!isEligibleCall(state, call)) {
        return undefined
    }

    const suppliedHandle = state.carriedContextSessionKey
    const suppliedKey = suppliedHandle ? sessionKey(state, suppliedHandle) : undefined
    if (suppliedKey && (await redis.get(suppliedKey))) {
        await redis.expire(suppliedKey, SESSION_TTL_SECONDS)
        return undefined
    }

    const projectId = await state.context.stateManager.getProjectId()
    const negativeKey = ineligibleKey(state, String(projectId))
    if (await redis.get(negativeKey)) {
        return undefined
    }
    const onboarding = onboardingSchema.safeParse(
        await state.context.api.request<Schemas.InboxOnboardingState>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/onboarding/`,
            signal: AbortSignal.timeout(1000),
        })
    )
    if (!onboarding.success) {
        return undefined
    }
    if (onboarding.data.completed_at !== null || onboarding.data.draft !== null) {
        await redis.set(negativeKey, '1', 'EX', INELIGIBLE_TTL_SECONDS)
        return undefined
    }

    // A generated handle cannot suppress this call, but remembering it preserves the cap if the client echoes it next time.
    const handle = suppliedHandle ?? state.requestContext.mcpConversationId
    if (handle) {
        const reserved = await redis.set(sessionKey(state, handle), '1', 'EX', SESSION_TTL_SECONDS, 'NX')
        if (suppliedHandle && reserved !== 'OK') {
            return undefined
        }
    }

    const outcome = state.toolFeatureFlags?.[MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG] === true ? 'shown' : 'flag_off'
    const setupUrl = `${state.context.api.getProjectBaseUrl(String(projectId))}/inbox?setup=github-first&onboarding_step=quick`
    return {
        ruleId: RULE_ID,
        outcome,
        ...(outcome === 'shown' ? { text: activationText(setupUrl, onboarding.data.github_optional_available) } : {}),
    }
}
