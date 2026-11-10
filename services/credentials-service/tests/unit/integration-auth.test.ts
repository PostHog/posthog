import { Hono } from 'hono'
import { SignJWT } from 'jose'
import { beforeEach, describe, expect, it } from 'vitest'

import {
    IntegrationAuthError,
    type IntegrationGrant,
    IntegrationVerifier,
    MAX_TOKEN_LIFETIME_SECONDS,
    assertKindAllowed,
} from '@/auth/integrations'
import { JwtVerifier } from '@/auth/jwt'
import { createIntegrationAuth } from '@/auth/middleware'
import { INTEGRATION_OPS, type IntegrationOp, ROLE_OPS, deploymentAllows, roleFor } from '@/auth/policy'
import type { SigningKeyLoader } from '@/auth/registry'
import { REPLAY_WINDOW_MS, ReplayCache } from '@/auth/replay'
import { AUDIENCE, AuthError, INTEGRATIONS_AUDIENCE, type SigningKeys } from '@/auth/types'
import { integrationAuthTotal, integrationReplayEvictionsTotal, register } from '@/metrics'

const WEB = 'posthog-django'
const WORKER = 'temporal-worker-data-warehouse'
const CDP = 'cdp-destinations'

const KEYS: SigningKeys = {
    [WEB]: ['web-signing-key-fake'],
    [WORKER]: ['worker-signing-key-fake'],
    [CDP]: ['cdp-signing-key-fake'],
}

const NOW_S = 1_800_000_000
const NOW_MS = NOW_S * 1000
const TEAM = { type: 'team', id: 42 }
const UUID_REF = '0b8a3a8e-4e0a-4f5e-9d7a-1c2b3d4e5f60'

const loader = { entries: () => Object.entries(KEYS) } as SigningKeyLoader

let jtiCounter = 0
function freshJti(): string {
    jtiCounter += 1
    return `test-jti-${String(jtiCounter).padStart(8, '0')}`
}

interface MintOptions {
    deployment?: string
    key?: string
    audience?: string | string[]
    iat?: number
    /** Seconds after `iat`. */
    lifetime?: number
    omitExp?: boolean
    claims?: Record<string, unknown>
    omit?: string[]
}

async function mint(opts: MintOptions = {}): Promise<string> {
    const iat = opts.iat ?? NOW_S
    const claims: Record<string, unknown> = {
        jti: freshJti(),
        owner: TEAM,
        ops: ['read', 'resolve'],
        caller: 'integrations-sdk',
        ...opts.claims,
    }
    for (const name of opts.omit ?? []) {
        delete claims[name]
    }
    const builder = new SignJWT(claims)
        .setProtectedHeader({ alg: 'HS256' })
        .setAudience(opts.audience ?? INTEGRATIONS_AUDIENCE)
        .setIssuedAt(iat)
    if (!opts.omitExp) {
        builder.setExpirationTime(iat + (opts.lifetime ?? MAX_TOKEN_LIFETIME_SECONDS))
    }
    const key = opts.key ?? KEYS[opts.deployment ?? WEB]![0]!
    return builder.sign(new TextEncoder().encode(key))
}

function verifier(opts: { now?: () => number; replay?: ReplayCache } = {}): IntegrationVerifier {
    return new IntegrationVerifier(loader, {
        now: opts.now ?? (() => NOW_MS),
        replay: opts.replay ?? new ReplayCache(),
    })
}

async function codeFor(promise: Promise<unknown> | (() => unknown)): Promise<string> {
    const outcome = await (typeof promise === 'function' ? Promise.resolve().then(promise) : promise).then(
        () => null,
        (err: unknown) => err
    )
    if (!(outcome instanceof IntegrationAuthError)) {
        throw new Error(`expected an IntegrationAuthError, got ${String(outcome)}`)
    }
    return outcome.code
}

async function grant(opts: MintOptions = {}): Promise<IntegrationGrant> {
    return verifier().verify(await mint(opts))
}

