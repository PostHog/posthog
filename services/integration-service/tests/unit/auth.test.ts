import { SignJWT } from 'jose'
import { describe, expect, it } from 'vitest'

import { JwtVerifier, bearerToken } from '@/auth/jwt.js'
import type { ClientRegistryLoader } from '@/auth/registry.js'
import { AUDIENCE, AuthError, type ClientRegistry } from '@/auth/types.js'

const DW_KEY_NEW = 'dw-signing-key-new'
const DW_KEY_OLD = 'dw-signing-key-old'
const DJANGO_KEY = 'django-signing-key'

const REGISTRY: ClientRegistry = {
    'temporal-worker-data-warehouse': { keys: [DW_KEY_NEW, DW_KEY_OLD], providers: ['google-ads', 'stripe'] },
    'posthog-django': { keys: [DJANGO_KEY], providers: ['google-ads', 'stripe', 'hubspot'] },
}

function verifier(registry: ClientRegistry = REGISTRY): JwtVerifier {
    const loader = { entryFor: (caller: string) => registry[caller] ?? null } as ClientRegistryLoader
    return new JwtVerifier(loader)
}

async function mint(opts: {
    key: string
    caller: string
    keys?: string[]
    previousUsed?: string[]
    audience?: string
    expiresIn?: string
}): Promise<string> {
    let builder = new SignJWT({
        caller: opts.caller,
        keys: opts.keys ?? ['GOOGLE_ADS_APP_CLIENT_SECRET'],
        ...(opts.previousUsed ? { previous_used: opts.previousUsed } : {}),
    })
        .setProtectedHeader({ alg: 'HS256' })
        .setAudience(opts.audience ?? AUDIENCE)
        .setIssuedAt()
    builder = builder.setExpirationTime(opts.expiresIn ?? '5m')
    return builder.sign(new TextEncoder().encode(opts.key))
}

// Resolves to the rejection reason, or throws if the token was accepted. Deliberately
// asserts by throwing rather than with `expect` inside a catch, which would make the
// assertion conditional on the rejection happening at all.
async function reasonFor(promise: Promise<unknown>): Promise<string> {
    const outcome = await promise.then(
        () => null,
        (err: unknown) => err
    )
    if (!(outcome instanceof AuthError)) {
        throw new Error(`expected the token to be rejected with an AuthError, got ${String(outcome)}`)
    }
    return outcome.reason
}

