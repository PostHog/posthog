import { describe, expect, it } from 'vitest'

import {
    encodePostHogIdForPath,
    isValidApiToken,
    isValidHostname,
    isValidOrganizationId,
    isValidProjectId,
    isValidRegion,
    redactSecrets,
    shouldHonorForwardedHost,
} from '@/lib/validation'

describe('validation', () => {
    describe('isValidProjectId', () => {
        it.each([
            ['numeric', '123', true],
            ['multi-digit numeric', '99999999', true],
            ['@current literal', '@current', true],
            ['leading zero numeric', '0123', true],
        ])('accepts %s', (_, value, expected) => {
            expect(isValidProjectId(value)).toBe(expected)
        })

        it.each([
            ['path traversal segment', '123/../private'],
            ['trailing slash', '123/'],
            ['url query injection', '123?refresh=true'],
            ['url fragment', '123#frag'],
            ['CR injection', '123\r\nX-Evil: 1'],
            ['LF injection', '123\nfoo'],
            ['NUL byte', '123\x00'],
            ['negative number', '-1'],
            ['decimal', '12.3'],
            ['scientific notation', '1e10'],
            ['empty string', ''],
            ['whitespace', ' 123'],
            ['javascript scheme', 'javascript:alert(1)'],
            ['encoded slash', '123%2Fadmin'],
            ['unicode lookalike for at-current', '＠current'],
            ['null', null],
            ['number type', 123],
            ['array', ['123']],
        ])('rejects %s', (_, value) => {
            expect(isValidProjectId(value)).toBe(false)
        })
    })

    describe('isValidOrganizationId', () => {
        it.each([
            ['lowercase UUID', '01958a09-3ec3-7000-3a82-d5d2729fdfe1', true],
            ['uppercase UUID', '01958A09-3EC3-7000-3A82-D5D2729FDFE1', true],
            ['@current literal', '@current', true],
        ])('accepts %s', (_, value, expected) => {
            expect(isValidOrganizationId(value)).toBe(expected)
        })

        it.each([
            ['UUID with path traversal', '01958a09-3ec3-7000-3a82-d5d2729fdfe1/../admin'],
            ['truncated UUID', '01958a09-3ec3-7000-3a82-d5d2729fdfe'],
            ['UUID with CRLF', '01958a09-3ec3-7000-3a82-d5d2729fdfe1\r\nX-Evil: 1'],
            ['UUID with query string', '01958a09-3ec3-7000-3a82-d5d2729fdfe1?delete=true'],
            ['empty', ''],
            ['plain string', 'my-org'],
            ['shell metachars', 'org;rm -rf /'],
            ['null', null],
            ['undefined', undefined],
        ])('rejects %s', (_, value) => {
            expect(isValidOrganizationId(value)).toBe(false)
        })
    })

    describe('isValidApiToken', () => {
        it.each([
            ['phx_ token', 'phx_ABCDEF1234567890_-abcdefghij', true],
            ['pha_ token', 'pha_ABCDEF1234567890_-abcdefghij', true],
            ['long pha_ token', 'pha_' + 'a'.repeat(64), true],
        ])('accepts %s', (_, value, expected) => {
            expect(isValidApiToken(value)).toBe(expected)
        })

        it.each([
            ['empty', ''],
            ['wrong prefix', 'phs_abc123abc123'],
            ['no prefix', 'abcdefghij1234567890'],
            ['too short', 'phx_short'],
            ['CR injection (header smuggling)', 'phx_abcdefgh\r\nX-Injected: 1'],
            ['LF injection', 'phx_abcdefgh\nX-Injected: 1'],
            ['NUL byte', 'phx_abcdefgh\x00more'],
            ['space', 'phx_abc def123'],
            ['Bearer prefix replay', 'Bearer phx_abcdefghij'],
            ['unicode whitespace', 'phx_abcdefgh\u200b1234'],
            ['pipe (shell metachar)', 'phx_abc|cat /etc/passwd'],
            ['null', null],
            ['undefined', undefined],
        ])('rejects %s', (_, value) => {
            expect(isValidApiToken(value)).toBe(false)
        })
    })

    describe('isValidRegion', () => {
        it.each([
            ['us', true],
            ['eu', true],
            ['US', true],
            ['EU', true],
        ])('accepts %s', (value, expected) => {
            expect(isValidRegion(value)).toBe(expected)
        })

        it.each([
            ['', false],
            ['ap', false],
            ['us;DROP TABLE', false],
            ['us\nfoo', false],
            ['../us', false],
        ])('rejects %s', (value, expected) => {
            expect(isValidRegion(value)).toBe(expected)
        })
    })

    describe('isValidHostname', () => {
        it.each([
            ['mcp.posthog.com', true],
            ['localhost', true],
            ['my-tunnel.ngrok-free.dev', true],
            ['example.com:8787', true],
            ['127.0.0.1:3000', true],
        ])('accepts %s', (value, expected) => {
            expect(isValidHostname(value)).toBe(expected)
        })

        it.each([
            ['', false],
            ['evil.com\r\nHost: target.com', false],
            ['evil.com/../path', false],
            ['evil.com?query=1', false],
            ['evil.com#frag', false],
            ['javascript:alert(1)', false],
            ['10.0.0.1:notaport', false],
            ['10.0.0.1:99999999', false],
            ['has space', false],
        ])('rejects %s', (value, expected) => {
            expect(isValidHostname(value)).toBe(expected)
        })
    })

    describe('shouldHonorForwardedHost', () => {
        it('honors X-Forwarded-Host on production proxy hostnames', () => {
            expect(shouldHonorForwardedHost('mcp.posthog.com', 'mcp.posthog.com')).toBe(true)
            expect(shouldHonorForwardedHost('mcp-eu.posthog.com', 'mcp-eu.posthog.com')).toBe(true)
        })

        it('honors X-Forwarded-Host on local dev hostnames (ngrok / cloudflared use case)', () => {
            expect(shouldHonorForwardedHost('my-tunnel.ngrok-free.dev', 'localhost')).toBe(true)
            expect(shouldHonorForwardedHost('my-tunnel.ngrok-free.dev', '127.0.0.1')).toBe(true)
        })

        it('refuses to honor X-Forwarded-Host on unknown request hostnames', () => {
            // Even though the value itself is plausible, the request didn't
            // come from a hostname we trust to set that header. Honoring it
            // would let an attacker poison OAuth metadata discovery.
            expect(shouldHonorForwardedHost('attacker.example.com', 'public-mcp-host.example.com')).toBe(false)
        })

        it('refuses syntactically hostile X-Forwarded-Host values', () => {
            expect(shouldHonorForwardedHost('attacker.example.com\r\nX-Evil: 1', 'mcp.posthog.com')).toBe(false)
            expect(shouldHonorForwardedHost('attacker.example.com/foo', 'mcp.posthog.com')).toBe(false)
            expect(shouldHonorForwardedHost('', 'mcp.posthog.com')).toBe(false)
        })
    })

    describe('encodePostHogIdForPath', () => {
        it('passes through plain numeric IDs', () => {
            expect(encodePostHogIdForPath('12345')).toBe('12345')
        })

        it('escapes path-traversal-style characters even though entry validation should have rejected them', () => {
            // This is the defense-in-depth check: even if the entry-level
            // validator regresses, the URL builder still cannot smuggle
            // additional path segments.
            expect(encodePostHogIdForPath('123/../admin')).toBe('123%2F..%2Fadmin')
            expect(encodePostHogIdForPath('123?delete=true')).toBe('123%3Fdelete%3Dtrue')
        })
    })

    describe('redactSecrets', () => {
        it('strips bearer tokens from messages', () => {
            const before = 'Request failed with Bearer phx_abcdef1234567890ABCDEF embedded'
            expect(redactSecrets(before)).toBe('Request failed with Bearer [REDACTED] embedded')
        })

        it('strips bare PostHog tokens from messages', () => {
            const before = 'token=phx_abcdef1234567890ABCDEF and pha_zzzzzzzzzzzz9999'
            expect(redactSecrets(before)).toBe('token=[REDACTED_TOKEN] and [REDACTED_TOKEN]')
        })

        it('strips upstream-style API keys', () => {
            // Synthetic fixture — avoid real-vendor prefixes that secret
            // scanners would block on the way to remote.
            const fixture = 'invalid api key ' + 'k' + 'ey_test_' + 'abcdefghij1234567890abcdef provided'
            expect(redactSecrets(fixture)).toContain('[REDACTED_KEY]')
            expect(redactSecrets(fixture)).not.toContain('abcdefghij1234567890abcdef')
        })

        it('leaves benign text unchanged', () => {
            expect(redactSecrets('hello world')).toBe('hello world')
        })
    })
})
