import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import { classifyAuthFailure } from '@/lib/auth-errors'
import { ErrorCode, PostHogApiError } from '@/lib/errors'

vi.mock('@/lib/posthog', () => ({
    getPostHogClient: () => ({ captureException: vi.fn() }),
}))

// PostHog answers 401 for account state as well as for a bad credential. The client used to
// collapse every 401 to the bare `INVALID_API_KEY` sentinel, so a caller holding a valid,
// freshly issued token was told to replace it, and the server's own reason never arrived.
describe('401 handling', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        vi.spyOn(console, 'error').mockImplementation(() => {})
    })

    afterEach(() => {
        vi.restoreAllMocks()
        vi.unstubAllGlobals()
    })

    const stub401 = (body: string): void => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { status: 401 })))
    }

    const requestError = async (): Promise<unknown> =>
        await new ApiClient({ apiToken: 'phx_test', baseUrl: 'https://us.posthog.com' })
            .request({ method: 'GET', path: '/api/billing/' })
            .then(
                () => undefined,
                (error: unknown) => error
            )

    it('carries the server reason and the status alongside the sentinel', async () => {
        stub401(
            JSON.stringify({
                type: 'authentication_error',
                code: 'permission_denied',
                detail: 'This endpoint reads the project that is set on your account, and your account has none.',
            })
        )

        const error = await requestError()

        expect(error).toBeInstanceOf(PostHogApiError)
        expect((error as PostHogApiError).status).toBe(401)
        expect((error as Error).message).toContain('your account has none')
    })

    it('still reads as an invalid credential, so the re-auth path keeps firing', async () => {
        stub401(JSON.stringify({ detail: 'Invalid access token.' }))

        const error = await requestError()

        expect((error as Error).message).toContain(ErrorCode.INVALID_API_KEY)
        expect(classifyAuthFailure(error).reason).toBe('invalid_api_key')
    })

    it('falls back to the bare sentinel when the body carries no reason', async () => {
        stub401('')

        const error = await requestError()

        expect((error as Error).message).toBe(ErrorCode.INVALID_API_KEY)
    })
})
