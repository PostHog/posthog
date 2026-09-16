import { describe, expect, it } from 'vitest'

import { getPublicOrigin, matchAuthServerRedirect, PUBLIC_ORIGIN_HEADER } from '@/lib/routing'

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

describe('getPublicOrigin', () => {
    const originCases: { label: string; headers: Record<string, string>; expected: string }[] = [
        {
            label: 'the proxy header, which survives an ingress that rewrites X-Forwarded-Host',
            headers: {
                [PUBLIC_ORIGIN_HEADER]: 'https://mcp.posthog.com',
                'X-Forwarded-Host': 'mcp.us.posthog.com',
            },
            expected: 'https://mcp.posthog.com',
        },
        {
            label: 'the forwarded host when no proxy header is set',
            headers: { 'X-Forwarded-Host': 'mcp.eu.posthog.com', 'X-Forwarded-Proto': 'https' },
            expected: 'https://mcp.eu.posthog.com',
        },
        { label: 'the request URL when nothing is forwarded', headers: {}, expected: 'http://localhost:8787' },
        {
            label: 'the request URL when the proxy header is malformed',
            headers: { [PUBLIC_ORIGIN_HEADER]: 'not-a-url' },
            expected: 'http://localhost:8787',
        },
    ]

    it.each(originCases)('resolves $label', ({ headers, expected }) => {
        const request = new Request('http://localhost:8787/mcp', { headers })
        expect(getPublicOrigin(request)).toBe(expected)
    })
})