describe('jwt verification', () => {
    it('accepts a well-formed token and returns the caller allowlist and requested keys', async () => {
        const token = await mint({ key: DW_KEY_NEW, caller: 'temporal-worker-data-warehouse' })
        const { identity } = await verifier().verifyToken(token)

        expect(identity.caller).toBe('temporal-worker-data-warehouse')
        expect(identity.requestedKeys).toEqual(['GOOGLE_ADS_APP_CLIENT_SECRET'])
        expect([...identity.allowedProviders].sort()).toEqual(['google-ads', 'stripe'])
    })

    // The whole reason the signing key is per caller rather than fleet-wide: a key leaked
    // from one pod must not let an attacker assume a caller with a wider allowlist.
    it('rejects a token signed with one caller key but claiming to be another caller', async () => {
        const forged = await mint({ key: DW_KEY_NEW, caller: 'posthog-django' })
        expect(await reasonFor(verifier().verifyToken(forged))).toBe('bad_signature')
    })

    it('accepts a token signed with a retired key still listed in the caller key set', async () => {
        const token = await mint({ key: DW_KEY_OLD, caller: 'temporal-worker-data-warehouse' })
        await expect(verifier().verifyToken(token)).resolves.toBeDefined()
    })

    it('rejects a token signed with a key that has been removed from the set', async () => {
        const token = await mint({ key: 'a-key-nobody-lists', caller: 'temporal-worker-data-warehouse' })
        expect(await reasonFor(verifier().verifyToken(token))).toBe('bad_signature')
    })

    it('rejects an expired token', async () => {
        const token = await mint({ key: DW_KEY_NEW, caller: 'temporal-worker-data-warehouse', expiresIn: '-1s' })
        expect(await reasonFor(verifier().verifyToken(token))).toBe('expired')
    })

    it('rejects a token minted for a different audience', async () => {
        const token = await mint({
            key: DW_KEY_NEW,
            caller: 'temporal-worker-data-warehouse',
            audience: 'posthog:recording_api',
        })
        expect(await reasonFor(verifier().verifyToken(token))).toBe('bad_audience')
    })

    it('rejects a caller with no registry entry', async () => {
        const token = await mint({ key: DW_KEY_NEW, caller: 'some-pod-nobody-registered' })
        expect(await reasonFor(verifier().verifyToken(token))).toBe('unknown_caller')
    })

    // The request scope IS the token. A token with no keys claim is not a request for
    // everything — it is a malformed request.
    it('rejects a token carrying no keys claim', async () => {
        const token = await mint({ key: DW_KEY_NEW, caller: 'temporal-worker-data-warehouse', keys: [] })
        expect(await reasonFor(verifier().verifyToken(token))).toBe('no_keys_claim')
    })

    it('rejects a token with no caller claim', async () => {
        const token = await new SignJWT({ keys: ['GOOGLE_ADS_APP_CLIENT_SECRET'] })
            .setProtectedHeader({ alg: 'HS256' })
            .setAudience(AUDIENCE)
            .setExpirationTime('5m')
            .sign(new TextEncoder().encode(DW_KEY_NEW))
        expect(await reasonFor(verifier().verifyToken(token))).toBe('malformed')
    })

    it('rejects a garbage token', async () => {
        expect(await reasonFor(verifier().verifyToken('not-a-jwt'))).toBe('malformed')
    })

    // A caller reporting on a field it never asked for could hold open somebody else's
    // rotation indefinitely.
    it('confines the previous_used report to the keys the token actually requested', async () => {
        const token = await mint({
            key: DW_KEY_NEW,
            caller: 'temporal-worker-data-warehouse',
            keys: ['GOOGLE_ADS_APP_CLIENT_SECRET'],
            previousUsed: ['GOOGLE_ADS_APP_CLIENT_SECRET', 'STRIPE_APP_SECRET_KEY'],
        })
        const { extras } = await verifier().verifyToken(token)
        expect(extras.previousUsed).toEqual(['GOOGLE_ADS_APP_CLIENT_SECRET'])
    })

    it('treats a missing previous_used claim as no report', async () => {
        const token = await mint({ key: DW_KEY_NEW, caller: 'temporal-worker-data-warehouse' })
        expect((await verifier().verifyToken(token)).extras.previousUsed).toEqual([])
    })

    // Every distinct key name a caller sends becomes a metric label and a Redis field,
    // and neither is reclaimed. The allowlist bounds what a compromised caller can read;
    // these bound what it can cost.
    describe('claim size limits', () => {
        it('rejects a token asking for more keys than any real request needs', async () => {
            const token = await mint({
                key: DW_KEY_NEW,
                caller: 'temporal-worker-data-warehouse',
                keys: Array.from({ length: 51 }, (_, i) => `KEY_${i}`),
            })
            expect(await reasonFor(verifier().verifyToken(token))).toBe('oversized_keys_claim')
        })

        it('rejects a token carrying an absurdly long key name', async () => {
            const token = await mint({
                key: DW_KEY_NEW,
                caller: 'temporal-worker-data-warehouse',
                keys: ['A'.repeat(129)],
            })
            expect(await reasonFor(verifier().verifyToken(token))).toBe('oversized_keys_claim')
        })

        it('accepts a request at the limit', async () => {
            const token = await mint({
                key: DW_KEY_NEW,
                caller: 'temporal-worker-data-warehouse',
                keys: Array.from({ length: 50 }, (_, i) => `KEY_${i}`),
            })
            await expect(verifier().verifyToken(token)).resolves.toBeDefined()
        })

        it('deduplicates a repeated key rather than resolving it twice', async () => {
            const token = await mint({
                key: DW_KEY_NEW,
                caller: 'temporal-worker-data-warehouse',
                keys: ['GOOGLE_ADS_APP_CLIENT_SECRET', 'GOOGLE_ADS_APP_CLIENT_SECRET'],
            })
            const { identity } = await verifier().verifyToken(token)
            expect(identity.requestedKeys).toEqual(['GOOGLE_ADS_APP_CLIENT_SECRET'])
        })

        it('deduplicates the previous_used report', async () => {
            const token = await mint({
                key: DW_KEY_NEW,
                caller: 'temporal-worker-data-warehouse',
                keys: ['GOOGLE_ADS_APP_CLIENT_SECRET'],
                previousUsed: ['GOOGLE_ADS_APP_CLIENT_SECRET', 'GOOGLE_ADS_APP_CLIENT_SECRET'],
            })
            const { extras } = await verifier().verifyToken(token)
            expect(extras.previousUsed).toEqual(['GOOGLE_ADS_APP_CLIENT_SECRET'])
        })
    })
})

describe('bearerToken', () => {
    it.each([
        ['undefined header', undefined],
        ['empty header', ''],
        ['non-bearer scheme', 'Basic abc'],
        ['bearer with no token', 'Bearer '],
    ])('rejects %s', (_label, header) => {
        expect(() => bearerToken(header)).toThrow(AuthError)
    })

    it('extracts the token from a well-formed header', () => {
        expect(bearerToken('Bearer abc.def.ghi')).toBe('abc.def.ghi')
    })
})
