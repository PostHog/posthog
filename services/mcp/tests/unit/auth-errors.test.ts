import { describe, expect, it } from 'vitest'

import { isRejectedTokenChallenge, mapKnownErrorMessage, withResourceMetadata } from '@/lib/auth-errors'
import { ErrorCode } from '@/lib/errors'

describe('rejected token challenge', () => {
    it.each([ErrorCode.INVALID_API_KEY, ErrorCode.INACTIVE_OAUTH_TOKEN])(
        'points a %s rejection at the metadata of the origin the client connected to',
        (code) => {
            const honoResponse = mapKnownErrorMessage(code)!
            expect(isRejectedTokenChallenge(honoResponse)).toBe(true)

            const response = withResourceMetadata(
                honoResponse,
                new Request('https://mcp.posthog.com/mcp?region=eu&features=insights'),
                'eu'
            )

            expect(response.status).toBe(401)
            expect(response.headers.get('WWW-Authenticate')).toMatch(
                /^Bearer error="invalid_token", .*resource_metadata="https:\/\/mcp\.posthog\.com\/\.well-known\/oauth-protected-resource\/mcp\?region=eu"$/
            )
        }
    )
})
