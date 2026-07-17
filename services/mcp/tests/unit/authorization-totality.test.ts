import { beforeEach, describe, expect, it } from 'vitest'

import type { ApiClient } from '@/api/client'
import { MemoryCache } from '@/lib/cache/MemoryCache'
import { ErrorCode } from '@/lib/errors'
import { StateManager } from '@/lib/StateManager'
import type { ApiEffectiveAuthorization } from '@/schema/api'
import type { State } from '@/tools/types'

/**
 * Totality oracle for the authorization resolver.
 *
 * The MCP tool catalog is a projection of the caller's resolved scopes. Every
 * credential kind that can reach the MCP gate as a bearer must resolve through
 * `getAuthorizationMetadata` to EITHER real scopes OR a typed error — never a
 * silent empty (zero-scope) catalog.
 *
 * `CredentialKind` is DERIVED from the resource server's `credential_type`
 * union minus `'session'` (browser-only; never a bearer here). The
 * `satisfies Record<CredentialKind, TotalityCase>` on the case map makes the
 * domain exhaustive: add a 4th token type to `ApiEffectiveAuthorization` and
 * this file stops compiling until a case — and therefore a resolver branch —
 * exists for it. That compile-time gap is the point: a new token type cannot
 * silently ship with an empty catalog.
 */
type CredentialKind = Exclude<ApiEffectiveAuthorization['credential_type'], 'session'>

interface TotalityCase {
    /** An ApiClient wired so this kind resolves to EXPECTED_SCOPES. */
    resolving: () => ApiClient
    /** An ApiClient where this kind's authorization source fails — must throw INVALID_API_KEY. */
    failing: () => ApiClient
}

const EXPECTED_SCOPES = ['insight:read', 'dashboard:read']

// Single JWT segment → not ID-JAG, so it takes the personal-key/OAuth cascade.
const NON_JAG_TOKEN = 'phx_personal_key'

// Header-only `typ: at+jwt` routes the token to the resource server.
function idJagToken(): string {
    const header = Buffer.from(JSON.stringify({ typ: 'at+jwt' })).toString('base64url')
    return `${header}.${Buffer.from('{}').toString('base64url')}.sig`
}

function fakeApi(parts: { apiToken: string; current?: unknown; introspect?: unknown; effective?: unknown }): ApiClient {
    // Any credential source not explicitly wired fails — so removing the
    // resolver branch for one kind can't accidentally succeed via another.
    const fail = { success: false, error: new Error('unexpected credential source') }
    return {
        config: { apiToken: parts.apiToken },
        apiKeys: () => ({ current: async () => parts.current ?? fail }),
        oauth: () => ({ introspect: async () => parts.introspect ?? fail }),
        authorization: () => ({ effective: async () => parts.effective ?? fail }),
    } as unknown as ApiClient
}

const CASES = {
    personal_api_key: {
        resolving: () =>
            fakeApi({
                apiToken: NON_JAG_TOKEN,
                current: {
                    success: true,
                    data: { scopes: EXPECTED_SCOPES, scoped_teams: [], scoped_organizations: [] },
                },
            }),
        failing: () => fakeApi({ apiToken: NON_JAG_TOKEN }),
    },
    oauth: {
        resolving: () =>
            fakeApi({
                apiToken: NON_JAG_TOKEN,
                introspect: {
                    success: true,
                    data: {
                        active: true,
                        scope: EXPECTED_SCOPES.join(' '),
                        scoped_teams: [],
                        scoped_organizations: [],
                    },
                },
            }),
        failing: () => fakeApi({ apiToken: NON_JAG_TOKEN }),
    },
    id_jag: {
        resolving: () =>
            fakeApi({
                apiToken: idJagToken(),
                effective: {
                    success: true,
                    data: {
                        scopes: EXPECTED_SCOPES,
                        scoped_teams: null,
                        scoped_organizations: null,
                        credential_type: 'id_jag',
                    },
                },
            }),
        failing: () => fakeApi({ apiToken: idJagToken() }),
    },
} satisfies Record<CredentialKind, TotalityCase>

describe('authorization totality oracle', () => {
    let cache: MemoryCache<State>

    beforeEach(async () => {
        cache = new MemoryCache('totality')
        await cache.clear()
    })

    it.each(Object.entries(CASES))(
        'resolves real scopes for %s (never a silent empty catalog)',
        async (_kind, testCase) => {
            const sm = new StateManager(cache, testCase.resolving())

            const result = await sm.getAuthorizationMetadata()

            expect(result.scopes).toEqual(EXPECTED_SCOPES)
        }
    )

    it.each(Object.entries(CASES))(
        'fails closed with INVALID_API_KEY for %s on auth failure',
        async (_kind, testCase) => {
            const sm = new StateManager(cache, testCase.failing())

            await expect(sm.getAuthorizationMetadata()).rejects.toThrow(ErrorCode.INVALID_API_KEY)
        }
    )
})
