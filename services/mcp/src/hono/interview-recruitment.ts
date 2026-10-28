import type { JSONRPCRequest } from '@modelcontextprotocol/sdk/types.js'
import { createHash, randomUUID } from 'node:crypto'
import { z } from 'zod'

import { getPostHogClient } from '@/lib/posthog'
import {
    META_CLIENT_CAPABILITIES,
    parseRequestProtocolMeta,
    STATELESS_PROTOCOL_VERSION,
} from '@/lib/stateless-protocol'
import { isPrivateScoutTrialTool } from '@/lib/tool-privacy'
import { parseExecCallInnerToolName } from '@/tools/exec'

import type { RedisLike } from './cache/RedisCache'
import { resolveSessionKey } from './mcp-context'
import type { ResolvedState } from './request-state-resolver'

// WARNING: Unsolicited elicitation can interrupt users' work and turn the MCP into an advertising channel.
// This interview flow is a narrow exception, not a general survey or promotion mechanism.
// services/mcp/AGENTS.md requires human MCP owner approval before adding prompts or expanding their reach/frequency.
export const MCP_INTERVIEW_RECRUITMENT_FLAG = 'mcp-interview-recruitment'

const DEFAULT_CAMPAIGN_ID = 'mcp-research'
const campaignIdSchema = z.string().regex(/^[a-z][a-z0-9_-]{0,63}$/)
const invitationMessageSchema = z.string().trim().min(1).max(1000)

const bookingUrlSchema = z.url().refine((value) => value.startsWith('https://'))

const interviewRecruitmentConfigSchema = z.object({
    min_completed_tool_calls: z.number().int().min(0).max(1000).default(3),
    min_session_age_seconds: z.number().int().min(0).max(86400).default(120),
    message: invitationMessageSchema,
    booking_url: bookingUrlSchema,
})

export type InterviewRecruitmentConfig = z.infer<typeof interviewRecruitmentConfigSchema> & { campaign_id: string }

export type InterviewRecruitmentUnavailableReason =
    | 'surface_excluded'
    | 'internal_run'
    | 'task_bound'
    | 'flag_disabled'
    | 'flag_unavailable'
    | 'invalid_configuration'

export interface InterviewRecruitmentDiagnostics {
    reason:
        | InterviewRecruitmentUnavailableReason
        | 'legacy_protocol'
        | 'eligible'
        | 'continuation'
        | 'request_state_present'
        | 'configuration_unavailable'
        | 'url_unsupported'
        | 'not_product_call'
        | 'missing_conversation'
        | 'suppressed'
        | 'insufficient_tool_calls'
        | 'session_too_young'
        | 'reservation_conflict'
        | 'redis_error'
        | 'invited'
    urlSupported: boolean | null
    formSupported: boolean | null
    campaignId?: string
    completedCalls?: number
    sessionAgeSeconds?: number
}

export function interviewRecruitmentProperties(diagnostics: InterviewRecruitmentDiagnostics): Record<string, unknown> {
    return {
        interview_recruitment_reason: diagnostics.reason,
        interview_recruitment_url_supported: diagnostics.urlSupported,
        interview_recruitment_form_supported: diagnostics.formSupported,
        ...(diagnostics.campaignId ? { interview_recruitment_campaign_id: diagnostics.campaignId } : {}),
        ...(diagnostics.completedCalls !== undefined
            ? { interview_recruitment_completed_calls: diagnostics.completedCalls }
            : {}),
        ...(diagnostics.sessionAgeSeconds !== undefined
            ? { interview_recruitment_session_age_seconds: diagnostics.sessionAgeSeconds }
            : {}),
    }
}

export function resolveInterviewRecruitmentConfig(
    value: unknown,
    payload: unknown
): InterviewRecruitmentConfig | undefined {
    const campaign = campaignIdSchema.safeParse(value === true ? DEFAULT_CAMPAIGN_ID : value)
    if (!campaign.success) {
        return undefined
    }
    const config = interviewRecruitmentConfigSchema.safeParse(payload)
    return config.success ? { ...config.data, campaign_id: campaign.data } : undefined
}

const INPUT_ID = 'mcp-interview'
const STATE_PREFIX = 'mcp-interview:'
const PENDING_SECONDS = 10 * 60
const COOLDOWN_SECONDS = 7 * 24 * 60 * 60
const CONVERSATION_IDLE_SECONDS = 24 * 60 * 60

