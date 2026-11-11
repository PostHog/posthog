import { Hono } from 'hono'
import { SignJWT } from 'jose'
import { type KeyObject, generateKeyPairSync } from 'node:crypto'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { IntegrationKeyLoader, parseIntegrationPublicKeys } from '@/auth/integration-keys'
import {
    IntegrationAuthError,
    type IntegrationGrant,
    IntegrationVerifier,
    MAX_TOKEN_LIFETIME_SECONDS,
    assertKindAllowed,
} from '@/auth/integrations'
import { JwtVerifier } from '@/auth/jwt'
import { createIntegrationAuth } from '@/auth/middleware'
import { ALL_KINDS, INTEGRATION_OPS, type IntegrationOp, POLICY, deploymentAllows, policyFor } from '@/auth/policy'
import type { SigningKeyLoader } from '@/auth/registry'
import { MemoryReplayStore, REPLAY_WINDOW_MS, ReplayCache, type ReplayStore } from '@/auth/replay'
import { AUDIENCE, AuthError, INTEGRATIONS_AUDIENCE } from '@/auth/types'
import { integrationAuthTotal, integrationReplayEvictionsTotal, register } from '@/metrics'

const WEB = 'posthog-web-django'
const WORKER = 'temporal-worker-data-warehouse'
const CELERY = 'posthog-worker-django'
const CDP = 'cdp-events-consumer'
const TASKS = 'temporal-worker-tasks-agent'
const REVERSE_SYNC = 'posthog-integrations-reverse-sync'

const DEPLOYMENTS = [WEB, WORKER, CELERY, CDP, TASKS, REVERSE_SYNC]

const PAIRS: Record<string, { privateKey: KeyObject; publicKey: KeyObject }> = Object.fromEntries(
    DEPLOYMENTS.map((deployment) => [deployment, generateKeyPairSync('ed25519')])
)

function publicPem(key: KeyObject): string {
    return key.export({ type: 'spki', format: 'pem' }).toString()
}

const PUBLIC_FILES: Record<string, string> = Object.fromEntries(
    DEPLOYMENTS.map((deployment) => [`${deployment}.pub`, publicPem(PAIRS[deployment]!.publicKey)])
)

const loader = new IntegrationKeyLoader('test')
loader.loadFrom(PUBLIC_FILES)

// The platform-secrets HS256 key of the same deployment. It must never verify an integrations token.
const PLATFORM_KEY = 'web-platform-signing-key-fake'

const NOW_S = 1_800_000_000
const NOW_MS = NOW_S * 1000
const TEAM = { type: 'team', id: 42 }
const UUID_REF = '0b8a3a8e-4e0a-4f5e-9d7a-1c2b3d4e5f60'

let jtiCounter = 0
function freshJti(): string {
    jtiCounter += 1
    return `test-jti-${String(jtiCounter).padStart(8, '0')}`
}

interface MintOptions {
    deployment?: string
    /** Sign with this key instead of the deployment's private key. */
    signWith?: KeyObject | Uint8Array
    alg?: string
    audience?: string | string[]
    iat?: number
    /** Seconds after `iat`. */
    lifetime?: number
    omitExp?: boolean
    claims?: Record<string, unknown>
    omit?: string[]
}

function claimsFor(opts: MintOptions): Record<string, unknown> {
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
    return claims
}

async function mint(opts: MintOptions = {}): Promise<string> {
    const iat = opts.iat ?? NOW_S
    const builder = new SignJWT(claimsFor(opts))
        .setProtectedHeader({ alg: opts.alg ?? 'EdDSA' })
        .setAudience(opts.audience ?? INTEGRATIONS_AUDIENCE)
        .setIssuedAt(iat)
    if (!opts.omitExp) {
        builder.setExpirationTime(iat + (opts.lifetime ?? MAX_TOKEN_LIFETIME_SECONDS))
    }
    return builder.sign(opts.signWith ?? PAIRS[opts.deployment ?? WEB]!.privateKey)
}

/** A token with `alg: none` and no signature, which jose refuses to build. */
function unsigned(): string {
    const encode = (value: unknown): string => Buffer.from(JSON.stringify(value)).toString('base64url')
    const payload = { ...claimsFor({}), aud: INTEGRATIONS_AUDIENCE, iat: NOW_S, exp: NOW_S + 60 }
    return `${encode({ alg: 'none', typ: 'JWT' })}.${encode(payload)}.`
}

