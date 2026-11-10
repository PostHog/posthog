import { describe, expect, it } from 'vitest'

import { PROVIDER_SPECS, providerSpec } from '@/providers'
import { OAUTH_REFRESH } from '@/providers/defaults'
import { applyOverrides } from '@/providers/overrides'
import { providerSpecSchema, type ProviderSpec } from '@/providers/schema'
import { ProviderSpecError, validateProviderSpecs } from '@/providers/validate'

const VALID: ProviderSpec = {
    kind: 'example',
    label: 'Example',
    authTypes: { default: 'oauth', others: [] },
    authorize: { url: 'https://example.com/authorize', scope: 'read', pkce: false, opaqueState: false },
    token: { url: 'https://example.com/token', auth: 'client_secret_post' },
    clientSecretKeys: { clientId: 'EXAMPLE_CLIENT_ID', clientSecret: 'EXAMPLE_CLIENT_SECRET' },
    tokenInfo: { idPath: 'id', namePath: 'name' },
    refresh: { ...OAUTH_REFRESH, mode: 'static' },
    resolveExposes: ['access_token'],
    displayName: { configPaths: ['name'] },
}

function issues(spec: unknown): string[] {
    const result = providerSpecSchema.safeParse(spec)
    return result.success ? [] : result.error.issues.map((issue) => issue.message)
}

describe('provider specs', () => {
    it.each(PROVIDER_SPECS.map((spec) => [spec.kind, spec]))('%s passes validation', (_, spec) => {
        expect(issues(spec)).toEqual([])
    })

    it('registers each kind once and boots with the registry', () => {
        expect(() => validateProviderSpecs(PROVIDER_SPECS)).not.toThrow()
        expect(providerSpec('slack')?.kind).toBe('slack')
        expect(providerSpec('not-a-kind')).toBeUndefined()
    })

    it('reports every problem in one error, including a duplicate kind', () => {
        const broken = { ...VALID, resolveExposes: ['refresh_token'] }
        let error: unknown
        try {
            validateProviderSpecs([VALID, VALID, broken])
        } catch (caught) {
            error = caught
        }
        expect(error).toBeInstanceOf(ProviderSpecError)
        expect((error as ProviderSpecError).problems).toEqual([
            'example: the kind is registered twice',
            'example: the kind is registered twice',
            'example: resolveExposes: must not expose the refresh token',
        ])
    })

    it.each<[string, Record<string, unknown>, string]>([
        ['a refresh token in resolve', { resolveExposes: ['access_token', 'refresh_token'] }, 'must not expose'],
        ['an oauth kind with no authorize leg', { authorize: undefined }, 'needs `authorize`'],
        [
            'an authorize leg on a kind without oauth',
            { authTypes: { default: 'token', others: [] } },
            'only an oauth kind',
        ],
        ['a plain http token URL', { token: { url: 'http://example.com/token', auth: 'client_secret_post' } }, 'https'],
        ['a token endpoint without client keys', { clientSecretKeys: undefined }, 'needs `clientSecretKeys`'],
        ['a code exchange without token info', { tokenInfo: undefined }, 'needs `tokenInfo`'],
        [
            'a signing key as a client secret',
            { clientSecretKeys: { clientId: 'EXAMPLE_CLIENT_ID', clientSecret: '__CALLER_KEY_WEB' } },
            'platform-secret name',
        ],
        [
            'a backoff cap below its base',
            { refresh: { ...OAUTH_REFRESH, mode: 'static', backoff: { baseSeconds: 600, maxSeconds: 60 } } },
            'backoff max',
        ],
        [
            'a refresh fraction of a whole lifetime',
            { refresh: { ...OAUTH_REFRESH, mode: 'static', refreshAtLifetimeFraction: 1 } },
            '',
        ],
        ['an unknown refresh mode', { refresh: { ...OAUTH_REFRESH, mode: 'sometimes' } }, ''],
        ['a field the DSL does not know', { tokenUrl: 'https://example.com/token' }, ''],
        ['the default auth type listed again', { authTypes: { default: 'oauth', others: ['oauth'] } }, 'again'],
        [
            'custom params without the state',
            { authorize: { ...VALID.authorize, params: [['client_id', '{client_id}']] } },
            'must send `{state}`',
        ],
        [
            'custom params on a PKCE kind without the challenge',
            { authorize: { ...VALID.authorize, pkce: true, params: [['state', '{state}']] } },
            '`{code_challenge}`',
        ],
        [
            'custom params and extra params together',
            { authorize: { ...VALID.authorize, params: [['state', '{state}']], extraParams: [['a', 'b']] } },
            'cannot have `extraParams`',
        ],
        [
            'an unknown placeholder',
            { authorize: { ...VALID.authorize, extraParams: [['secret', '{client_secret}']] } },
            'unknown placeholder {client_secret}',
        ],
        [
            'a URL placeholder with no value source',
            { authorize: { ...VALID.authorize, url: 'https://example.com/{tenant}/authorize' } },
            'name the same values',
        ],
        [
            'a refresh with nothing to refresh against',
            {
                authorize: undefined,
                authTypes: { default: 'credentials', others: [] },
                token: undefined,
                clientSecretKeys: undefined,
            },
            'refresh needs',
        ],
    ])('rejects %s', (_, change, message) => {
        const found = issues({ ...VALID, ...change })
        expect(found.length).toBeGreaterThan(0)
        expect(found.join('\n')).toContain(message)
    })

    it('applies an override without erasing what it leaves out', () => {
        const spec: ProviderSpec = {
            ...VALID,
            overrides: {
                region: { EU: { token: { url: 'https://eu.example.com/token', revokeUrl: undefined } } },
                environment: { dev: { authorize: { scope: 'read write' } } },
            },
        }
        const eu = applyOverrides(spec, { environment: 'dev', region: 'EU' })
        expect(eu.token).toEqual({ url: 'https://eu.example.com/token', auth: 'client_secret_post' })
        expect(eu.authorize?.scope).toBe('read write')
        expect(eu.authorize?.url).toBe(VALID.authorize?.url)
        expect(applyOverrides(spec, { region: 'US' })).toEqual(spec)
    })
})