type InterviewInvitation = {
    resultType: 'input_required'
    requestState: string
    inputRequests: Record<
        typeof INPUT_ID,
        {
            method: 'elicitation/create'
            params: { mode: 'url'; elicitationId: string; message: string; url: string }
        }
    >
}

function isCompletedToolCall(result: unknown): boolean {
    return (
        !!result &&
        typeof result === 'object' &&
        'content' in result &&
        Array.isArray(result.content) &&
        !('isError' in result && result.isError === true)
    )
}

// The counter and deduplication fields expire together; retries cannot increment after losing their deduplication record.
const OBSERVE_CONVERSATION = `
redis.call('HSETNX', KEYS[1], 'started_at', ARGV[1])
local completed = tonumber(redis.call('HGET', KEYS[1], 'completed_calls') or '0')
if ARGV[3] ~= '' and completed < 1000 then
    if redis.call('HSETNX', KEYS[1], 'request:' .. ARGV[3], '1') == 1 then
        completed = redis.call('HINCRBY', KEYS[1], 'completed_calls', 1)
    end
end
redis.call('EXPIRE', KEYS[1], ARGV[2])
return {completed, tonumber(redis.call('HGET', KEYS[1], 'started_at'))}
`

// Both keys share a Redis Cluster slot. Reserving before returning the invitation prevents parallel calls from asking twice.
const RESERVE_INVITATION = `
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[3])
redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[4])
return 1
`

const SAVE_RESPONSE = `
if redis.call('GET', KEYS[2]) ~= ARGV[1] then return 0 end
if ARGV[3] == '0' then
    redis.call('SET', KEYS[1], ARGV[2])
else
    redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
end
redis.call('SET', KEYS[2], ARGV[4], 'EX', ARGV[5])
return 1
`

const bookingLinkSchema = z.object({
    distinct_id: z.string().min(1),
    invitation_id: z.uuid(),
    url: bookingUrlSchema,
    campaign_id: campaignIdSchema,
})

const pendingInvitationSchema = z.object({
    fingerprint: z.string(),
    delivery: z.enum(['stateless', 'legacy']).default('stateless'),
    campaign_id: campaignIdSchema,
    organization_id: z.string().min(1),
    project_id: z.string().min(1),
    consumed: z.boolean().default(false),
})

const responseSchema = z.object({ action: z.enum(['accept', 'decline', 'cancel']) })
const legacyResponseSchema = z.object({
    jsonrpc: z.literal('2.0'),
    id: z.string().regex(/^mcp-interview:[0-9a-f-]{36}$/),
    method: z.never().optional(),
    result: responseSchema,
})

export class InterviewRequestError extends Error {}

export class InterviewRecruitment {
    constructor(private readonly redis: RedisLike) {}

    private track(
        event: string,
        distinctId: string,
        invitationId: string,
        campaignId: string,
        response?: string,
        diagnostics?: InterviewRecruitmentDiagnostics
    ): void {
        try {
            getPostHogClient().capture({
                distinctId,
                event,
                properties: {
                    invitation_id: invitationId,
                    campaign_id: campaignId,
                    feature_flag: MCP_INTERVIEW_RECRUITMENT_FLAG,
                    ...(response ? { response } : {}),
                    ...(diagnostics ? interviewRecruitmentProperties(diagnostics) : {}),
                },
            })
        } catch {
            // Analytics availability must not block the invitation or booking page.
        }
    }

    private bookingLinkKey(invitationId: string): string {
        return `mcp:interview:link:{${invitationId}}`
    }

    async openBookingLink(invitationId: string): Promise<string | undefined> {
        if (!z.uuid().safeParse(invitationId).success) {
            return undefined
        }
        const key = this.bookingLinkKey(invitationId)
        const raw = await this.redis.get(key)
        if (!raw) {
            return undefined
        }
        const link = bookingLinkSchema.safeParse(JSON.parse(raw))
        if (!link.success || link.data.invitation_id !== invitationId) {
            return undefined
        }
        try {
            const firstOpen = await this.redis.set(`${key}:opened`, '1', 'EX', COOLDOWN_SECONDS, 'NX')
            if (firstOpen === 'OK') {
                this.track(
                    'mcp interview booking link opened',
                    link.data.distinct_id,
                    invitationId,
                    link.data.campaign_id
                )
            }
        } catch {
            // A failed analytics deduplication write must not prevent a known booking redirect.
        }
        return link.data.url
    }

