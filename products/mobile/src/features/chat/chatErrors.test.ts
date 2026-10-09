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
            '400 on content',
            new ApiError(400, { attr: 'content', detail: 'Ensure this field has no more than 40000 characters.' }),
            { kind: 'invalid', message: 'This message is too long. Shorten it and try again.' },
        ],
        ['a dropped connection', new TypeError('Network request failed'), { kind: 'network' }],
        ['a signed-out session', new NotSignedInError(), { kind: 'auth' }],
    ])('%s', (_label, error, expected) => {
        expect(toChatError(error)).toMatchObject(expected)
    })
})
