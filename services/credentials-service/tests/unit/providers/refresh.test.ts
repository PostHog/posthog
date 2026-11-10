import { describe, expect, it } from 'vitest'

import { providerSpec } from '@/providers'
import { OAUTH_REFRESH } from '@/providers/defaults'
import {
    classifyRefreshFailure,
    isTerminalFailure,
    type RefreshFailureReason,
    refreshBackoffSeconds,
    refreshDueAt,
} from '@/providers/refresh'
import type { RefreshSpec } from '@/providers/schema'

const STATIC: RefreshSpec = { ...OAUTH_REFRESH, mode: 'static' }
const REFRESHED_AT = new Date('2026-11-10T12:00:00Z')

function refreshOf(kind: string): RefreshSpec {
    const refresh = providerSpec(kind)?.refresh
    if (!refresh) {
        throw new Error(`${kind} has no refresh spec`)
    }
    return refresh
}

describe('refresh_due_at', () => {
    it.each<[string, RefreshSpec | undefined, Date | null, number | null, string | null]>([
        ['half the lifetime after the last refresh', STATIC, REFRESHED_AT, 3600, '2026-11-10T12:30:00.000Z'],
        ['a fractional lifetime', STATIC, REFRESHED_AT, 3599, '2026-11-10T12:29:59.500Z'],
        ['nothing when the provider sent no lifetime', STATIC, REFRESHED_AT, null, null],
        // Python reads `not expires_in`, so 0 means absent and the row never comes due.
        ['nothing for a zero lifetime', STATIC, REFRESHED_AT, 0, null],
        ['nothing for a row never refreshed', STATIC, null, 3600, null],
        ['nothing for a kind that does not refresh', undefined, REFRESHED_AT, 3600, null],
        [
            'the default lifetime when Salesforce sends none',
            refreshOf('salesforce'),
            REFRESHED_AT,
            null,
            '2026-11-10T12:30:00.000Z',
        ],
        [
            'the lifetime Salesforce sends over its default',
            refreshOf('salesforce'),
            REFRESHED_AT,
            7200,
            '2026-11-10T13:00:00.000Z',
        ],
    ])('is %s', (_, refresh, refreshedAt, expiresInSeconds, expected) => {
        expect(refreshDueAt(refresh, { refreshedAt, expiresInSeconds })?.toISOString() ?? null).toBe(expected)
    })

    it.each([
        [1, 120],
        [2, 240],
        [3, 480],
        [5, 1920],
        [6, 3600],
        [40, 3600],
        // The count includes the failure that was just recorded, so it is never below one.
        [0, 120],
    ])('backs off %i failures in a row by %i seconds', (failures, seconds) => {
        expect(refreshBackoffSeconds(STATIC, failures)).toBe(seconds)
    })
})

describe('refresh failure classification', () => {
    it.each<[string, string, number, unknown, RefreshFailureReason]>([
        ['an OAuth invalid_grant', 'google-ads', 400, { error: 'invalid_grant' }, 'invalid_grant'],
        ['an OAuth invalid_client', 'google-ads', 401, { error: 'invalid_client' }, 'invalid_client'],
        ['a throttled call', 'google-ads', 429, { error: 'rate_limit' }, 'rate_limited'],
        ['a provider outage', 'google-ads', 503, 'Service Unavailable', 'http_5xx'],
        ['an unknown 4xx', 'google-ads', 400, { error: 'invalid_request' }, 'other'],
        ['an HTML body', 'linear', 400, '<html>', 'other'],
        ['a deleted HubSpot portal', 'hubspot', 400, { status: 'BAD_HUB', error: 'access_denied' }, 'invalid_grant'],
        // A 5xx says nothing about the grant, even with BAD_HUB in it.
        ['BAD_HUB on a HubSpot 5xx', 'hubspot', 502, { status: 'BAD_HUB' }, 'http_5xx'],
        ['BAD_HUB from another provider', 'salesforce', 400, { status: 'BAD_HUB' }, 'other'],
    ])('classifies %s', (_, kind, status, body, expected) => {
        expect(classifyRefreshFailure(refreshOf(kind), status, body)).toBe(expected)
    })

    it.each<[string, Partial<RefreshSpec>, unknown, number, number]>([
        // Reddit reports a dead grant as `{"message": "Bad Request", "error": 400}`.
        [
            'an exact status and a numeric value',
            { terminalErrors: [{ path: 'error', equals: 400, status: 400 }] },
            { error: 400 },
            400,
            401,
        ],
        // Meta nests its error, and code 190 means the token is dead.
        [
            'a nested path below a status',
            { terminalErrors: [{ path: 'error.code', equals: 190, statusBelow: 500 }] },
            { error: { code: 190 } },
            400,
            500,
        ],
    ])('matches a provider-specific terminal error by %s', (_, change, body, matching, notMatching) => {
        const refresh = { ...STATIC, ...change }
        expect(classifyRefreshFailure(refresh, matching, body)).toBe('invalid_grant')
        expect(classifyRefreshFailure(refresh, notMatching, body)).not.toBe('invalid_grant')
    })

    it.each<[RefreshFailureReason, number, boolean]>([
        ['invalid_grant', 4, false],
        ['invalid_grant', 5, true],
        ['unreadable_secret', 0, true],
        ['invalid_token_uri', 0, true],
        // A fix on PostHog's side must let these rows recover, however long the streak.
        ['invalid_client', 50, false],
        ['http_5xx', 50, false],
        ['network', 50, false],
    ])('treats %s with a grant streak of %i as terminal: %s', (reason, streak, terminal) => {
        expect(isTerminalFailure(STATIC, reason, streak)).toBe(terminal)
    })
})
