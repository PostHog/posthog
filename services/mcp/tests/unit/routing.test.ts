import { describe, expect, it } from 'vitest'

import { matchAuthServerRedirect } from '@/lib/routing'

describe('Authorization server redirects', () => {
    const redirectCases = [
        { pathname: '/.well-known/oauth-authorization-server', expectedStatus: 302 },
        { pathname: '/.well-known/jwks.json', expectedStatus: 301 },
        { pathname: '/oauth/authorize/', expectedStatus: 301 },
        { pathname: '/oauth/token/', expectedStatus: 301 },
        { pathname: '/oauth/register/', expectedStatus: 301 },
        { pathname: '/oauth/revoke/', expectedStatus: 301 },
        { pathname: '/oauth/introspect/', expectedStatus: 301 },
        { pathname: '/oauth/userinfo/', expectedStatus: 301 },
    ]

    it.each(redirectCases)('redirects $pathname with status $expectedStatus', ({ pathname, expectedStatus }) => {
        const redirect = matchAuthServerRedirect(pathname)
        expect(redirect).not.toBeUndefined()
        expect(redirect!.status).toBe(expectedStatus)
    })

    const noRedirectCases = [
        { pathname: '/' },
        { pathname: '/mcp' },
        { pathname: '/sse' },
        { pathname: '/.well-known/oauth-protected-resource' },
        { pathname: '/.well-known/oauth-protected-resource/mcp' },
    ]

    it.each(noRedirectCases)('does not redirect $pathname', ({ pathname }) => {
        expect(matchAuthServerRedirect(pathname)).toBeUndefined()
    })
})
