import { describe, expect, it } from 'vitest'

import {
    classifyAuthFailure,
    isInsufficientScopeChallenge,
    isRejectedTokenChallenge,
    mapErrorToAuthResponse,
    mapKnownErrorMessage,
    withoutStepUpChallenge,
    withResourceMetadata,
} from '@/lib/auth-errors'
import { ErrorCode, PostHogPermissionError } from '@/lib/errors'
import { InsufficientScopeError } from '@/lib/missing-scope'

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

describe('step-up challenge', () => {
    it('points the 403 challenge at the metadata of the origin the client connected to', () => {
        const error = new InsufficientScopeError(['insight:read', 'query:read'])
        const honoResponse = mapErrorToAuthResponse(error)!
        expect(isInsufficientScopeChallenge(honoResponse)).toBe(true)
        expect(classifyAuthFailure(error)).toMatchObject({ missingScope: 'insight:read query:read' })

        const response = withResourceMetadata(honoResponse, new Request('https://mcp.posthog.com/mcp'), null)

        expect(response.status).toBe(403)
        expect(response.headers.get('WWW-Authenticate')).toBe(
            'Bearer error="insufficient_scope", scope="insight:read query:read", resource_metadata="https://mcp.posthog.com/.well-known/oauth-protected-resource/mcp"'
        )
    })
})

describe('withoutStepUpChallenge', () => {
    it('drops the challenge from a step-up 403 so a batch is not replayed', () => {
        const error = new PostHogPermissionError({
            detail: "API key missing required scope 'user:read'",
            missingScope: 'user:read',
            challengeScopes: ['user:read'],
            url: 'https://us.posthog.com/api/users/@me/',
            method: 'GET',
        })
        expect(mapErrorToAuthResponse(error)!.headers.get('WWW-Authenticate')).not.toBeNull()

        const response = mapErrorToAuthResponse(withoutStepUpChallenge(error))!

        expect(response.status).toBe(403)
        expect(response.headers.get('WWW-Authenticate')).toBeNull()
    })
})
