import { describe, expect, it } from 'vitest'

import { redactRecordingUrls, redactSensitiveUrl } from '@/lib/redact-url'

describe('redactSensitiveUrl', () => {
    it.each([
        // credential-like query params → value redacted, key + path preserved
        ['https://app.example.com/reset?token=abc123', 'https://app.example.com/reset?token=[REDACTED]'],
        ['https://x.io/v1?api_key=sk_live_123', 'https://x.io/v1?api_key=[REDACTED]'],
        ['https://x.io/v1?apiKey=sk_live_123', 'https://x.io/v1?apiKey=[REDACTED]'],
        ['https://x.io/login?password=hunter2', 'https://x.io/login?password=[REDACTED]'],
        ['https://x.io/s?sig=deadbeef&signature=cafe', 'https://x.io/s?sig=[REDACTED]&signature=[REDACTED]'],
        // OAuth implicit-flow tokens live in the fragment as key=value pairs
        [
            'https://x.io/cb#access_token=tok123&token_type=bearer&state=xyz',
            'https://x.io/cb#access_token=[REDACTED]&token_type=[REDACTED]&state=xyz',
        ],
        // sensitive param mixed with benign params → only the sensitive value goes
        [
            'https://x.io/p?page=2&utm_source=email&auth_token=secret',
            'https://x.io/p?page=2&utm_source=email&auth_token=[REDACTED]',
        ],
    ])('redacts credential-like values in %s', (input, expected) => {
        expect(redactSensitiveUrl(input)).toBe(expected)
    })

    it.each([
        // no query/fragment → untouched
        ['https://app.example.com/dashboard/42'],
        // benign query params → untouched
        ['https://x.io/search?q=posthog&page=3&country_code=US'],
        // plain anchor fragment (no key=value) → untouched
        ['https://x.io/docs#installation'],
        // token-level matching: substrings must not trigger redaction
        ['https://x.io/p?keyword=analytics&passenger=1'],
        // empty value → left as-is (nothing to leak)
        ['https://x.io/p?token='],
    ])('leaves %s unchanged', (input) => {
        expect(redactSensitiveUrl(input)).toBe(input)
    })

    it.each([
        ['', ''],
        [undefined as unknown as string, undefined as unknown as string],
    ])('returns non-URL input %s unchanged', (input, expected) => {
        expect(redactSensitiveUrl(input)).toBe(expected)
    })
})

describe('redactRecordingUrls', () => {
    it('redacts start_url on each recording, preserving other fields', () => {
        const results = [
            { id: 'a', start_url: 'https://x.io/reset?token=abc', distinct_id: 'd1' },
            { id: 'b', start_url: 'https://x.io/home', distinct_id: 'd2' },
        ]
        expect(redactRecordingUrls(results)).toEqual([
            { id: 'a', start_url: 'https://x.io/reset?token=[REDACTED]', distinct_id: 'd1' },
            { id: 'b', start_url: 'https://x.io/home', distinct_id: 'd2' },
        ])
    })

    it('ignores recordings without a string start_url and non-array input', () => {
        expect(redactRecordingUrls([{ id: 'a', start_url: null }, { id: 'b' }])).toEqual([
            { id: 'a', start_url: null },
            { id: 'b' },
        ])
        expect(redactRecordingUrls({ columns: [], results: [] })).toEqual({ columns: [], results: [] })
    })
})
