import { SignJWT, type JWK, decodeJwt, exportJWK, exportPKCS8, generateKeyPair, importJWK, jwtVerify } from 'jose'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { handleJwks } from '@/handlers/passthrough'
import { IdTokenReissueError, reissueIdToken } from '@/lib/idtoken'

import { createMockKV } from './helpers'

// Relative to now, so the fixture keeps describing a live token however long this test lives.
const ISSUED_AT = Math.floor(Date.now() / 1000)
const EXPIRES_AT = ISSUED_AT + 3600

interface RegionalKey {
    privateKey: CryptoKey
    publicJwk: JWK
}

async function createRegionalKey(): Promise<RegionalKey> {
    const { privateKey, publicKey } = await generateKeyPair('RS256', { extractable: true })
    return { privateKey, publicJwk: await exportJWK(publicKey) }
}

async function createProxyKeyPem(): Promise<string> {
    const { privateKey } = await generateKeyPair('RS256', { extractable: true })
    return exportPKCS8(privateKey)
}

async function signRegionalIdToken(
    key: RegionalKey,
    claims: Record<string, unknown> = {},
    issuer = 'https://us.posthog.com'
): Promise<string> {
    return new SignJWT({
        email: 'someone@example.com',
        email_verified: true,
        nonce: 'nonce-from-the-client',
        at_hash: 'at-hash-of-the-access-token',
        ...claims,
    })
        .setProtectedHeader({ alg: 'RS256' })
        .setIssuer(issuer)
        .setSubject('018f0000-0000-7000-8000-000000000000')
        .setAudience('us_regional_client_id')
        .setIssuedAt(ISSUED_AT)
        .setExpirationTime(EXPIRES_AT)
        .sign(key.privateKey)
}

function stubRegionalJwks(key: RegionalKey): void {
    // A fresh Response per call: the JWKS handler reads both regions, and a body can be read once.
    vi.stubGlobal(
        'fetch',
        vi.fn(() =>
            Promise.resolve(
                new Response(JSON.stringify({ keys: [key.publicJwk] }), {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                })
            )
        )
    )
}

describe('ID token re-issuance', () => {
    let regionalKey: RegionalKey
    let signingKey: string

    // One key set per file: `reissueIdToken` caches the remote JWKS per region, as a worker
    // isolate does, so a fresh key per test would be rejected by the cached set.
    beforeAll(async () => {
        regionalKey = await createRegionalKey()
        signingKey = await createProxyKeyPem()
    })

    beforeEach(() => {
        stubRegionalJwks(regionalKey)
    })

    afterEach(() => {
        vi.restoreAllMocks()
    })

    it('replaces the regional issuer and audience while preserving the identity claims', async () => {
        const idToken = await signRegionalIdToken(regionalKey)

        const reissued = await reissueIdToken(idToken, {
            region: 'us',
            issuer: 'https://oauth.posthog.com',
            audience: 'proxy_client_id',
            env: { OIDC_SIGNING_KEY: signingKey },
        })

        const claims = decodeJwt(reissued)
        expect(claims.iss).toBe('https://oauth.posthog.com')
        expect(claims.aud).toBe('proxy_client_id')
        expect(claims.sub).toBe('018f0000-0000-7000-8000-000000000000')
        expect(claims.email).toBe('someone@example.com')
        expect(claims.email_verified).toBe(true)
        expect(claims.nonce).toBe('nonce-from-the-client')
        expect(claims.at_hash).toBe('at-hash-of-the-access-token')
    })

    it('copies the lifetime of the regional token rather than extending it', async () => {
        const idToken = await signRegionalIdToken(regionalKey)

        const reissued = await reissueIdToken(idToken, {
            region: 'us',
            issuer: 'https://oauth.posthog.com',
            audience: 'proxy_client_id',
            env: { OIDC_SIGNING_KEY: signingKey },
        })

        const claims = decodeJwt(reissued)
        expect(claims.iat).toBe(ISSUED_AT)
        expect(claims.exp).toBe(EXPIRES_AT)
    })

    it('signs with a key published in the proxy JWKS', async () => {
        const idToken = await signRegionalIdToken(regionalKey)
        const reissued = await reissueIdToken(idToken, {
            region: 'us',
            issuer: 'https://oauth.posthog.com',
            audience: 'proxy_client_id',
            env: { OIDC_SIGNING_KEY: signingKey },
        })

        const response = await handleJwks(
            new Request('https://oauth.posthog.com/.well-known/jwks.json'),
            createMockKV(),
            {
                OIDC_SIGNING_KEY: signingKey,
            }
        )
        const { keys } = (await response.json()) as { keys: JWK[] }
        const header = JSON.parse(atob(reissued.split('.')[0]!)) as { kid: string }
        const signingJwk = keys.find((key) => key.kid === header.kid)

        expect(signingJwk).not.toBeUndefined()
        await expect(jwtVerify(reissued, await importJWK(signingJwk!, 'RS256'))).resolves.toBeDefined()
    })

    it('keeps publishing the regional keys, which sign ID-JAG access tokens', async () => {
        const response = await handleJwks(
            new Request('https://oauth.posthog.com/.well-known/jwks.json'),
            createMockKV(),
            {
                OIDC_SIGNING_KEY: signingKey,
            }
        )

        const { keys } = (await response.json()) as { keys: JWK[] }
        expect(keys.some((key) => key.n === regionalKey.publicJwk.n)).toBe(true)
    })

    it('refuses to sign without a configured key', async () => {
        const idToken = await signRegionalIdToken(regionalKey)

        await expect(
            reissueIdToken(idToken, {
                region: 'us',
                issuer: 'https://oauth.posthog.com',
                audience: 'proxy_client_id',
                env: {},
            })
        ).rejects.toBeInstanceOf(IdTokenReissueError)
    })

    it('refuses to sign a token the region did not sign', async () => {
        const impostorKey = await createRegionalKey()
        const idToken = await signRegionalIdToken(impostorKey)

        await expect(
            reissueIdToken(idToken, {
                region: 'us',
                issuer: 'https://oauth.posthog.com',
                audience: 'proxy_client_id',
                env: { OIDC_SIGNING_KEY: signingKey },
            })
        ).rejects.toBeInstanceOf(IdTokenReissueError)
    })
})
