import { SignJWT } from 'jose'
import { describe, expect, it } from 'vitest'

import { JwtVerifier, bearerToken } from '@/auth/jwt.js'
import { SigningKeyLoader } from '@/auth/registry.js'
import { AUDIENCE, AuthError, type SigningKeys } from '@/auth/types.js'

const DW = 'temporal-worker-data-warehouse'
const DJANGO = 'posthog-django'

const DW_KEY_NEW = 'dw-signing-key-new'
const DW_KEY_OLD = 'dw-signing-key-old'
const DJANGO_KEY = 'django-signing-key'

const KEYS: SigningKeys = {
    [DW]: [DW_KEY_NEW, DW_KEY_OLD],
    [DJANGO]: [DJANGO_KEY],
}

function verifier(keys: SigningKeys = KEYS): JwtVerifier {
    return new JwtVerifier({ entries: () => Object.entries(keys) } as SigningKeyLoader)
}

async function mint(opts: {
    key: string
    product?: string
    keys?: string[]
    audience?: string
    expiresIn?: string
    /** Mint with no `exp` at all — the shape jose accepts unless `exp` is required. */
    omitExpiry?: boolean
}): Promise<string> {
    const builder = new SignJWT({
        caller: opts.product ?? 'warehouse-sources',
        keys: opts.keys ?? ['GOOGLE_ADS_APP_CLIENT_SECRET'],
    })
        .setProtectedHeader({ alg: 'HS256' })
        .setAudience(opts.audience ?? AUDIENCE)
        .setIssuedAt()
    if (!opts.omitExpiry) {
        builder.setExpirationTime(opts.expiresIn ?? '5m')
    }
    return builder.sign(new TextEncoder().encode(opts.key))
}

// Resolves to the rejection reason, or throws if the token was accepted. Asserts by
// throwing rather than with `expect` inside a catch, which would make the assertion
// conditional on the rejection happening at all.
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
    it('accepts a well-formed token and returns the requested keys', async () => {
        const identity = await verifier().verify(await mint({ key: DW_KEY_NEW }))

        expect(identity.deployment).toBe(DW)
        expect(identity.requestedKeys).toEqual(['GOOGLE_ADS_APP_CLIENT_SECRET'])
    })

    // The deployment is whichever key verified, never a claim. There is therefore nothing
    // in the token an attacker could edit to become a different deployment.
    it('derives the deployment from the verifying key, not from the token', async () => {
        const signedByDjango = await verifier().verify(await mint({ key: DJANGO_KEY }))
        const signedByWorker = await verifier().verify(await mint({ key: DW_KEY_NEW }))

        expect(signedByDjango.deployment).toBe(DJANGO)
        expect(signedByWorker.deployment).toBe(DW)
    })

    it('accepts a token signed with a retired key still listed for that deployment', async () => {
        await expect(verifier().verify(await mint({ key: DW_KEY_OLD }))).resolves.toBeDefined()
    })

    it('rejects a token signed with a key no deployment lists', async () => {
        expect(await reasonFor(verifier().verify(await mint({ key: 'nobody-lists-this' })))).toBe('bad_signature')
    })

    it.each([
        ['an expired token', { expiresIn: '-1s' }, 'expired'],
        ['a token for another audience', { audience: 'posthog:recording_api' }, 'bad_audience'],
        ['a token with no keys claim', { keys: [] }, 'no_keys_claim'],
        // jose validates `exp` only when it is present, so a token minted without one
        // would otherwise verify and never expire. The bound has to live here rather than
        // in whichever client happens to mint today.
        ['a token that never expires', { omitExpiry: true }, 'no_expiry'],
    ])('rejects %s', async (_label, overrides, reason) => {
        const token = await mint({ key: DW_KEY_NEW, ...overrides })
        expect(await reasonFor(verifier().verify(token))).toBe(reason)
    })

    it('rejects a garbage token', async () => {
        expect(await reasonFor(verifier().verify('not-a-jwt'))).toBe('malformed')
    })

    describe('the product claim', () => {
        // Django holds one key and hosts many products, so the product name cannot be
        // authenticated. It is kept for metrics and audit and grants nothing.
        it('is carried through when we recognise it', async () => {
            const identity = await verifier().verify(await mint({ key: DJANGO_KEY, product: 'cdp' }))
            expect(identity.product).toBe('cdp')
        })

        // Otherwise it is a caller-supplied string, and a caller-supplied string must
        // never become a metric label.
        it.each([
            ['an unrecognised product', 'something-invented'],
            ['an empty product', ''],
        ])('collapses %s to a constant', async (_label, product) => {
            const identity = await verifier().verify(await mint({ key: DJANGO_KEY, product }))
            expect(identity.product).toBe('unknown')
        })

        it('never changes the authenticated deployment', async () => {
            const identity = await verifier().verify(await mint({ key: DW_KEY_NEW, product: 'cdp' }))
            expect(identity.deployment).toBe(DW)
        })
    })

    // Every distinct key name a caller sends becomes a Redis field, and it is never
    // reclaimed. Revoking a deployment's key bounds what a compromised caller can read;
    // these bound what it can cost before anyone notices.
    describe('claim size limits', () => {
        it.each([
            ['more keys than any real request needs', Array.from({ length: 51 }, (_, i) => `KEY_${i}`)],
            ['an absurdly long key name', ['A'.repeat(129)]],
        ])('rejects %s', async (_label, keys) => {
            expect(await reasonFor(verifier().verify(await mint({ key: DW_KEY_NEW, keys })))).toBe(
                'oversized_keys_claim'
            )
        })

        it('accepts a request at the limit', async () => {
            const keys = Array.from({ length: 50 }, (_, i) => `KEY_${i}`)
            await expect(verifier().verify(await mint({ key: DW_KEY_NEW, keys }))).resolves.toBeDefined()
        })

        it('deduplicates a repeated key rather than resolving it twice', async () => {
            const token = await mint({ key: DW_KEY_NEW, keys: ['A_KEY', 'A_KEY'] })
            expect((await verifier().verify(token)).requestedKeys).toEqual(['A_KEY'])
        })
    })
})

