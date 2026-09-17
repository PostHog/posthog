import { describe, expect, it } from 'vitest'

import { redactUrlSecrets } from '@/lib/redact-url-secrets'

// Every URL below is invented. A session URL an agent reads is whatever the user's browser
// was pointed at, so an OAuth callback, a magic link, or a signed-in page can carry a live
// credential into a tool result and from there into the agent's transcript.
const cases: { name: string; url: string; expected: string }[] = [
    {
        name: 'redacts an access token, keeping the other parameters',
        url: 'https://app.example.com/callback?access_token=nx41ZmFrZXRva2VuMDAx&page=2',
        expected: 'https://app.example.com/callback?access_token=[redacted]&page=2',
    },
    {
        name: 'redacts an authorization code and a refresh token',
        url: 'https://app.example.com/oauth?code=4%2F0Afake-code&refresh_token=1%2F%2F0gfake',
        expected: 'https://app.example.com/oauth?code=[redacted]&refresh_token=[redacted]',
    },
    {
        name: 'redacts an email address in a parameter',
        url: 'https://app.example.com/billing?email=someone%40example.com&tab=invoices',
        expected: 'https://app.example.com/billing?email=[redacted]&tab=invoices',
    },
    {
        name: 'redacts an email address in the path',
        url: 'https://app.example.com/users/someone%40example.com/settings',
        expected: 'https://app.example.com/users/[redacted]/settings',
    },
    {
        name: 'redacts an implicit-flow token in the fragment',
        url: 'https://app.example.com/home#access_token=nx41ZmFrZXRva2VuMDAx&expires_in=3600',
        expected: 'https://app.example.com/home#access_token=[redacted]&expires_in=3600',
    },
    {
        name: 'redacts a fragment that is one opaque token',
        url: 'https://app.example.com/#f4k3t0k3nf4k3t0k3nf4k3',
        expected: 'https://app.example.com/#[redacted]',
    },
    {
        name: 'keeps a fragment that is a client-side route',
        url: 'https://app.example.com/#/settings/billing',
        expected: 'https://app.example.com/#/settings/billing',
    },
    {
        name: 'drops credentials held in the userinfo',
        url: 'https://someone:fakepassword@internal.example.com/dashboard',
        expected: 'https://internal.example.com/dashboard',
    },
    {
        name: 'redacts a JWT anywhere in the URL',
        url: 'https://app.example.com/verify/eyJhbGciOiJmYWtlIn0.eyJzdWIiOiJmYWtlIn0.c2lnbmF0dXJl',
        expected: 'https://app.example.com/verify/[redacted]',
    },
    {
        name: 'redacts an API key on a relative URL',
        url: '/integrations/setup?api_key=f4k3k3yf4k3k3y&step=2',
        expected: '/integrations/setup?api_key=[redacted]&step=2',
    },
    {
        name: 'returns an analytics URL unchanged',
        url: 'https://example.com/pricing?utm_source=newsletter&utm_campaign=launch#features',
        expected: 'https://example.com/pricing?utm_source=newsletter&utm_campaign=launch#features',
    },
    {
        name: 'leaves an empty parameter alone',
        url: 'https://app.example.com/callback?access_token=&state=1',
        expected: 'https://app.example.com/callback?access_token=&state=1',
    },
]

describe('redactUrlSecrets', () => {
    it.each(cases)('$name', ({ url, expected }) => {
        expect(redactUrlSecrets(url)).toBe(expected)
    })
})
