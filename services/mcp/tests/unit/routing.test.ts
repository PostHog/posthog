import { afterEach, describe, expect, it } from 'vitest'

import { getPublicUrl, getRegionFromRequest, matchAuthServerRedirect } from '@/lib/routing'

describe('getPublicUrl', () => {
    afterEach(() => {
        delete process.env.MCP_TRUST_FORWARDED_HOST
    })

    it.each([undefined, 'false', 'yes'])('keeps the request host when MCP_TRUST_FORWARDED_HOST is %s', (flag) => {
        if (flag !== undefined) {
            process.env.MCP_TRUST_FORWARDED_HOST = flag
        }
        const request = new Request('https://mcp.posthog.com/mcp', {
            headers: { 'X-Forwarded-Host': 'untrusted.example.com' },
        })
        expect(getPublicUrl(request).toString()).toBe('https://mcp.posthog.com/mcp')
    })

    it.each(['true', '1'])('uses X-Forwarded-Host when MCP_TRUST_FORWARDED_HOST is %s', (flag) => {
        process.env.MCP_TRUST_FORWARDED_HOST = flag
        const request = new Request('http://localhost:8787/mcp', {
            headers: { 'X-Forwarded-Host': 'dev-tunnel.example.com', 'X-Forwarded-Proto': 'https' },
        })
        expect(getPublicUrl(request).toString()).toBe('https://dev-tunnel.example.com/mcp')
    })

    it('applies X-Forwarded-Proto behind a TLS-terminating load balancer', () => {
        const request = new Request('http://mcp.us.posthog.com/mcp', {
            headers: { 'X-Forwarded-Proto': 'https' },
        })
        expect(getPublicUrl(request).toString()).toBe('https://mcp.us.posthog.com/mcp')
    })
})

describe('getRegionFromRequest', () => {
    it.each([
        { url: 'https://mcp-eu.posthog.com/mcp', expected: 'eu' },
        { url: 'https://mcp.eu.posthog.com/mcp', expected: 'eu' },
        { url: 'https://mcp.us.posthog.com/mcp', expected: 'us' },
        { url: 'https://mcp.posthog.com/mcp?region=eu', expected: 'eu' },
        { url: 'https://mcp.posthog.com/mcp', expected: null },
    ])('resolves $url to $expected', ({ url, expected }) => {
        expect(getRegionFromRequest(new Request(url))).toBe(expected)
    })

    it('ignores a region hostname in a client-sent X-Forwarded-Host', () => {
        const request = new Request('https://mcp.posthog.com/mcp', {
            headers: { 'X-Forwarded-Host': 'mcp-eu.posthog.com' },
        })
        expect(getRegionFromRequest(request)).toBeNull()
    })
})

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