function verifier(
    opts: { now?: () => number; replay?: ReplayStore; keys?: IntegrationKeyLoader } = {}
): IntegrationVerifier {
    return new IntegrationVerifier(opts.keys ?? loader, {
        now: opts.now ?? (() => NOW_MS),
        replay: opts.replay ?? new MemoryReplayStore(),
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
    it('names every deployment exactly, with no wildcard or family pattern', () => {
        for (const deployment of Object.keys(POLICY)) {
            expect(deployment).toMatch(/^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/)
        }
    })

    it.each(Object.entries(POLICY))('gives %s a non-empty op list and kinds allowlist', (_deployment, policy) => {
        expect(policy.ops.length).toBeGreaterThan(0)
        expect(new Set(policy.ops).size).toBe(policy.ops.length)
        expect(policy.ops.every((op) => (INTEGRATION_OPS as readonly string[]).includes(op))).toBe(true)
        if (policy.kinds !== ALL_KINDS) {
            expect(policy.kinds.length).toBeGreaterThan(0)
            expect(new Set(policy.kinds).size).toBe(policy.kinds.length)
        }
    })

    it.each([
        // Matching is exact. A name that only shares a prefix with a listed one gets nothing.
        'cdp',
        'cdp-foo',
        'cdp-events-consumer-canary',
        'ingestion-foo',
        'push-api',
        'temporal-worker',
        'temporal-worker-foo',
        'posthog-celery',
        'posthog-django',
        'posthog-web-django-canary',
        'posthog-web-django-two',
        'constructor',
        '__proto__',
        'toString',
        'someone-else',
        '',
    ])('gives the unknown name %j nothing', (deployment) => {
        expect(policyFor(deployment)).toBeNull()
        for (const op of INTEGRATION_OPS) {
            expect(deploymentAllows(deployment, op)).toBe(false)
        }
    })

    it('gives reverse_sync to the reverse-sync deployment only, and nothing else to it', () => {
        const holders = Object.entries(POLICY)
            .filter(([, policy]) => policy.ops.includes('reverse_sync'))
            .map(([deployment]) => deployment)

        expect(holders).toEqual([REVERSE_SYNC])
        expect(POLICY[REVERSE_SYNC]!.ops).toEqual(['reverse_sync'])
    })

    it('gives web every op except reverse_sync', () => {
        expect([...POLICY[WEB]!.ops].sort()).toEqual(INTEGRATION_OPS.filter((op) => op !== 'reverse_sync').sort())
    })

    it('keeps the cross-team and admin ops on web', () => {
        const webOnly: IntegrationOp[] = [
            'delete',
            'revoke',
            'oauth_exchange',
            'write_by_external_id',
            'delete_by_external_id',
            'delete_owner',
        ]
        for (const [deployment, policy] of Object.entries(POLICY)) {
            if (deployment !== WEB) {
                expect(policy.ops.filter((op) => webOnly.includes(op))).toEqual([])
            }
        }
    })

    it('gives read_by_external_id to web and to the tasks worker for the Slack kinds only', () => {
        const holders = Object.entries(POLICY)
            .filter(([, policy]) => policy.ops.includes('read_by_external_id'))
            .map(([deployment]) => deployment)

        expect(holders.sort()).toEqual([WEB, TASKS])
        expect(POLICY[TASKS]!.opKinds).toEqual({ read_by_external_id: ['slack', 'slack-posthog-code'] })
    })

    it.each(['temporal-worker-max-ai', 'temporal-worker-wizard'])('gives %s no refresh', (deployment) => {
        expect(POLICY[deployment]!.ops).toEqual(['read', 'resolve', 'mint'])
    })

    it('gives any kind only to the deployments whose code can touch any kind', () => {
        const anyKind = Object.entries(POLICY)
            .filter(([, policy]) => policy.kinds === ALL_KINDS)
            .map(([deployment]) => deployment)
            .filter((deployment) => !/^(cdp|ingestion)-/.test(deployment))

        expect(anyKind.sort()).toEqual([
            'posthog-admin-django',
            'posthog-integrations-reverse-sync',
            'posthog-query-django',
            WEB,
            CELERY,
            'temporal-worker-general-purpose',
        ])
        // The resolvers that hold any kind may only resolve.
        for (const [deployment, policy] of Object.entries(POLICY)) {
            if (/^(cdp|ingestion)-/.test(deployment)) {
                expect(policy.ops).toEqual(['resolve'])
            }
        }
    })

    it.each(['temporal-worker-health-check', 'temporal-worker-stamphog'])('gives %s no entry', (deployment) => {
        expect(policyFor(deployment)).toBeNull()
    })

    // Any change to who may do what shows up in review as a change to this snapshot.
    it('matches the reviewed table', () => {
        const table = Object.fromEntries(
            Object.entries(POLICY).map(([deployment, policy]) => [
                deployment,
                {
                    ops: [...policy.ops].sort().join(','),
                    kinds: policy.kinds === ALL_KINDS ? ALL_KINDS : policy.kinds.join(','),
                    sourceRows: policy.sourceRows === true,
                    opKinds: Object.fromEntries(
                        Object.entries(policy.opKinds ?? {}).map(([op, k]) => [op, k.join(',')])
                    ),
                },
            ])
        )
        expect(table).toMatchInlineSnapshot(`
          {
            "cdp-api": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "cdp-api-batch-exports": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "cdp-api-push": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "cdp-api-warehouse-webhooks": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "cdp-api-webhooks": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "cdp-cyclotron-worker-batch-resolve": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "cdp-cyclotron-worker-email": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "cdp-cyclotron-worker-hog-kafka": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "cdp-cyclotron-worker-hogflows-pg": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "cdp-cyclotron-worker-hogoverflow-kafka": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "cdp-data-warehouse-events-consumer": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "cdp-events-consumer": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "cdp-internal-events-consumer": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "cdp-legacy-events-consumer": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "cdp-realtime-only-events-consumer": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "ingestion-ai-main": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "ingestion-ai-overflow": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "ingestion-analytics-async": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "ingestion-analytics-historical": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "ingestion-analytics-main": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "ingestion-analytics-overflow": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "ingestion-analytics-team2": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "ingestion-analytics-turbo": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "ingestion-clientwarnings-main": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "ingestion-errortracking-main": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "ingestion-errortracking-overflow": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "ingestion-heatmaps-main": {
              "kinds": "*",
              "opKinds": {},
              "ops": "resolve",
              "sourceRows": false,
            },
            "posthog-admin-django": {
              "kinds": "*",
              "opKinds": {},
              "ops": "list_across_teams,read,refresh,resolve,write",
              "sourceRows": false,
            },
            "posthog-integrations-reverse-sync": {
              "kinds": "*",
              "opKinds": {},
              "ops": "reverse_sync",
              "sourceRows": false,
            },
            "posthog-query-django": {
              "kinds": "*",
              "opKinds": {},
              "ops": "read",
              "sourceRows": false,
            },
            "posthog-web-django": {
              "kinds": "*",
              "opKinds": {},
              "ops": "delete,delete_by_external_id,delete_owner,list_across_teams,mint,oauth_exchange,read,read_by_external_id,refresh,resolve,revoke,write,write_by_external_id",
              "sourceRows": false,
            },
            "posthog-worker-django": {
              "kinds": "*",
              "opKinds": {},
              "ops": "list_across_teams,read,refresh,resolve,write",
              "sourceRows": false,
            },
            "temporal-worker-batch-exports": {
              "kinds": "aws-redshift,aws-s3,azure-blob,databricks,google-cloud-service-account,postgresql,s3-compatible,snowflake",
              "opKinds": {},
              "ops": "read,refresh,resolve",
              "sourceRows": false,
            },
            "temporal-worker-data-warehouse": {
              "kinds": "apple-ads,aws-redshift,aws-s3,azure-blob,bing-ads,databricks,github,google-ads,google-analytics,google-cloud-service-account,google-search-console,google-sheets,helpscout,hubspot,instagram,intercom,linear,linkedin-ads,meta-ads,pardot,pinterest-ads,postgresql,reddit-ads,resend,s3-compatible,salesforce,snapchat,snowflake,stripe,tiktok-ads,twitter-ads,youtube-analytics",
              "opKinds": {},
              "ops": "list_across_teams,read,refresh,resolve,write",
              "sourceRows": true,
            },
            "temporal-worker-general-purpose": {
              "kinds": "*",
              "opKinds": {},
              "ops": "list_across_teams,read,refresh,resolve,write",
              "sourceRows": false,
            },
            "temporal-worker-max-ai": {
              "kinds": "github",
              "opKinds": {},
              "ops": "mint,read,resolve",
              "sourceRows": false,
            },
            "temporal-worker-tasks-agent": {
              "kinds": "github,slack,slack-posthog-code",
              "opKinds": {
                "read_by_external_id": "slack,slack-posthog-code",
              },
              "ops": "mint,read,read_by_external_id,refresh,resolve",
              "sourceRows": false,
            },
            "temporal-worker-video-export": {
              "kinds": "github,gitlab,google-calendar,jira,linear,slack",
              "opKinds": {},
              "ops": "mint,read,refresh,resolve",
              "sourceRows": false,
            },
            "temporal-worker-wizard": {
              "kinds": "github",
              "opKinds": {},
              "ops": "mint,read,resolve",
              "sourceRows": false,
            },
            "warehouse-sources-load": {
              "kinds": "apple-ads,aws-redshift,aws-s3,azure-blob,bing-ads,databricks,github,google-ads,google-analytics,google-cloud-service-account,google-search-console,google-sheets,helpscout,hubspot,instagram,intercom,linear,linkedin-ads,meta-ads,pardot,pinterest-ads,postgresql,reddit-ads,resend,s3-compatible,salesforce,snapchat,snowflake,stripe,tiktok-ads,twitter-ads,youtube-analytics",
              "opKinds": {},
              "ops": "list_across_teams,read,refresh,resolve,write",
              "sourceRows": true,
            },
          }
        `)
    })
})

describe('integration public keys', () => {
    const rsa = generateKeyPairSync('rsa', { modulusLength: 2048 })
    const ec = generateKeyPairSync('ec', { namedCurve: 'P-256' })
    const webPem = PUBLIC_FILES[`${WEB}.pub`]!

    it.each([
        ['a file that is not <deployment>.pub', { 'posthog-web-django.pem': webPem }, /only <deployment>.pub files/],
        [
            'a private key',
            { [`${WEB}.pub`]: PAIRS[WEB]!.privateKey.export({ type: 'pkcs8', format: 'pem' }).toString() },
            /private key/,
        ],
        ['an RSA key', { [`${WEB}.pub`]: publicPem(rsa.publicKey) }, /only Ed25519/],
        ['an EC key', { [`${WEB}.pub`]: publicPem(ec.publicKey) }, /only Ed25519/],
        ['a file with no PEM block', { [`${WEB}.pub`]: 'not a key' }, /no PEM public key/],
        [
            'a broken PEM block',
            { [`${WEB}.pub`]: '-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----' },
            /not a valid public key/,
        ],
        ['a name that is not a deployment', { 'Posthog_Web.pub': webPem }, /does not name a deployment/],
        // The verifier stops at the first key that verifies, so two deployments with one key
        // collapse into one identity.
        ['one key for two deployments', { [`${WEB}.pub`]: webPem, [`${CDP}.pub`]: webPem }, /also listed for/],
    ])('refuses %s', (_label, files: Record<string, string>, error) => {
        expect(() => parseIntegrationPublicKeys(files)).toThrow(error)
    })

    it('refuses to boot with no keys', () => {
        const keys = new IntegrationKeyLoader('test')
        expect(() => keys.loadFrom({})).toThrow(/no .pub files/)
        expect(keys.isLoaded).toBe(false)
    })

    it('accepts every key in a file, so a rotation keeps the old key working', async () => {
        const next = generateKeyPairSync('ed25519')
        const keys = new IntegrationKeyLoader('test')
        keys.loadFrom({ [`${WEB}.pub`]: `${publicPem(next.publicKey)}\n${webPem}` })
        const v = verifier({ keys })

        expect((await v.verify(await mint({ signWith: next.privateKey }))).deployment).toBe(WEB)
        expect((await v.verify(await mint())).deployment).toBe(WEB)
    })

    describe('from a directory', () => {
        const dirs: string[] = []

        afterEach(async () => {
            await Promise.all(dirs.splice(0).map((d) => rm(d, { recursive: true, force: true })))
        })

        it('keeps the previous keys when a reload fails', async () => {
            const dir = await mkdtemp(join(tmpdir(), 'integration-keys-'))
            dirs.push(dir)
            await writeFile(join(dir, `${WEB}.pub`), webPem)
            const keys = new IntegrationKeyLoader(dir)
            await keys.load()

            await writeFile(join(dir, 'stray.txt'), 'oops')
            await keys.reload()

            expect(keys.entries().map(([deployment]) => deployment)).toEqual([WEB])
        })
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

    it('names the deployment by the key that verified the token', async () => {
        expect((await grant({ deployment: CDP })).deployment).toBe(CDP)
        expect((await grant({ deployment: TASKS })).deployment).toBe(TASKS)
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
        ['a token signed by no known key', { signWith: generateKeyPairSync('ed25519').privateKey }, 'bad_signature'],
        // The platform-secrets registry is separate. Its HS256 key never verifies here.
        [
            'an HS256 token signed with a platform caller key',
            { alg: 'HS256', signWith: new TextEncoder().encode(PLATFORM_KEY) },
            'bad_algorithm',
        ],
        // Algorithm confusion: the public key text used as an HMAC secret.
        [
            'an HS256 token signed with the public key text',
            { alg: 'HS256', signWith: new TextEncoder().encode(PUBLIC_FILES[`${WEB}.pub`]!) },
            'bad_algorithm',
        ],
        [
            'an ES256 token',
            { alg: 'ES256', signWith: generateKeyPairSync('ec', { namedCurve: 'P-256' }).privateKey },
            'bad_algorithm',
        ],
        ['a token with no jti', { omit: ['jti'] }, 'invalid_claims'],
        ['a token with a short jti', { claims: { jti: 'short' } }, 'invalid_claims'],
        ['a token with no caller', { omit: ['caller'] }, 'invalid_claims'],
        ['a token with no ops', { claims: { ops: [] } }, 'invalid_claims'],
        ['a token with an unknown op', { claims: { ops: ['read', 'admin'] } }, 'invalid_claims'],
        ['a token with the old changes op', { claims: { ops: ['changes'] } }, 'invalid_claims'],
        ['a token whose ops is a string', { claims: { ops: 'read' } }, 'invalid_claims'],
        ['a token with no owner for a team op', { omit: ['owner'] }, 'invalid_claims'],
        ['a token with an org owner', { claims: { owner: { type: 'organization', id: 42 } } }, 'invalid_claims'],
        ['a token with a list of owners', { claims: { owner: [TEAM, { type: 'team', id: 43 }] } }, 'invalid_claims'],
        ['a token with a string owner id', { claims: { owner: { type: 'team', id: '42' } } }, 'invalid_claims'],
        ['a token with a zero owner id', { claims: { owner: { type: 'team', id: 0 } } }, 'invalid_claims'],
        ['a token with an extra owner field', { claims: { owner: { ...TEAM, org: 1 } } }, 'invalid_claims'],
        ['a cross-team token with an owner', { claims: { ops: ['list_across_teams'] } }, 'invalid_claims'],
        [
            'a token that mixes team and cross-team ops',
            { omit: ['owner'], claims: { ops: ['read', 'list_across_teams'] } },
            'invalid_claims',
        ],
        [
            'a token that mixes team and cross-team ops with an owner',
            { claims: { ops: ['read', 'read_by_external_id'] } },
            'invalid_claims',
        ],
        ...(['refresh', 'mint', 'revoke', 'delete'] as const).map(
            (op) => [`a ${op} token with no refs`, { claims: { ops: [op] } }, 'invalid_claims'] as const
        ),
        ['a token with an empty kinds list', { claims: { kinds: [] } }, 'invalid_claims'],
        ['a token with an invalid kind', { claims: { kinds: ['Slack App'] } }, 'invalid_claims'],
        ['a token with an uppercase uuid ref', { claims: { refs: [UUID_REF.toUpperCase()] } }, 'invalid_claims'],
        ['a token with a zero-padded ref', { claims: { refs: ['007'] } }, 'invalid_claims'],
        ['a token with a numeric ref', { claims: { refs: [7] } }, 'invalid_claims'],
        ['a token with a string user_id', { claims: { user_id: '7' } }, 'invalid_claims'],
        ['a token with a null user_id', { claims: { user_id: null } }, 'invalid_claims'],
        // A secrets-route claim means the minter mixed up the two schemas.
        ['a token with a keys claim', { claims: { keys: ['STRIPE_APP_SECRET_KEY'] } }, 'invalid_claims'],
    ] as [string, MintOptions, string][])('rejects %s', async (_label, opts, code) => {
        expect(await codeFor(verifier().verify(await mint(opts)))).toBe(code)
    })

    it.each([
        ['a token that is not a JWT', 'not-a-jwt', 'malformed'],
        ['an alg none token', unsigned(), 'bad_algorithm'],
    ])('rejects %s', async (_label, token, code) => {
        expect(await codeFor(verifier().verify(token))).toBe(code)
    })

    it.each([
        ['exactly 60s of life', { lifetime: MAX_TOKEN_LIFETIME_SECONDS }],
        ['exp 29s in the past, inside the skew', { iat: NOW_S - 89 }],
        ['iat 30s in the future, at the skew limit', { iat: NOW_S + 30 }],
        ['a numeric legacy ref', { claims: { refs: ['0', '123'] } }],
        ['the RFC 9864 alg name', { alg: 'Ed25519' }],
        ['a refresh token that names its ref', { claims: { ops: ['refresh'], refs: ['12'] } }],
        ['no owner when every op is cross-team', { omit: ['owner'], claims: { ops: ['list_across_teams'] } }],
    ] as [string, MintOptions][])('accepts %s', async (_label, opts) => {
        await expect(verifier().verify(await mint(opts))).resolves.toBeDefined()
    })

    it('rejects exp exactly 30s in the past', async () => {
        expect(await codeFor(verifier().verify(await mint({ iat: NOW_S - 90 })))).toBe('expired')
    })

    // JwtVerifier reads the real clock, so pin it to the instant the tokens are minted at.
    async function verifySecretsRoute(token: string): Promise<unknown> {
        vi.useFakeTimers({ toFake: ['Date'] })
        vi.setSystemTime(NOW_MS)
        try {
            const platformKeys = {
                entries: () => [[WEB, [PLATFORM_KEY]]],
                allowedSecrets: () => null,
            } as unknown as SigningKeyLoader
            return await new JwtVerifier(platformKeys).verify(token).catch((err: unknown) => err)
        } finally {
            vi.useRealTimers()
        }
    }

    it('does not let the secrets route accept an integration token', async () => {
        const token = await mint({
            alg: 'HS256',
            signWith: new TextEncoder().encode(PLATFORM_KEY),
            claims: { keys: ['STRIPE_APP_SECRET_KEY'] },
        })
        const outcome = await verifySecretsRoute(token)

        expect(outcome).toBeInstanceOf(AuthError)
        expect((outcome as AuthError).reason).toBe('bad_audience')
    })

    it('does not let the secrets route accept a token with both audiences', async () => {
        const token = await mint({
            alg: 'HS256',
            signWith: new TextEncoder().encode(PLATFORM_KEY),
            audience: [AUDIENCE, INTEGRATIONS_AUDIENCE],
            claims: { keys: ['A_KEY'] },
        })
        const outcome = await verifySecretsRoute(token)

        expect((outcome as AuthError).reason).toBe('bad_audience')
    })

    // An integrations key must not verify a secrets token, whatever audience it names.
    it('does not let an integrations key sign for the secrets route', async () => {
        const token = await mint({ audience: AUDIENCE, claims: { keys: ['STRIPE_APP_SECRET_KEY'] } })
        const outcome = await verifySecretsRoute(token)

        expect(outcome).toBeInstanceOf(AuthError)
        expect((outcome as AuthError).reason).toBe('bad_signature')
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

    it('passes the store the deployment, the jti and the last moment the token verifies', async () => {
        const claim = vi.fn<ReplayStore['claim']>().mockResolvedValue(true)
        await verifier({ replay: { claim } }).verify(
            await mint({ deployment: CDP, claims: { jti: 'a-store-jti-00001' } })
        )

        expect(claim).toHaveBeenCalledWith(
            CDP,
            'a-store-jti-00001',
            (NOW_S + MAX_TOKEN_LIFETIME_SECONDS + 30) * 1000,
            NOW_MS
        )
    })

    // Accepting the token would turn a database outage into a replay window.
    it('refuses the token when the replay store fails', async () => {
        const replay: ReplayStore = { claim: () => Promise.reject(new Error('database unavailable')) }

        await expect(verifier({ replay }).verify(await mint())).rejects.toThrow('database unavailable')
    })

    it('counts outcomes by deployment, and unknown before a key verifies', async () => {
        await grant({ deployment: CDP })
        await codeFor(verifier().verify(await mint({ signWith: generateKeyPairSync('ed25519').privateKey })))
        await codeFor(verifier().verify(await mint({ deployment: CDP, lifetime: 600 })))
        await codeFor(verifier().verify(await mint({ alg: 'HS256', signWith: new TextEncoder().encode(PLATFORM_KEY) })))

        expect(await authCount('unknown', 'bad_signature')).toBe(1)
        expect(await authCount('unknown', 'bad_algorithm')).toBe(1)
        expect(await authCount(CDP, 'lifetime_too_long')).toBe(1)
    })
})

describe('integration authorization', () => {
    it.each([
        ['cdp writing', { deployment: CDP, claims: { ops: ['resolve', 'write'] } }, 'write'],
        [
            'cdp listing across teams',
            { deployment: CDP, omit: ['owner'], claims: { ops: ['list_across_teams'] } },
            'list_across_teams',
        ],
        ['a worker deleting a team', { deployment: WORKER, claims: { ops: ['delete_owner'] } }, 'delete_owner'],
        [
            'a worker reading by external id',
            { deployment: WORKER, omit: ['owner'], claims: { ops: ['read_by_external_id'] } },
            'read_by_external_id',
        ],
        ['celery minting', { deployment: CELERY, claims: { ops: ['mint'], refs: ['12'] } }, 'mint'],
        [
            'web reading the changes feed',
            { deployment: WEB, omit: ['owner'], claims: { ops: ['reverse_sync'] } },
            'reverse_sync',
        ],
        [
            'the reverse-sync deployment reading one team',
            { deployment: REVERSE_SYNC, claims: { ops: ['read'] } },
            'read',
        ],
        // The policy allows it, but the token does not ask for it.
        ['web with an op the token lacks', { deployment: WEB, claims: { ops: ['read'] } }, 'write'],
    ] as [string, MintOptions, IntegrationOp][])('forbids %s', async (_label, opts, op) => {
        const g = await grant(opts)
        expect(await codeFor(() => g.authorize(op, { ref: '12' }))).toBe('forbidden_op')
        expect(await authCount(opts.deployment!, 'forbidden_op')).toBe(1)
    })

    it('allows an op in both the token and the policy, and binds the token owner', async () => {
        const g = await grant({ deployment: CDP, claims: { ops: ['resolve'], refs: ['123'], user_id: 9 } })
        const auth = g.authorize('resolve', { ref: '123' })

        expect(auth).toMatchObject({ op: 'resolve', deployment: CDP, owner: TEAM, userId: 9 })
        expect(auth.jti).toBe(g.claims.jti)
        expect(await authCount(CDP, 'ok')).toBe(1)
    })

    it('lets the tasks worker mint for one ref', async () => {
        const g = await grant({ deployment: TASKS, claims: { ops: ['mint'], refs: ['12'], kinds: ['github'] } })
        expect(g.authorize('mint', { ref: '12', kind: 'github' }).kinds).toEqual(['github'])
    })

    it('lets the reverse-sync deployment read the changes feed', async () => {
        const g = await grant({ deployment: REVERSE_SYNC, omit: ['owner'], claims: { ops: ['reverse_sync'] } })
        expect(g.authorize('reverse_sync').op).toBe('reverse_sync')
    })

    it('forbids a reverse_sync token that carries an owner', async () => {
        await expect(grant({ deployment: REVERSE_SYNC, claims: { ops: ['reverse_sync'] } })).rejects.toBeDefined()
    })

    it.each([
        ['slack', null],
        ['slack-posthog-code', null],
        ['github', 'forbidden_kind'],
        ['hubspot', 'forbidden_kind'],
    ])('lets the tasks worker read_by_external_id for kind %s: %s', async (kind, code) => {
        const g = await grant({ deployment: TASKS, omit: ['owner'], claims: { ops: ['read_by_external_id'] } })
        if (code) {
            expect(await codeFor(() => g.authorize('read_by_external_id', { kind }))).toBe(code)
        } else {
            expect(g.authorize('read_by_external_id', { kind }).kinds).toEqual(['slack', 'slack-posthog-code'])
        }
    })

    it('keeps the token kinds inside the op kinds for the tasks worker', async () => {
        const g = await grant({
            deployment: TASKS,
            omit: ['owner'],
            claims: { ops: ['read_by_external_id'], kinds: ['github', 'slack'] },
        })
        expect(g.authorize('read_by_external_id', { kind: 'slack' }).kinds).toEqual(['slack'])
        expect(await codeFor(() => g.authorize('read_by_external_id', { kind: 'github' }))).toBe('forbidden_kind')
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
        ['an empty kind list on a kind-narrowed token', ['slack'], [], 'forbidden_kind'],
        ['any kind when neither the token nor the policy narrows', undefined, 'github', null],
    ])('handles %s', async (_label, kinds, kind, code) => {
        const g = await grant({ claims: kinds ? { kinds } : {} })
        if (code) {
            expect(await codeFor(() => g.authorize('read', { kind }))).toBe(code)
        } else {
            expect(g.authorize('read', { kind }).op).toBe('read')
        }
    })

    it('narrows a token with no kinds to the kinds in the policy', async () => {
        const policyKinds = POLICY[TASKS]!.kinds
        const auth = (await grant({ deployment: TASKS })).authorize('read')

        expect(auth.kinds).toEqual(policyKinds)
        expect(await codeFor(() => assertKindAllowed(auth, 'hubspot'))).toBe('forbidden_kind')
    })

    it.each([
        ['a kind outside the policy', { deployment: TASKS }, 'hubspot'],
        // The token names only kinds the policy refuses, so it can touch nothing.
        [
            'a token whose kinds are all outside the policy',
            { deployment: TASKS, claims: { kinds: ['hubspot'] } },
            undefined,
        ],
    ] as [string, MintOptions, string | undefined][])('forbids %s', async (_label, opts, kind) => {
        const g = await grant(opts)
        expect(await codeFor(() => g.authorize('read', { kind }))).toBe('forbidden_kind')
    })

    it.each([
        ['a warehouse worker on a source row', { deployment: WORKER }, 'a-source-kind', true, null],
        [
            'a warehouse worker on a source row the token names',
            { deployment: WORKER, claims: { kinds: ['a-source-kind'] } },
            'a-source-kind',
            true,
            null,
        ],
        [
            'a warehouse worker on a source row the token leaves out',
            { deployment: WORKER, claims: { kinds: ['hubspot'] } },
            'a-source-kind',
            true,
            'forbidden_kind',
        ],
        // The flag is what allows the row, not the kind name.
        [
            'a warehouse worker on an unlisted kind that is not a source row',
            { deployment: WORKER },
            'a-source-kind',
            false,
            'forbidden_kind',
        ],
        ['the tasks worker on a source row', { deployment: TASKS }, 'github', true, 'forbidden_kind'],
        ['web on a source row', { deployment: WEB }, 'a-source-kind', true, null],
    ] as [string, MintOptions, string, boolean, string | null][])(
        'handles %s',
        async (_label, opts, kind, sourceRow, code) => {
            const g = await grant(opts)
            if (code) {
                expect(await codeFor(() => g.authorize('read', { kind, sourceRow }))).toBe(code)
            } else {
                expect(g.authorize('read', { kind, sourceRow }).op).toBe('read')
            }
        }
    )

    it('checks a source row that the route learns after it loads the row', async () => {
        const worker = (await grant({ deployment: WORKER, claims: { kinds: ['a-source-kind'] } })).authorize('read')
        const tasks = (await grant({ deployment: TASKS })).authorize('read')

        expect(worker.sourceRows).toEqual({ kinds: ['a-source-kind'] })
        expect(() => assertKindAllowed(worker, 'a-source-kind', { sourceRow: true })).not.toThrow()
        expect(await codeFor(() => assertKindAllowed(worker, 'other-source-kind', { sourceRow: true }))).toBe(
            'forbidden_kind'
        )
        expect(tasks.sourceRows).toBeNull()
        expect(await codeFor(() => assertKindAllowed(tasks, 'a-source-kind', { sourceRow: true }))).toBe(
            'forbidden_kind'
        )
    })

    it.each([
        ['an allowed ref', [UUID_REF, '12'], '12', null],
        ['a batch of allowed refs', [UUID_REF, '12'], [UUID_REF, '12'], null],
        ['a ref outside the token', ['12'], '13', 'forbidden_ref'],
        ['a batch with one ref outside the token', ['12'], ['12', '13'], 'forbidden_ref'],
        // A list cannot name its refs, so a ref-narrowed token must not reach it.
        ['a request that names no ref', ['12'], undefined, 'forbidden_ref'],
        ['an empty ref list', ['12'], [], 'forbidden_ref'],
        // A route that acts on one ref needs a token that names it.
        ['a ref when the token names none', undefined, '13', 'forbidden_ref'],
        ['a list when the token names no ref', undefined, undefined, null],
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

    const refreshClaims = { ops: ['read', 'refresh'], refs: ['12'] }

    it('passes the token owner to the handler, verifying the token once across middlewares', async () => {
        const res = await call(app(), await mint({ deployment: WORKER, claims: refreshClaims }))

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
        const token = await mint({ deployment: WORKER, claims: refreshClaims })

        expect((await call(hono, token)).status).toBe(200)
        expect((await call(hono, token)).status).toBe(401)
        expect(await authCount(WORKER, 'replayed')).toBe(1)
    })

    it.each([
        ['an op the deployment lacks', { deployment: CDP, claims: refreshClaims }, 'forbidden_op'],
        ['a ref the token lacks', { claims: { ops: ['read', 'refresh'], refs: ['13'] } }, 'forbidden_ref'],
    ] as [string, MintOptions, string][])('answers 403 with the code for %s', async (_label, opts, code) => {
        const res = await call(app(), await mint(opts))

        expect(res.status).toBe(403)
        expect(((await res.json()) as { error: { code: string } }).error.code).toBe(code)
    })
})
