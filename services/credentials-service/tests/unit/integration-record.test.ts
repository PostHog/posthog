import { describe, expect, it } from 'vitest'

import type { IntegrationRow } from '@/db/integrations'
import { exposedCredentials, referenceOf, tokenExpiresAt } from '@/integrations/record'
import { parseIfMatch } from '@/integrations/validation'

function row(overrides: Partial<IntegrationRow> = {}): IntegrationRow {
    return {
        id: '0b8a3a8e-4e0a-4f5e-9d7a-1c2b3d4e5f60',
        legacyId: null,
        ownerType: 'team',
        ownerId: 1,
        kind: 'hubspot',
        externalId: 'portal-1',
        authType: 'oauth',
        isSourceRow: false,
        config: {},
        errors: '',
        createdById: null,
        createdAt: new Date(0),
        updatedAt: new Date(0),
        version: 1,
        deletedAt: null,
        refreshDueAt: null,
        refreshState: 'idle',
        refreshAttempts: 0,
        refreshLastError: null,
        refreshLockedUntil: null,
        ...overrides,
    }
}

describe('tokenExpiresAt', () => {
    it.each([
        ['both fields', { refreshed_at: 1_800_000_000, expires_in: 3600 }, '2027-01-15T09:00:00.000Z'],
        ['no expires_in', { refreshed_at: 1_800_000_000 }, null],
        ['no refreshed_at', { expires_in: 3600 }, null],
        ['string values', { refreshed_at: '1800000000', expires_in: '3600' }, null],
        ['a value past the Date range', { refreshed_at: 1e300, expires_in: 1 }, null],
        ['an empty config', {}, null],
    ])('with %s', (_label, config, expected) => {
        expect(tokenExpiresAt(row({ config }))).toBe(expected)
    })
})

describe('exposedCredentials', () => {
    it('drops refresh tokens and client secrets of an oauth row and keeps everything else', () => {
        expect(
            exposedCredentials('oauth', {
                access_token: 'fake-access',
                refresh_token: 'fake-refresh',
                client_secret: 'fake-client-secret',
                api_key: 'fake-key',
                nested: { refresh_token: 'kept-only-when-nested' },
            })
        ).toEqual({
            access_token: 'fake-access',
            api_key: 'fake-key',
            nested: { refresh_token: 'kept-only-when-nested' },
        })
    })

    it('keeps the client secret of a credentials row, which needs it to authenticate', () => {
        expect(
            exposedCredentials('credentials', {
                client_id: 'fake-client-id',
                client_secret: 'fake-client-secret',
                refresh_token: 'fake-refresh',
            })
        ).toEqual({ client_id: 'fake-client-id', client_secret: 'fake-client-secret' })
    })
})

describe('referenceOf', () => {
    it.each([
        ['a migrated row', 42, '42'],
        ['a new row', null, '0b8a3a8e-4e0a-4f5e-9d7a-1c2b3d4e5f60'],
    ])('for %s', (_label, legacyId, expected) => {
        expect(referenceOf(row({ legacyId }))).toBe(expected)
    })
})

describe('parseIfMatch', () => {
    it.each([
        [undefined, null],
        ['3', 3],
        ['"3"', 3],
        [' "12" ', 12],
    ])('reads %j as %j', (header, expected) => {
        expect(parseIfMatch(header)).toBe(expected)
    })

    it.each(['0', '-1', '1.5', 'W/"3"', '*', '"3', '99999999999', '2147483648', ''])('rejects %j', (header) => {
        expect(() => parseIfMatch(header)).toThrow('If-Match must be a version number')
    })
})
