import { createHash, randomUUID } from 'node:crypto'
import { z } from 'zod'

import { META_CLIENT_CAPABILITIES } from '@/lib/stateless-protocol'

import type { RedisLike } from './cache/RedisCache'
import type { ResolvedState } from './request-state-resolver'

export const MCP_INTERVIEW_RECRUITMENT_FLAG = 'mcp-interview-recruitment'

const INPUT_ID = 'mcp-interview'
const STATE_PREFIX = 'mcp-interview:'
const PENDING_SECONDS = 10 * 60
const COOLDOWN_SECONDS = 7 * 24 * 60 * 60

// Both keys share a Redis Cluster slot. Reserving before returning the form prevents parallel calls from asking twice.
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
redis.call('DEL', KEYS[2])
return 1
`

const responseSchema = z.discriminatedUnion('action', [
    z.object({
        action: z.literal('accept'),
        content: z.object({ response: z.enum(['interested', 'not_now', 'do_not_ask_again']) }),
    }),
    z.object({ action: z.enum(['decline', 'cancel']) }),
])

export class InterviewRequestError extends Error {}

export class InterviewRecruitment {
    constructor(private readonly redis: RedisLike) {}

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

    private supportsForm(params: Record<string, unknown>): boolean {
        const capabilities = z
            .object({ elicitation: z.object({ form: z.object({}).optional(), url: z.object({}).optional() }) })
            .safeParse((params._meta as Record<string, unknown> | undefined)?.[META_CLIENT_CAPABILITIES])
        return (
            capabilities.success &&
            (capabilities.data.elicitation.form !== undefined || capabilities.data.elicitation.url === undefined)
        )
    }

    private async resume(params: Record<string, unknown>, state: ResolvedState, userHash: string): Promise<void> {
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
                ? parsed.data.content.response
                : parsed.data.action === 'decline'
                  ? 'do_not_ask_again'
                  : 'not_now'
        const preferenceKey = this.preferenceKey(state)
        const saved = await this.redis.eval(
            SAVE_RESPONSE,
            2,
            preferenceKey,
            `${preferenceKey}:${requestState}`,
            this.requestFingerprint(params, userHash),
            JSON.stringify({ distinct_id: state.distinctId, response, responded_at: new Date().toISOString() }),
            response === 'not_now' ? COOLDOWN_SECONDS : 0
        )
        if (saved !== 1) {
            throw new InterviewRequestError(
                'Interview invitation expired or does not match this request. Retry the original tool call without requestState or inputResponses.'
            )
        }
    }

    async beforeToolCall(
        params: Record<string, unknown>,
        state: ResolvedState,
        userHash: string
    ): Promise<Record<string, unknown> | undefined> {
        if (typeof params.requestState === 'string' && params.requestState.startsWith(STATE_PREFIX)) {
            // A flag change must not discard a response to a form that was already displayed.
            await this.resume(params, state, userHash)
            return undefined
        }
        if (
            params.requestState !== undefined ||
            state.toolFeatureFlags?.[MCP_INTERVIEW_RECRUITMENT_FLAG] !== true ||
            state.isImpersonated ||
            state.suppressAnalytics ||
            !this.supportsForm(params)
        ) {
            return undefined
        }

        const requestState = `${STATE_PREFIX}${randomUUID()}`
        const preferenceKey = this.preferenceKey(state)
        try {
            const reserved = await this.redis.eval(
                RESERVE_INVITATION,
                2,
                preferenceKey,
                `${preferenceKey}:${requestState}`,
                JSON.stringify({ response: 'pending', asked_at: new Date().toISOString() }),
                this.requestFingerprint(params, userHash),
                COOLDOWN_SECONDS,
                PENDING_SECONDS
            )
            if (reserved !== 1) {
                return undefined
            }
        } catch {
            // If suppression cannot be checked atomically, skip recruitment and let the user's task proceed.
            return undefined
        }

        return {
            resultType: 'input_required',
            requestState,
            inputRequests: {
                [INPUT_ID]: {
                    method: 'elicitation/create',
                    params: {
                        mode: 'form',
                        message: '20-minute MCP interview? Yes lets us contact you at your PostHog email.',
                        requestedSchema: {
                            type: 'object',
                            properties: {
                                response: {
                                    type: 'string',
                                    title: 'Interview invitation',
                                    oneOf: [
                                        { const: 'interested', title: 'Yes, contact me' },
                                        { const: 'not_now', title: 'Not now' },
                                        { const: 'do_not_ask_again', title: "Don't ask again" },
                                    ],
                                },
                            },
                            required: ['response'],
                        },
                    },
                },
            },
        }
    }
}