async function authCount(deployment: string, outcome: string): Promise<number> {
    const values = (await integrationAuthTotal.get()).values
    return values.find((v) => v.labels['deployment'] === deployment && v.labels['outcome'] === outcome)?.value ?? 0
}

beforeEach(() => {
    register.resetMetrics()
})

describe('integration policy', () => {
    it.each([
        [WEB, 'web'],
        ['temporal-worker', 'worker'],
        [WORKER, 'worker'],
        ['posthog-celery', 'worker'],
        ['posthog-celery-default', 'worker'],
        ['cdp', 'resolver'],
        [CDP, 'resolver'],
        ['ingestion-events', 'resolver'],
        ['push-api', 'resolver'],
        // The web role is exact. A family name never extends it.
        ['posthog-django-canary', null],
        // A family needs the `-` boundary.
        ['cdpx', null],
        ['temporal-workers', null],
        ['someone-else', null],
    ])('gives %s the role %s', (deployment, role) => {
        expect(roleFor(deployment)).toBe(role)
    })

    it('gives web every op', () => {
        expect([...ROLE_OPS.web].sort()).toEqual([...INTEGRATION_OPS].sort())
    })

    const crossTeamAndAdmin: IntegrationOp[] = [
        'read_by_external_id',
        'write_by_external_id',
        'delete_by_external_id',
        'delete_owner',
    ]

    it.each([
        ...INTEGRATION_OPS.map((op) => [WEB, op, true] as const),
        ...(['read', 'resolve', 'write', 'refresh', 'list_across_teams'] as const).map(
            (op) => [WORKER, op, true] as const
        ),
        ...crossTeamAndAdmin.map((op) => [WORKER, op, false] as const),
        [WORKER, 'delete', false],
        [WORKER, 'changes', false],
        [WORKER, 'oauth_exchange', false],
        [CDP, 'resolve', true],
        ...INTEGRATION_OPS.filter((op) => op !== 'resolve').map((op) => [CDP, op, false] as const),
        ['someone-else', 'resolve', false],
        ['someone-else', 'read', false],
    ] as [string, IntegrationOp, boolean][])('%s may %s: %s', (deployment, op, allowed) => {
        expect(deploymentAllows(deployment, op)).toBe(allowed)
    })
})

