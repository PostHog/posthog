import { SignJWT } from 'jose'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'

import { JwtVerifier, bearerToken } from '@/auth/jwt'
import { SigningKeyLoader } from '@/auth/registry'
import { AUDIENCE, AuthError, type SigningKeys } from '@/auth/types'

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
    caller?: string
    keys?: unknown
    audience?: string
    expiresIn?: string
    /** Mint with no `exp` at all — the shape jose accepts unless `exp` is required. */
    omitExpiry?: boolean
    omitKeys?: boolean
}): Promise<string> {
    const builder = new SignJWT({
        caller: opts.caller ?? 'warehouse-sources',
        ...(opts.omitKeys ? {} : { keys: opts.keys ?? ['GOOGLE_ADS_APP_CLIENT_SECRET'] }),
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
        // A bare string would spread through `new Set(...)` into one requested key per
        // character; a non-string element would slip past validation entirely.
        ['a token whose keys claim is a bare string', { keys: 'STRIPE_APP_SECRET_KEY' }, 'no_keys_claim'],
        ['a token whose keys claim holds a non-string', { keys: ['GOOGLE_ADS_APP_CLIENT_SECRET', 7] }, 'no_keys_claim'],
        ['a token with the keys claim absent', { omitKeys: true }, 'no_keys_claim'],
        // jose validates `exp` only when it is present, so a token minted without one
        // would otherwise verify and never expire. The bound has to live here rather than
        // in whichever client happens to mint today.
        ['a token that never expires', { omitExpiry: true }, 'no_expiry'],
    ])('rejects %s', async (_label, overrides, reason) => {
        const token = await mint({ key: DW_KEY_NEW, ...overrides })
        expect(await reasonFor(verifier().verify(token))).toBe(reason)
    })

    // Widening or dropping `algorithms: ['HS256']` is the classic algorithm-confusion
    // regression, and that one line is all that stands between the service and it.
    it('rejects a token signed with a wider HMAC', async () => {
        const token = await new SignJWT({ caller: 'warehouse-sources', keys: ['A_KEY'] })
            .setProtectedHeader({ alg: 'HS512' })
            .setAudience(AUDIENCE)
            .setIssuedAt()
            .setExpirationTime('5m')
            .sign(new TextEncoder().encode(DW_KEY_NEW))

        await expect(verifier().verify(token)).rejects.toBeInstanceOf(AuthError)
    })

    // Hand-built, because jose refuses to mint one: an unsigned token must not verify.
    it('rejects an unsigned token', async () => {
        const b64 = (value: object): string => Buffer.from(JSON.stringify(value)).toString('base64url')
        const token = `${b64({ alg: 'none' })}.${b64({
            aud: AUDIENCE,
            exp: Math.floor(Date.now() / 1000) + 300,
            keys: ['A_KEY'],
        })}.`

        await expect(verifier().verify(token)).rejects.toBeInstanceOf(AuthError)
    })

    // Two mount entries that normalize onto one deployment name would silently drop a key
    // set, so a revocation would look like it landed and would not have.
    it('rejects a garbage token', async () => {
        expect(await reasonFor(verifier().verify('not-a-jwt'))).toBe('malformed')
    })

    // Untrusted after the registry went away: Django holds one key and hosts many
    // products, so the claim is carried to the audit log and is never a metric label.
    it.each([
        ['a name we would once have recognised', 'cdp'],
        ['a name nobody has ever used', 'something-invented'],
    ])('carries %s through as the caller without touching the deployment', async (_label, caller) => {
        const identity = await verifier().verify(await mint({ key: DW_KEY_NEW, caller }))

        expect(identity.caller).toBe(caller)
        expect(identity.deployment).toBe(DW)
    })

    it('deduplicates a repeated key rather than resolving it twice', async () => {
        const token = await mint({ key: DW_KEY_NEW, keys: ['A_KEY', 'A_KEY'] })
        expect((await verifier().verify(token)).requestedKeys).toEqual(['A_KEY'])
    })
})

describe('signing key registry', () => {
    const dirs: string[] = []

    afterEach(async () => {
        await Promise.all(dirs.splice(0).map((d) => rm(d, { recursive: true, force: true })))
    })

    /** A directory shaped the way kubelet projects a Kubernetes Secret: one file per key. */
    async function mount(values: Record<string, string>): Promise<string> {
        const dir = await mkdtemp(join(tmpdir(), 'signing-keys-'))
        dirs.push(dir)
        await Promise.all(Object.entries(values).map(([k, v]) => writeFile(join(dir, k), v)))
        return dir
    }

    it('derives one deployment per __CALLER_KEY_ entry and ignores everything else', async () => {
        const keys = new SigningKeyLoader(
            await mount({
                __CALLER_KEY_POSTHOG_DJANGO: DJANGO_KEY,
                __CALLER_KEY_TEMPORAL_WORKER_DATA_WAREHOUSE: `${DW_KEY_NEW}, ${DW_KEY_OLD}`,
                STRIPE_APP_SECRET_KEY: 'not-a-signing-key',
            })
        )
        await keys.load()

        expect(Object.fromEntries(keys.entries())).toEqual(KEYS)
    })

    it('refuses to boot when the mount carries no caller keys at all', async () => {
        const keys = new SigningKeyLoader(await mount({ STRIPE_APP_SECRET_KEY: 'sec' }))
        await expect(keys.load()).rejects.toThrow(/no __CALLER_KEY_\* entries/)
        expect(keys.isLoaded).toBe(false)
    })

    // The verifier stops at the first key set that verifies, so two deployments sharing a
    // value collapse into one identity: revoking either leaves the other working, and every
    // attribution names the wrong caller. A paste error is invisible in an opaque value, so
    // it has to fail at boot.
    it('refuses to load when two deployments are given the same signing key', async () => {
        const keys = new SigningKeyLoader(
            await mount({
                __CALLER_KEY_POSTHOG_DJANGO: DJANGO_KEY,
                __CALLER_KEY_TEMPORAL_WORKER_DATA_WAREHOUSE: `${DW_KEY_NEW},${DJANGO_KEY}`,
            })
        )

        await expect(keys.load()).rejects.toThrow(/also listed for/)
        expect(keys.isLoaded).toBe(false)
    })

    it('refuses to load when two entries normalize onto one deployment name', async () => {
        const keys = new SigningKeyLoader(
            await mount({ __CALLER_KEY_FOO_BAR: DJANGO_KEY, '__CALLER_KEY_FOO-BAR': DW_KEY_NEW })
        )

        await expect(keys.load()).rejects.toThrow(/both name the deployment foo-bar/)
        expect(keys.isLoaded).toBe(false)
    })

    // A malformed edit must not lock a running fleet out, so reload keeps the previous
    // keys. That makes it the one path a revocation travels and it fails open — see the
    // last-loaded gauge and the failure counter in metrics.ts.
    it('keeps the previous keys when a reload fails', async () => {
        const dir = await mount({ __CALLER_KEY_POSTHOG_DJANGO: DJANGO_KEY })
        const keys = new SigningKeyLoader(dir)
        await keys.load()

        await rm(dir, { recursive: true, force: true })
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
