import { createHash } from 'node:crypto'

import type { Schemas } from '@/api/generated'
import { EVENT_SOURCE, resolveEventSource } from '@/lib/event-source'
import { resolveScopePreset } from '@/lib/scope-preset'

import type { RedisLike } from '../cache/RedisCache'
import type { ResolvedState } from '../request-state-resolver'
import type { GuidanceCall, GuidanceNotice } from './engine'
import { MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG } from './rules'

const RULE_ID = 'error-tracking-sd-activation'
const SESSION_TTL_SECONDS = 24 * 60 * 60
const ACTIVATION_TOOLS = ['self-driving-activation-get', 'self-driving-activate']

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
        ACTIVATION_TOOLS.every((name) => state.allTools.some((tool) => tool.name === name))
    )
}

function sessionKey(state: ResolvedState, handle: string): string {
    const identity = createHash('sha256').update(`${state.distinctId}|${handle}`).digest('base64url').slice(0, 22)
    return `mcp:guidance:sd-activation:{${identity}}`
}

const ACTIVATION_TEXT = [
    'Self-driving is not activated for this project. Continue helping with the current error investigation.',
    'You may briefly offer: "Self-driving can investigate errors like this in the background and prepare reports',
    'with evidence and suggested fixes, so you have a head start next time. Would you like me to enable it for this project?"',
    'Before asking, call `self-driving-activation-get` and explain its `setup_description`, including parent-project',
    'effects, and billing terms. If `automatic_implementation` is true, explicitly say that Self-driving may open',
    'pull requests for the user to review and merge. Call `self-driving-activate` only after the user',
    "explicitly agrees to those settings, using the preview's activation mode and automatic implementation setting.",
    'Do not claim that a report or pull request already exists, or that enabling Self-driving completes this investigation.',
].join(' ')

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
    const preview = await state.context.api.request<Schemas.SelfDrivingActivationPreview>({
        method: 'GET',
        path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/onboarding/activation/`,
        signal: AbortSignal.timeout(1000),
    })
    if (preview.state !== 'not_started' || !preview.can_activate) {
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
    return { ruleId: RULE_ID, outcome, ...(outcome === 'shown' ? { text: ACTIVATION_TEXT } : {}) }
}