    private preferenceKey(state: ResolvedState): string {
        const identity = createHash('sha256')
            .update(JSON.stringify([state.context.api.getProjectBaseUrl('@current'), state.distinctId]))
            .digest('hex')
        return `mcp:interview:{${identity}}:response`
    }

    private requestFingerprint(params: Record<string, unknown>, userHash: string): string {
        return createHash('sha256')
            .update(
                JSON.stringify([userHash, params.name, params.arguments ?? {}], (_key, value: unknown) =>
                    value && typeof value === 'object' && !Array.isArray(value)
                        ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)))
                        : value
                )
            )
            .digest('hex')
    }

    private supportsUrl(params: Record<string, unknown>, state: ResolvedState): boolean {
        if (parseRequestProtocolMeta(params).protocolVersion !== STATELESS_PROTOCOL_VERSION) {
            return state.sessionContext?.mcpElicitationUrlSupported === true
        }
        return z
            .object({ elicitation: z.object({ url: z.object({}) }) })
            .safeParse((params._meta as Record<string, unknown> | undefined)?.[META_CLIENT_CAPABILITIES]).success
    }

    private isProductCall(params: Record<string, unknown>, state: ResolvedState): boolean {
        const args = params.arguments as Record<string, unknown> | undefined
        const name =
            params.name === 'exec'
                ? typeof args?.command === 'string'
                    ? parseExecCallInnerToolName(args.command)
                    : undefined
                : params.name
        return (
            typeof name === 'string' &&
            name !== 'docs-search' &&
            !isPrivateScoutTrialTool(name) &&
            !/^skills?-/.test(name) &&
            state.allTools.some((tool) => tool.name === name)
        )
    }

    private eligibleConversation(
        params: Record<string, unknown>,
        state: ResolvedState,
        allowLegacy = false
    ): { config: InterviewRecruitmentConfig; key: string } | { reason: InterviewRecruitmentDiagnostics['reason'] } {
        if (!allowLegacy && parseRequestProtocolMeta(params).protocolVersion !== STATELESS_PROTOCOL_VERSION) {
            return { reason: 'legacy_protocol' }
        }
        if (params.requestState !== undefined) {
            return { reason: 'request_state_present' }
        }
        const config = state.interviewRecruitmentConfig
        if (!config) {
            return { reason: state.interviewRecruitmentUnavailableReason ?? 'configuration_unavailable' }
        }
        if (state.isImpersonated || state.suppressAnalytics) {
            return { reason: 'suppressed' }
        }
        if (!this.supportsUrl(params, state)) {
            return { reason: 'url_unsupported' }
        }
        if (!this.isProductCall(params, state)) {
            return { reason: 'not_product_call' }
        }
        const conversation = resolveSessionKey(state.requestContext)
        if (!conversation) {
            return { reason: 'missing_conversation' }
        }
        const client = state.requestContext
        const hash = createHash('sha256')
            .update(JSON.stringify([client.mcpClientName, client.mcpVendorClient, client.mcpConsumer, conversation]))
            .digest('hex')
        return { config, key: `${this.preferenceKey(state)}:conversation:${hash}` }
    }

    async afterToolCall(
        params: Record<string, unknown>,
        state: ResolvedState,
        result: unknown,
        requestId: string | number,
        allowLegacy = false
    ): Promise<void> {
        if (!isCompletedToolCall(result)) {
            return
        }
        const conversation = this.eligibleConversation(params, state, allowLegacy)
        if ('reason' in conversation) {
            return
        }
        try {
            if ((await this.redis.get(this.preferenceKey(state))) !== null) {
                return
            }
            await this.redis.eval(
                OBSERVE_CONVERSATION,
                1,
                conversation.key,
                Date.now(),
                CONVERSATION_IDLE_SECONDS,
                this.requestFingerprint(params, JSON.stringify(requestId))
            )
        } catch {
            // Recruitment bookkeeping must not change the outcome of a completed tool call.
        }
    }

    async afterLegacyToolCall(
        params: Record<string, unknown>,
        state: ResolvedState,
        result: unknown,
        requestId: string | number,
        userHash: string,
        requestOrigin: string
    ): Promise<JSONRPCRequest | undefined> {
        if (params.requestState !== undefined || !isCompletedToolCall(result)) {
            return undefined
        }
        const invitation = await this.beforeToolCall(params, state, userHash, requestOrigin, 'legacy')
        await this.afterToolCall(params, state, result, requestId, true)
        if (!invitation) {
            return undefined
        }
        const input = invitation.inputRequests[INPUT_ID]
        return {
            jsonrpc: '2.0',
            id: invitation.requestState,
            method: 'elicitation/create',
            params: input.params,
        }
    }

    isLegacyResponse(message: unknown): boolean {
        return legacyResponseSchema.safeParse(message).success
    }

    async receiveLegacyResponse(message: unknown, state: ResolvedState, userHash: string): Promise<void> {
        const response = legacyResponseSchema.safeParse(message)
        if (!response.success) {
            return
        }
        try {
            await this.resume(
                { requestState: response.data.id, inputResponses: { [INPUT_ID]: response.data.result } },
                state,
                userHash,
                'legacy'
            )
        } catch (error) {
            if (!(error instanceof InterviewRequestError)) {
                throw error
            }
        }
    }

    private async resume(
        params: Record<string, unknown>,
        state: ResolvedState,
        userHash: string,
        delivery: 'stateless' | 'legacy' = 'stateless'
    ): Promise<void> {
        const requestState = params.requestState as string
        if (!/^mcp-interview:[0-9a-f-]{36}$/.test(requestState)) {
            throw new InterviewRequestError('Invalid interview invitation state.')
        }
        const parsed = responseSchema.safeParse(
            (params.inputResponses as Record<string, unknown> | undefined)?.[INPUT_ID]
        )
        if (!parsed.success) {
            throw new InterviewRequestError('Missing or invalid interview response.')
        }
        const response =
            parsed.data.action === 'accept'
                ? 'booking_link_accepted'
                : parsed.data.action === 'decline'
                  ? 'do_not_ask_again'
                  : 'not_now'
        const preferenceKey = this.preferenceKey(state)
        const pendingKey = `${preferenceKey}:${requestState}`
        const rawPending = (await this.redis.get(pendingKey)) ?? ''
        const pending = pendingInvitationSchema.safeParse(rawPending ? JSON.parse(rawPending) : undefined)
        if (
            !pending.success ||
            pending.data.delivery !== delivery ||
            pending.data.fingerprint !== this.requestFingerprint(delivery === 'legacy' ? {} : params, userHash)
        ) {
            throw new InterviewRequestError(
                'Interview invitation expired, changed, or is unavailable. Check whether the original tool completed before retrying; do not automatically repeat a write.'
            )
        }
        if (pending.data.consumed) {
            throw new InterviewRequestError(
                'This interview response was already consumed. The original tool may have run. Check its outcome before retrying; do not automatically repeat a write.'
            )
        }
        if (delivery === 'stateless') {
            const [organizationId, projectId] = await Promise.all([
                state.context.stateManager.getOrgID(),
                state.context.stateManager.getProjectId(),
            ])
            if (pending.data.organization_id !== organizationId || pending.data.project_id !== projectId) {
                throw new InterviewRequestError(
                    'The active project or organization changed while the invitation was open. Restore the original context before retrying this continuation.'
                )
            }
        }
        const saved = await this.redis.eval(
            SAVE_RESPONSE,
            2,
            preferenceKey,
            pendingKey,
            rawPending,
            JSON.stringify({
                distinct_id: state.distinctId,
                campaign_id: pending.data.campaign_id,
                response,
                responded_at: new Date().toISOString(),
            }),
            response === 'not_now' ? COOLDOWN_SECONDS : 0,
            JSON.stringify({ ...pending.data, consumed: true }),
            PENDING_SECONDS
        )
        if (saved !== 1) {
            throw new InterviewRequestError(
                'Interview invitation expired, changed, or is unavailable. Check whether the original tool completed before retrying; do not automatically repeat a write.'
            )
        }
        if (!state.isImpersonated && !state.suppressAnalytics) {
            this.track(
                'mcp interview invitation responded',
                state.distinctId,
                requestState.slice(STATE_PREFIX.length),
                pending.data.campaign_id,
                parsed.data.action
            )
        }
    }

    async beforeToolCall(
        params: Record<string, unknown>,
        state: ResolvedState,
        userHash: string,
        requestOrigin: string,
        delivery: 'stateless' | 'legacy' = 'stateless',
        observeOnly = false
    ): Promise<InterviewInvitation | undefined> {
        const capabilities = (params._meta as Record<string, unknown> | undefined)?.[META_CLIENT_CAPABILITIES]
        const capabilitiesAvailable = z.record(z.string(), z.unknown()).safeParse(capabilities).success
        const diagnostics: InterviewRecruitmentDiagnostics = {
            reason: 'continuation',
            urlSupported: capabilitiesAvailable
                ? z.object({ elicitation: z.object({ url: z.object({}) }) }).safeParse(capabilities).success
                : (state.sessionContext?.mcpElicitationUrlSupported ?? null),
            formSupported: capabilitiesAvailable
                ? z
                      .object({
                          elicitation: z.union([z.object({ form: z.object({}) }), z.object({}).strict()]),
                      })
                      .safeParse(capabilities).success
                : null,
            ...(state.interviewRecruitmentConfig ? { campaignId: state.interviewRecruitmentConfig.campaign_id } : {}),
        }
        state.interviewRecruitmentDiagnostics = diagnostics
        if (
            parseRequestProtocolMeta(params).protocolVersion === STATELESS_PROTOCOL_VERSION &&
            typeof params.requestState === 'string' &&
            params.requestState.startsWith(STATE_PREFIX)
        ) {
            // A flag change must not discard a response to an invitation that was already displayed.
            await this.resume(params, state, userHash)
            return undefined
        }
        const conversation = this.eligibleConversation(params, state, delivery === 'legacy')
        if ('reason' in conversation) {
            diagnostics.reason = conversation.reason
            return undefined
        }
        const { config, key: conversationKey } = conversation

        const invitationId = randomUUID()
        const requestState = `${STATE_PREFIX}${invitationId}`
        const linkKey = this.bookingLinkKey(invitationId)
        const preferenceKey = this.preferenceKey(state)
        try {
            if ((await this.redis.get(preferenceKey)) !== null) {
                diagnostics.reason = 'suppressed'
                return undefined
            }
            const now = Date.now()
            const progress = z
                .tuple([z.number(), z.number()])
                .parse(
                    await this.redis.eval(OBSERVE_CONVERSATION, 1, conversationKey, now, CONVERSATION_IDLE_SECONDS, '')
                )
            diagnostics.completedCalls = progress[0]
            diagnostics.sessionAgeSeconds = Math.max(0, Math.floor((now - progress[1]) / 1000))
            if (progress[0] < config.min_completed_tool_calls) {
                diagnostics.reason = 'insufficient_tool_calls'
                return undefined
            }
            if (now - progress[1] < config.min_session_age_seconds * 1000) {
                diagnostics.reason = 'session_too_young'
                return undefined
            }
            if (observeOnly) {
                diagnostics.reason = 'eligible'
                return undefined
            }
            const [organizationId, projectId] = await Promise.all([
                state.context.stateManager.getOrgID(),
                state.context.stateManager.getProjectId(),
            ])
            await this.redis.set(
                linkKey,
                JSON.stringify({
                    distinct_id: state.distinctId,
                    invitation_id: invitationId,
                    url: config.booking_url,
                    campaign_id: config.campaign_id,
                }),
                'EX',
                COOLDOWN_SECONDS
            )
            const reserved = await this.redis.eval(
                RESERVE_INVITATION,
                2,
                preferenceKey,
                `${preferenceKey}:${requestState}`,
                JSON.stringify({
                    response: 'pending',
                    campaign_id: config.campaign_id,
                    asked_at: new Date().toISOString(),
                }),
                JSON.stringify({
                    fingerprint: this.requestFingerprint(delivery === 'legacy' ? {} : params, userHash),
                    delivery,
                    campaign_id: config.campaign_id,
                    organization_id: organizationId,
                    project_id: projectId,
                }),
                COOLDOWN_SECONDS,
                PENDING_SECONDS
            )
            if (reserved !== 1) {
                diagnostics.reason = 'reservation_conflict'
                await this.redis.del(linkKey)
                return undefined
            }
        } catch {
            // If suppression cannot be checked atomically, skip recruitment and let the user's task proceed.
            diagnostics.reason = 'redis_error'
            return undefined
        }

        diagnostics.reason = 'invited'
        this.track(
            'mcp interview invitation sent',
            state.distinctId,
            invitationId,
            config.campaign_id,
            undefined,
            diagnostics
        )
        const bookingLink = new URL(`/interview/${invitationId}`, requestOrigin).toString()
        return {
            resultType: 'input_required',
            requestState,
            inputRequests: {
                [INPUT_ID]: {
                    method: 'elicitation/create',
                    params: {
                        mode: 'url',
                        elicitationId: invitationId,
                        message: config.message,
                        url: bookingLink,
                    },
                },
            },
        }
    }
}
