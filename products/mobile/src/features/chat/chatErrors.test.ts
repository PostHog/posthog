import { ApiError, NotSignedInError } from '@/api/client'

import { toChatError } from './chatErrors'
import type { ChatError } from './types'

function headers(values: Record<string, string>): Headers {
    return { get: (name: string) => values[name] ?? null } as unknown as Headers
}

describe('chat error mapping', () => {
    test.each<[string, unknown, Partial<ChatError>]>([
        [
            '402 out of credits',
            new ApiError(402, { code: 'quota_limit_exceeded', detail: 'Your organization reached its limit.' }),
            {
                kind: 'credits',
                message: 'Your organization is out of AI credits. An admin can raise the limit in Billing settings.',
            },
        ],
        [
            '429 with server copy',
            new ApiError(
                429,
                { code: 'throttled', detail: 'You hit the hourly limit.' },
                headers({ 'Retry-After': '30' })
            ),
            { kind: 'throttled', message: 'You hit the hourly limit.', retryAfterSeconds: 30 },
        ],
        [
            '429 without server copy',
            new ApiError(429, undefined, headers({ 'Retry-After': '30' })),
            { kind: 'throttled', message: "You've sent a lot of messages. Try again in 30 seconds." },
        ],
        ['409 busy', new ApiError(409, { detail: 'Cannot resume streaming with a new message' }), { kind: 'busy' }],
        [
            '503 at capacity',
            new ApiError(503, undefined, headers({ 'Retry-After': '120' })),
            { kind: 'unavailable', message: 'PostHog AI is busy right now. Try again in 2 minutes.' },
        ],
        [
            '400 from run/ shows the server copy',
            new ApiError(400, { error: 'Invalid resume_from_run_id' }),
            { kind: 'invalid', message: 'Invalid resume_from_run_id' },
        ],
        [
            '400 without server copy',
            new ApiError(400, undefined),
            { kind: 'invalid', message: "PostHog AI couldn't take this message. Start a new chat and try again." },
        ],
        [
            '403 from the PostHog Desktop gate shows the server copy',
            new ApiError(403, {
                type: 'permission_denied',
                code: 'code_access_required',
                reason: 'startup_plan',
                error: "PostHog Desktop isn't available for Startup or YC program organizations.",
            }),
            { kind: 'access', message: "PostHog Desktop isn't available for Startup or YC program organizations." },
        ],
        [
            '503 when the gate cannot decide',
            new ApiError(503, { code: 'desktop_access_unavailable', error: 'x' }),
            { kind: 'unavailable', message: "We couldn't verify PostHog Desktop access. Try again." },
        ],
        [
            '429 from a billing limit',
            new ApiError(429, { type: 'billing_limit', code: 'compute_quota' }),
            { kind: 'throttled', message: "You've reached your PostHog Desktop usage limit." },
        ],
        [
            "429 from the report's task limit shows the server copy",
            new ApiError(429, {
                type: 'rate_limit',
                code: 'signal_report_task_cap',
                error: 'This report hit its limit.',
            }),
            { kind: 'throttled', message: 'This report hit its limit.' },
        ],
        [
            "429 from the report's task limit without server copy",
            new ApiError(429, { type: 'rate_limit', code: 'signal_report_task_cap' }),
            { kind: 'throttled', message: 'This report has reached its chat limit. Try again later.' },
        ],
        [
            '502 when the message was not queued',
            new ApiError(502, { error: 'Failed to queue user message for task run' }),
            { kind: 'unavailable', message: "Your message didn't reach the agent. Try again in a moment." },
        ],
        ['a dropped connection', new TypeError('Network request failed'), { kind: 'network' }],
        ['a signed-out session', new NotSignedInError(), { kind: 'auth' }],
    ])('%s', (_label, error, expected) => {
        expect(toChatError(error)).toMatchObject(expected)
    })
})