describe('integration token verification', () => {
    it('accepts a well-formed token and returns the owner from the token', async () => {
        const result = await grant({ claims: { user_id: 7, kinds: ['slack'], refs: [UUID_REF] } })

        expect(result.deployment).toBe(WEB)
        expect(result.claims).toMatchObject({
            owner: TEAM,
            userId: 7,
            kinds: ['slack'],
            refs: [UUID_REF],
            caller: 'integrations-sdk',
        })
    })

    it.each([
        ['an expired token', { iat: NOW_S - 120 }, 'expired'],
        ['a token with no exp', { omitExp: true }, 'no_expiry'],
        ['a token that lives longer than 60s', { lifetime: MAX_TOKEN_LIFETIME_SECONDS + 1 }, 'lifetime_too_long'],
        ['a token whose exp is not after iat', { lifetime: 0 }, 'invalid_claims'],
        ['a token issued too far in the future', { iat: NOW_S + 31 }, 'not_yet_valid'],
        ['a token for the secrets audience', { audience: AUDIENCE }, 'bad_audience'],
        // jose accepts an array that contains the audience, so one token could pass both routes.
        ['a token with both audiences', { audience: [AUDIENCE, INTEGRATIONS_AUDIENCE] }, 'bad_audience'],
        ['a token signed by no known key', { key: 'unknown-signing-key-fake' }, 'bad_signature'],
        ['a token with no jti', { omit: ['jti'] }, 'invalid_claims'],
        ['a token with a short jti', { claims: { jti: 'short' } }, 'invalid_claims'],
        ['a token with no caller', { omit: ['caller'] }, 'invalid_claims'],
        ['a token with no ops', { claims: { ops: [] } }, 'invalid_claims'],
        ['a token with an unknown op', { claims: { ops: ['read', 'admin'] } }, 'invalid_claims'],
        ['a token whose ops is a string', { claims: { ops: 'read' } }, 'invalid_claims'],
        ['a token with no owner for a team op', { omit: ['owner'] }, 'invalid_claims'],
        ['a token with an org owner', { claims: { owner: { type: 'organization', id: 42 } } }, 'invalid_claims'],
        ['a token with a string owner id', { claims: { owner: { type: 'team', id: '42' } } }, 'invalid_claims'],
        ['a token with a zero owner id', { claims: { owner: { type: 'team', id: 0 } } }, 'invalid_claims'],
        ['a token with an extra owner field', { claims: { owner: { ...TEAM, org: 1 } } }, 'invalid_claims'],
        ['a token with an empty kinds list', { claims: { kinds: [] } }, 'invalid_claims'],
        ['a token with an invalid kind', { claims: { kinds: ['Slack App'] } }, 'invalid_claims'],
        ['a token with an uppercase uuid ref', { claims: { refs: [UUID_REF.toUpperCase()] } }, 'invalid_claims'],
        ['a token with a zero-padded ref', { claims: { refs: ['007'] } }, 'invalid_claims'],
        ['a token with a numeric ref', { claims: { refs: [7] } }, 'invalid_claims'],
        ['a token with a string user_id', { claims: { user_id: '7' } }, 'invalid_claims'],
        ['a token with a null user_id', { claims: { user_id: null } }, 'invalid_claims'],
        // A secrets-route claim means the minter mixed up the two schemas.
        ['a token with a keys claim', { claims: { keys: ['STRIPE_APP_SECRET_KEY'] } }, 'invalid_claims'],
    ])('rejects %s', async (_label, opts: MintOptions, code) => {
        expect(await codeFor(verifier().verify(await mint(opts)))).toBe(code)
    })

    it('rejects a token that is not a JWT', async () => {
        expect(await codeFor(verifier().verify('not-a-jwt'))).toBe('malformed')
    })

    it.each([
        ['exactly 60s of life', { lifetime: MAX_TOKEN_LIFETIME_SECONDS }],
        ['exp 29s in the past, inside the skew', { iat: NOW_S - 89 }],
        ['iat 30s in the future, at the skew limit', { iat: NOW_S + 30 }],
        ['a numeric legacy ref', { claims: { refs: ['0', '123'] } }],
        ['no owner when every op is cross-team', { omit: ['owner'], claims: { ops: ['list_across_teams'] } }],
    ])('accepts %s', async (_label, opts: MintOptions) => {
        await expect(verifier().verify(await mint(opts))).resolves.toBeDefined()
    })

    it('rejects exp exactly 30s in the past', async () => {
        expect(await codeFor(verifier().verify(await mint({ iat: NOW_S - 90 })))).toBe('expired')
    })

    it('does not let the secrets route accept an integration token', async () => {
        const token = await mint({ claims: { keys: ['STRIPE_APP_SECRET_KEY'] } })
        const outcome = await new JwtVerifier(loader).verify(token).catch((err: unknown) => err)

        expect(outcome).toBeInstanceOf(AuthError)
        expect((outcome as AuthError).reason).toBe('bad_audience')
    })

    it('does not let the secrets route accept a token with both audiences', async () => {
        const token = await mint({ audience: [AUDIENCE, INTEGRATIONS_AUDIENCE], claims: { keys: ['A_KEY'] } })
        const outcome = await new JwtVerifier(loader).verify(token).catch((err: unknown) => err)

        expect((outcome as AuthError).reason).toBe('bad_audience')
    })

    it('rejects a replayed token', async () => {
        const v = verifier()
        const token = await mint()

        await v.verify(token)
        expect(await codeFor(v.verify(token))).toBe('replayed')
    })

    it('keeps token ids apart per deployment', async () => {
        const v = verifier()
        const jti = 'shared-jti-value-0001'

        await v.verify(await mint({ deployment: WEB, claims: { jti } }))
        await expect(v.verify(await mint({ deployment: WORKER, claims: { jti } }))).resolves.toBeDefined()
    })

    it('rejects a replay at the last moment the token still verifies', async () => {
        let now = (NOW_S - 30) * 1000
        const v = verifier({ now: () => now })
        const token = await mint()

        await v.verify(token)
        now = (NOW_S + 89) * 1000
        expect(await codeFor(v.verify(token))).toBe('replayed')
    })

    it('counts outcomes by deployment, and unknown before a key verifies', async () => {
        await grant({ deployment: CDP })
        await codeFor(verifier().verify(await mint({ key: 'unknown-signing-key-fake' })))
        await codeFor(verifier().verify(await mint({ deployment: CDP, lifetime: 600 })))

        expect(await authCount('unknown', 'bad_signature')).toBe(1)
        expect(await authCount(CDP, 'lifetime_too_long')).toBe(1)
    })
})

