import { describe, expect, it } from 'vitest'

import { redactUrlCredentials, redactUrlCredentialsDeep } from '@/lib/url-credential-redaction'

describe('redactUrlCredentials', () => {
    it.each([
        [
            'https://app.example.com/callback?code=fake-auth-code-123&state=fake-state',
            'https://app.example.com/callback?code=[REDACTED]&state=[REDACTED]',
        ],
        [
            'https://app.example.com/#access_token=fake.jwt.value&token_type=bearer&expires_in=3600',
            'https://app.example.com/#access_token=[REDACTED]&token_type=bearer&expires_in=3600',
        ],
        [
            'https://files.example.com/a.pdf?X-Amz-Credential=FAKEKEY&X-Amz-Signature=deadbeef&X-Amz-Expires=60',
            'https://files.example.com/a.pdf?X-Amz-Credential=[REDACTED]&X-Amz-Signature=[REDACTED]&X-Amz-Expires=60',
        ],
        [
            'https://api.example.com/v1?apiKey=fake-key&client_secret=fake-secret&page=2',
            'https://api.example.com/v1?apiKey=[REDACTED]&client_secret=[REDACTED]&page=2',
        ],
        [
            'https://example.com/login?redirect_uri=https%3A%2F%2Fexample.com%2Fcb%3Fcode%3Dfake-code%26lang%3Den',
            'https://example.com/login?redirect_uri=https%3A%2F%2Fexample.com%2Fcb%3Fcode%3D[REDACTED]%26lang%3Den',
        ],
        [
            'url,count\nhttps://example.com/cb?code=fake-code,3\nhttps://example.com/pricing?plan=pro,5',
            'url,count\nhttps://example.com/cb?code=[REDACTED],3\nhttps://example.com/pricing?plan=pro,5',
        ],
        [
            'https://example.com/v1?api-key=fake-key&access-key=fake-access&secret_key=fake-secret&page=2',
            'https://example.com/v1?api-key=[REDACTED]&access-key=[REDACTED]&secret_key=[REDACTED]&page=2',
        ],
        [
            'https://example.com/login?redirect_uri=https://example.com/cb?code=fake-code&lang=en',
            'https://example.com/login?redirect_uri=https://example.com/cb?code=[REDACTED]&lang=en',
        ],
        ['{"url":"https://example.com/cb?code=fake-code"}', '{"url":"https://example.com/cb?code=[REDACTED]"}'],
    ])('masks credential values in %s', (input, expected) => {
        expect(redactUrlCredentials(input)).toBe(expected)
    })

    it.each([
        'https://example.com/search?q=shoes&country_code=US&author=someone&utm_source=newsletter',
        'SELECT count() FROM events WHERE code = 1',
        'https://example.com/cb?code=',
    ])('keeps non-credential text unchanged: %s', (input) => {
        expect(redactUrlCredentials(input)).toBe(input)
    })
})

describe('redactUrlCredentialsDeep', () => {
    it('masks strings at any depth and keeps other values', () => {
        const results = [
            { breakdown_value: 'https://example.com/cb?code=fake-code', count: 4, data: [1, 2] },
            ['https://example.com/cb?token=fake-token', null, true],
            { 'https://example.com/cb?code=fake-a': 1, 'https://example.com/cb?code=fake-b': 2 },
        ]

        expect(redactUrlCredentialsDeep(results)).toEqual([
            { breakdown_value: 'https://example.com/cb?code=[REDACTED]', count: 4, data: [1, 2] },
            ['https://example.com/cb?token=[REDACTED]', null, true],
            { 'https://example.com/cb?code=[REDACTED]': 1, 'https://example.com/cb?code=[REDACTED] (2)': 2 },
        ])
    })
})