describe('signing key registry', () => {
    function loader(fields: Record<string, unknown>): SigningKeyLoader {
        const client = {
            send: () => Promise.resolve({ SecretString: JSON.stringify(fields) }),
        }
        return new SigningKeyLoader(client as never, 'integration-service-secrets')
    }

    it('derives one deployment per CALLER_KEY_ entry and ignores everything else', async () => {
        const keys = loader({
            CALLER_KEY_POSTHOG_DJANGO: `${DJANGO_KEY}`,
            CALLER_KEY_TEMPORAL_WORKER_DATA_WAREHOUSE: `${DW_KEY_NEW}, ${DW_KEY_OLD}`,
            STRIPE_APP_SECRET_KEY: 'not-a-signing-key',
        })
        await keys.load()

        expect(Object.fromEntries(keys.entries())).toEqual(KEYS)
    })

    // The verifier breaks on the first key set that verifies, so two deployments sharing a
    // value collapse into one identity: revoking either leaves the other working, and
    // every attribution names the wrong caller. A paste error is invisible in an opaque
    // value, so it has to fail at boot.
    it('refuses to load when two deployments are given the same signing key', async () => {
        const keys = loader({
            CALLER_KEY_POSTHOG_DJANGO: DJANGO_KEY,
            CALLER_KEY_TEMPORAL_WORKER_DATA_WAREHOUSE: `${DW_KEY_NEW},${DJANGO_KEY}`,
        })

        await expect(keys.load()).rejects.toThrow(/also listed for posthog-django/)
        expect(keys.isLoaded).toBe(false)
    })

    // A malformed edit must not lock a running fleet out, so reload keeps the previous
    // keys. That makes it the one path a revocation travels and it fails open — see the
    // last-loaded gauge and the failure counter in metrics.ts.
    it('keeps the previous keys when a reload fails', async () => {
        let healthy = true
        const client = {
            send: () =>
                healthy
                    ? Promise.resolve({ SecretString: JSON.stringify({ CALLER_KEY_POSTHOG_DJANGO: DJANGO_KEY }) })
                    : Promise.reject(new Error('access denied')),
        }
        const keys = new SigningKeyLoader(client as never, 'integration-service-secrets')
        await keys.load()

        healthy = false
        await keys.reload()

        expect(Object.fromEntries(keys.entries())).toEqual({ [DJANGO]: [DJANGO_KEY] })
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