describe('integration authorization', () => {
    it.each([
        ['cdp writing', CDP, ['resolve', 'write'], 'write'],
        ['cdp listing across teams', CDP, ['resolve', 'list_across_teams'], 'list_across_teams'],
        ['a worker deleting a team', WORKER, ['delete_owner'], 'delete_owner'],
        ['a worker reading by external id', WORKER, ['read_by_external_id'], 'read_by_external_id'],
        // The policy allows it, but the token does not ask for it.
        ['web with an op the token lacks', WEB, ['read'], 'write'],
    ] as [string, string, IntegrationOp[], IntegrationOp][])('forbids %s', async (_label, deployment, ops, op) => {
        const g = await grant({ deployment, claims: { ops } })
        expect(await codeFor(() => g.authorize(op))).toBe('forbidden_op')
        expect(await authCount(deployment, 'forbidden_op')).toBe(1)
    })

    it('allows an op in both the token and the policy, and binds the token owner', async () => {
        const g = await grant({ deployment: CDP, claims: { ops: ['resolve'], user_id: 9 } })
        const auth = g.authorize('resolve', { ref: '123' })

        expect(auth).toMatchObject({ op: 'resolve', deployment: CDP, owner: TEAM, userId: 9 })
        expect(auth.jti).toBe(g.claims.jti)
        expect(await authCount(CDP, 'ok')).toBe(1)
    })

    it.each([
        ['a worker', WORKER, 'list_across_teams'],
        ['web', WEB, 'read_by_external_id'],
    ] as [string, string, IntegrationOp][])('lets %s run %s with no owner', async (_label, deployment, op) => {
        const g = await grant({ deployment, omit: ['owner'], claims: { ops: [op] } })
        expect(g.authorize(op).owner).toBeNull()
    })

    it.each([
        ['an allowed kind', ['slack', 'github'], 'slack', null],
        ['every allowed kind of a batch', ['slack', 'github'], ['slack', 'github'], null],
        ['a kind outside the token', ['slack'], 'github', 'forbidden_kind'],
        ['a batch with one kind outside the token', ['slack'], ['slack', 'github'], 'forbidden_kind'],
        ['any kind when the token does not narrow', undefined, 'github', null],
    ])('handles %s', async (_label, kinds, kind, code) => {
        const g = await grant({ claims: kinds ? { kinds } : {} })
        if (code) {
            expect(await codeFor(() => g.authorize('read', { kind }))).toBe(code)
        } else {
            expect(g.authorize('read', { kind }).op).toBe('read')
        }
    })

    it.each([
        ['an allowed ref', [UUID_REF, '12'], '12', null],
        ['a batch of allowed refs', [UUID_REF, '12'], [UUID_REF, '12'], null],
        ['a ref outside the token', ['12'], '13', 'forbidden_ref'],
        ['a batch with one ref outside the token', ['12'], ['12', '13'], 'forbidden_ref'],
        // A list cannot name its refs, so a ref-narrowed token must not reach it.
        ['a request that names no ref', ['12'], undefined, 'forbidden_ref'],
        ['any ref when the token does not narrow', undefined, '13', null],
    ])('handles %s', async (_label, refs, ref, code) => {
        const g = await grant({ claims: refs ? { refs } : {} })
        if (code) {
            expect(await codeFor(() => g.authorize('read', { ref }))).toBe(code)
        } else {
            expect(g.authorize('read', { ref }).op).toBe('read')
        }
    })

    it('checks a kind that the route learns after it loads the row', async () => {
        const auth = (await grant({ claims: { kinds: ['slack'] } })).authorize('read')

        expect(() => assertKindAllowed(auth, 'slack')).not.toThrow()
        expect(await codeFor(() => assertKindAllowed(auth, 'github'))).toBe('forbidden_kind')
    })
})

