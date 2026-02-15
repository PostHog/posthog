import { describe, expect, it } from 'vitest'

import { mapAuthErrorResponse } from '@/lib/auth-error-response'
import { ErrorCode } from '@/lib/errors'

describe('mapAuthErrorResponse', () => {
    it.each([ErrorCode.INACTIVE_OAUTH_TOKEN, ErrorCode.INVALID_API_KEY])(
        'maps %s responses to 401',
        async (errorCode) => {
            const response = new Response(`request failed: ${errorCode}`, { status: 500 })

            const mappedResponse = await mapAuthErrorResponse(response)

            expect(mappedResponse.status).toBe(401)
            expect(await mappedResponse.text()).toBe('OAuth token is inactive')
        }
    )

    it('keeps unrelated non-OK responses unchanged', async () => {
        const response = new Response('request failed: SOMETHING_ELSE', { status: 500 })

        const mappedResponse = await mapAuthErrorResponse(response)

        expect(mappedResponse).toBe(response)
    })

    it('keeps successful responses unchanged', async () => {
        const response = new Response('ok', { status: 200 })

        const mappedResponse = await mapAuthErrorResponse(response)

        expect(mappedResponse).toBe(response)
    })
})