describe('replay cache', () => {
    it('forgets an id once the window has passed', () => {
        const cache = new ReplayCache()

        expect(cache.claim('a', 0)).toBe(true)
        expect(cache.claim('a', REPLAY_WINDOW_MS - 1)).toBe(false)
        expect(cache.claim('a', REPLAY_WINDOW_MS)).toBe(true)
    })

    it('drops expired ids so memory stays bounded by traffic in the window', () => {
        const cache = new ReplayCache(1000)
        cache.claim('a', 0)
        cache.claim('b', 500)
        cache.claim('c', 1200)

        expect(cache.size).toBe(2)
    })

    it('evicts the oldest id when full and counts it', async () => {
        const cache = new ReplayCache(REPLAY_WINDOW_MS, 2)
        cache.claim('a', 0)
        cache.claim('b', 1)
        cache.claim('c', 2)

        expect(cache.size).toBe(2)
        expect(cache.claim('b', 3)).toBe(false)
        expect(cache.claim('a', 3)).toBe(true)
        expect((await integrationReplayEvictionsTotal.get()).values[0]?.value).toBe(2)
    })
})

describe('requireIntegrationAuth middleware', () => {
    function app(v: IntegrationVerifier = verifier()): Hono {
        const requireIntegrationAuth = createIntegrationAuth(v)
        const hono = new Hono()
        hono.post(
            '/v1/integrations/:ref/refresh',
            requireIntegrationAuth('read', { ref: (c) => c.req.param('ref') }),
            requireIntegrationAuth('refresh', { ref: (c) => c.req.param('ref') }),
            (c) => c.json({ owner: c.var.integrationAuth.owner, op: c.var.integrationAuth.op })
        )
        return hono
    }

    const call = (hono: Hono, token: string | null, ref = '12'): Response | Promise<Response> =>
        hono.request(`/v1/integrations/${ref}/refresh`, {
            method: 'POST',
            headers: token ? { Authorization: `Bearer ${token}` } : {},
        })

    it('passes the token owner to the handler, verifying the token once across middlewares', async () => {
        const res = await call(app(), await mint({ deployment: WORKER, claims: { ops: ['read', 'refresh'] } }))

        expect(res.status).toBe(200)
        expect(await res.json()).toEqual({ owner: TEAM, op: 'refresh' })
    })

    it.each([
        ['no token', null],
        ['an expired token', 'expired'],
    ])('answers 401 with no detail for %s', async (_label, kind) => {
        const token = kind ? await mint({ iat: NOW_S - 600 }) : null
        const res = await call(app(), token)

        expect(res.status).toBe(401)
        expect(await res.json()).toEqual({ error: { code: 'unauthorized', message: 'Unauthorized' } })
    })

    it('answers 401 for a replayed token on a second request', async () => {
        const hono = app()
        const token = await mint({ deployment: WORKER, claims: { ops: ['read', 'refresh'] } })

        expect((await call(hono, token)).status).toBe(200)
        expect((await call(hono, token)).status).toBe(401)
        expect(await authCount(WORKER, 'replayed')).toBe(1)
    })

    it.each([
        ['an op the deployment lacks', { deployment: CDP, claims: { ops: ['read', 'refresh'] } }, 'forbidden_op'],
        ['a ref the token lacks', { claims: { ops: ['read', 'refresh'], refs: ['13'] } }, 'forbidden_ref'],
    ])('answers 403 with the code for %s', async (_label, opts: MintOptions, code) => {
        const res = await call(app(), await mint(opts))

        expect(res.status).toBe(403)
        expect(((await res.json()) as { error: { code: string } }).error.code).toBe(code)
    })
})
