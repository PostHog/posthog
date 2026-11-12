// Tokens for the `/v1/integrations/*` routes. Each caller deployment signs with its own Ed25519
// private key, and the service verifies with that deployment's public key (integration-keys.ts).
// The platform-secrets HS256 keys never verify these tokens, and these keys never verify a
// secrets token. The deployment is still whichever key verifies, never a claim.
//
// Unlike a secrets token, the claims carry the owner, so every query a route runs binds the
// owner from here and never from the request.

import { type JWTPayload, decodeProtectedHeader } from 'jose'

import { logger } from '../lib/logging'
import { integrationAuthTotal } from '../metrics'
import type { IntegrationKeyLoader } from './integration-keys'
import { type VerifiedToken, verifyDeploymentToken } from './jwt'
import {
    ALL_KINDS,
    type CrossTeamOp,
    type DeploymentPolicy,
    type IntegrationOp,
    type KindAllowlist,
    SINGLE_REF_OPS,
    isCrossTeamOp,
    isIntegrationOp,
    policyFor,
} from './policy'
import { MemoryReplayStore, type ReplayStore } from './replay'
import { AuthError, type AuthFailureReason, INTEGRATIONS_AUDIENCE } from './types'

export const MAX_TOKEN_LIFETIME_SECONDS = 60
export const CLOCK_SKEW_SECONDS = 30

/**
 * Both names mean Ed25519 here, because every key in the registry is an Ed25519 key. `EdDSA` is
 * the RFC 8037 name, `Ed25519` the RFC 9864 one. HS256, `none` and every other algorithm fail.
 */
export const INTEGRATION_ALGORITHMS: readonly string[] = ['EdDSA', 'Ed25519']

const MAX_LIST_ITEMS = 200
const KIND_PATTERN = /^[a-z0-9][a-z0-9_-]{0,63}$/
// The canonical forms of `IntegrationReference` (posthog/integrations/references.py).
const REF_PATTERN = /^(0|[1-9][0-9]{0,18}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/
const JTI_PATTERN = /^[A-Za-z0-9_-]{16,128}$/
const MAX_CALLER_LENGTH = 100

const ALLOWED_CLAIMS = new Set(['aud', 'exp', 'iat', 'jti', 'owner', 'ops', 'kinds', 'refs', 'user_id', 'caller'])

export type IntegrationAuthErrorCode =
    | Exclude<AuthFailureReason, 'no_keys_claim'>
    | 'bad_algorithm'
    | 'invalid_claims'
    | 'lifetime_too_long'
    | 'not_yet_valid'
    | 'replayed'
    | 'forbidden_op'
    | 'forbidden_kind'
    | 'forbidden_ref'

const FORBIDDEN: ReadonlySet<IntegrationAuthErrorCode> = new Set(['forbidden_op', 'forbidden_kind', 'forbidden_ref'])

export class IntegrationAuthError extends Error {
    constructor(
        readonly code: IntegrationAuthErrorCode,
        message: string,
        /** Set once a signing key verified the token. */
        readonly deployment: string | null = null
    ) {
        super(message)
        this.name = 'IntegrationAuthError'
    }

    /** 403 when the token is valid but does not allow the request, 401 otherwise. */
    get status(): 401 | 403 {
        return FORBIDDEN.has(this.code) ? 403 : 401
    }
}

export interface Owner {
    type: 'team'
    id: number
}

export interface IntegrationClaims {
    /** Null exactly when every op in the token is a cross-team op. */
    owner: Owner | null
    ops: readonly IntegrationOp[]
    /** Null means the token does not narrow by kind. */
    kinds: readonly string[] | null
    /** Null means the token does not narrow by ref. */
    refs: readonly string[] | null
    /** For the audit log only. Never an authorization input. */
    userId: number | null
    caller: string
    jti: string
    iat: number
    exp: number
}

/** What a route gets back once a request is allowed. */
export interface IntegrationAuth<O extends IntegrationOp = IntegrationOp> {
    op: O
    deployment: string
    caller: string
    /** Bind `owner.id` into every query. A cross-team op never has an owner. */
    owner: O extends CrossTeamOp ? null : Owner
    userId: number | null
    jti: string
    /**
     * The kinds this request may touch: the token's `kinds` narrowed by the deployment's policy.
     * Null means any kind. When set, a route that lists rows must only return these kinds.
     */
    kinds: readonly string[] | null
    /**
     * Whether the request may touch warehouse source rows, and of which kinds (null means any).
     * Null when it may touch none. A route that lists rows must leave source rows out then.
     */
    sourceRows: { kinds: readonly string[] | null } | null
    /** When set, the request may only touch these refs. */
    refs: readonly string[] | null
}

export interface IntegrationScope {
    /** The kind (or kinds) the request touches, when the route knows it. */
    kind?: string | readonly string[] | undefined
    /**
     * The ref (or refs) the request touches. A route that names refs needs a token whose `refs`
     * covers them. A ref-narrowed token fails on a route that names none.
     */
    ref?: string | readonly string[] | undefined
    /** True when the rows the request touches are warehouse source rows. */
    sourceRow?: boolean | undefined
}

function invalid(message: string): IntegrationAuthError {
    return new IntegrationAuthError('invalid_claims', message)
}

function isPositiveInt(value: unknown): value is number {
    return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}

function stringList(name: string, value: unknown, pattern: RegExp): string[] {
    if (!Array.isArray(value) || value.length === 0 || value.length > MAX_LIST_ITEMS) {
        throw invalid(`${name} must be a non-empty list of at most ${MAX_LIST_ITEMS} items`)
    }
    for (const item of value) {
        if (typeof item !== 'string' || !pattern.test(item)) {
            throw invalid(`${name} holds an invalid item`)
        }
    }
    return [...new Set(value as string[])]
}

function parseOwner(value: unknown): Owner {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
        throw invalid('owner must be an object')
    }
    const { type, id, ...rest } = value as Record<string, unknown>
    if (type !== 'team' || !isPositiveInt(id) || Object.keys(rest).length > 0) {
        throw invalid('owner must be {type: "team", id: <positive int>}')
    }
    return { type, id }
}

/**
 * Check every claim's shape. `exp`, `aud` and the signature are already checked by jose.
 * An unknown claim is rejected, so a token minted for the secrets route (with `keys`)
 * cannot pass here by accident.
 *
 * A token has exactly one owner, or none when every op is cross-team. It never mixes the two.
 * A token with an op that always acts on one ref (`SINGLE_REF_OPS`) must carry `refs`.
 */
export function parseIntegrationClaims(payload: JWTPayload, nowSeconds: number): IntegrationClaims {
    for (const name of Object.keys(payload)) {
        if (!ALLOWED_CLAIMS.has(name)) {
            throw invalid(`unexpected claim ${name}`)
        }
    }

    const { iat, exp, jti } = payload
    if (typeof iat !== 'number' || !Number.isFinite(iat)) {
        throw invalid('iat is required')
    }
    if (typeof exp !== 'number' || exp <= iat) {
        throw invalid('exp must be after iat')
    }
    if (exp - iat > MAX_TOKEN_LIFETIME_SECONDS) {
        throw new IntegrationAuthError(
            'lifetime_too_long',
            `exp must be at most ${MAX_TOKEN_LIFETIME_SECONDS}s after iat`
        )
    }
    if (iat > nowSeconds + CLOCK_SKEW_SECONDS) {
        throw new IntegrationAuthError('not_yet_valid', 'iat is in the future')
    }
    if (typeof jti !== 'string' || !JTI_PATTERN.test(jti)) {
        throw invalid('jti must be 16 to 128 URL-safe characters')
    }

    const caller = payload['caller']
    if (typeof caller !== 'string' || caller.length === 0 || caller.length > MAX_CALLER_LENGTH) {
        throw invalid('caller is required')
    }

    const rawOps = payload['ops']
    if (!Array.isArray(rawOps) || rawOps.length === 0 || !rawOps.every(isIntegrationOp)) {
        throw invalid('ops must be a non-empty list of known operations')
    }
    const ops: IntegrationOp[] = [...new Set<IntegrationOp>(rawOps)]

    const crossTeam = ops.filter(isCrossTeamOp)
    if (crossTeam.length > 0 && crossTeam.length < ops.length) {
        throw invalid('a token holds cross-team ops or team ops, never both')
    }
    let owner: Owner | null = null
    if (crossTeam.length > 0) {
        if (payload['owner'] !== undefined) {
            throw invalid('a cross-team token carries no owner')
        }
    } else if (payload['owner'] === undefined) {
        throw invalid('owner is required unless every op is a cross-team op')
    } else {
        owner = parseOwner(payload['owner'])
    }

    const kinds = payload['kinds'] === undefined ? null : stringList('kinds', payload['kinds'], KIND_PATTERN)
    const refs = payload['refs'] === undefined ? null : stringList('refs', payload['refs'], REF_PATTERN)
    if (refs === null && ops.some((op) => (SINGLE_REF_OPS as readonly IntegrationOp[]).includes(op))) {
        throw invalid('refs is required for an op that acts on one ref')
    }

    let userId: number | null = null
    const rawUserId = payload['user_id']
    if (rawUserId !== undefined) {
        if (!isPositiveInt(rawUserId)) {
            throw invalid('user_id must be a positive int')
        }
        userId = rawUserId
    }

    return { owner, ops, kinds, refs, userId, caller, jti, iat, exp }
}

/** The token's kinds narrowed by the policy, and by the policy's kinds for `op`. Null means any kind. */
function effectiveKinds(
    token: readonly string[] | null,
    policy: KindAllowlist,
    opKinds: readonly string[] | undefined
): readonly string[] | null {
    const allowed = opKinds ?? policy
    if (allowed === ALL_KINDS) {
        return token
    }
    return token === null ? allowed : token.filter((kind) => allowed.includes(kind))
}

/** Null when the policy gives no source rows. */
function sourceRowAccess(token: readonly string[] | null, policy: DeploymentPolicy): IntegrationAuth['sourceRows'] {
    return policy.kinds === ALL_KINDS || policy.sourceRows === true ? { kinds: token } : null
}

function kindsAllow(allowed: readonly string[] | null, requested: readonly string[]): boolean {
    // An empty list names nothing, so `every` would pass vacuously. Refuse it rather than let a
    // route treat it as "all".
    return allowed === null || (requested.length > 0 && requested.every((kind) => allowed.includes(kind)))
}

function asList(value: string | readonly string[] | undefined): readonly string[] | null {
    if (value === undefined) {
        return null
    }
    return typeof value === 'string' ? [value] : value
}

function record(deployment: string | null, outcome: IntegrationAuthErrorCode | 'ok'): void {
    integrationAuthTotal.labels({ deployment: deployment ?? 'unknown', outcome }).inc()
}

export function recordRejection(err: IntegrationAuthError): void {
    record(err.deployment, err.code)
    logger.warn('integration_auth:rejected', { deployment: err.deployment ?? 'unknown', reason: err.code })
}

/** A verified token. One per request: verifying a token again counts as a replay. */
export class IntegrationGrant {
    constructor(
        readonly deployment: string,
        readonly claims: IntegrationClaims
    ) {}

    /**
     * Allow `op` on `scope`, or throw an IntegrationAuthError. The op must be in the token
     * and in the deployment's policy. The kinds are the token's kinds narrowed by the policy's
     * kinds. A route that names refs needs a token that names them.
     */
    authorize<O extends IntegrationOp>(op: O, scope: IntegrationScope = {}): IntegrationAuth<O> {
        let access: Pick<IntegrationAuth, 'kinds' | 'sourceRows'>
        try {
            access = this.check(op, scope)
        } catch (err) {
            if (err instanceof IntegrationAuthError) {
                recordRejection(err)
            }
            throw err
        }
        record(this.deployment, 'ok')
        const { owner, userId, jti, refs, caller } = this.claims
        return {
            op,
            deployment: this.deployment,
            caller,
            // parseIntegrationClaims gives a cross-team token no owner and every other token one.
            owner: owner as unknown as IntegrationAuth<O>['owner'],
            userId,
            jti,
            ...access,
            refs,
        }
    }

    /** Throws when the request is not allowed, and returns the kinds it may touch. */
    private check(op: IntegrationOp, scope: IntegrationScope): Pick<IntegrationAuth, 'kinds' | 'sourceRows'> {
        const { ops, owner, refs } = this.claims
        const policy = policyFor(this.deployment)
        if (policy === null || !ops.includes(op) || !policy.ops.includes(op)) {
            throw this.error('forbidden_op', `operation ${op} is not allowed`)
        }
        if ((owner === null) !== isCrossTeamOp(op)) {
            throw this.error('forbidden_op', `operation ${op} does not match the token owner`)
        }

        const kinds = effectiveKinds(this.claims.kinds, policy.kinds, policy.opKinds?.[op])
        const sourceRows = sourceRowAccess(this.claims.kinds, policy)
        const requestedKinds = asList(scope.kind)
        let kindAllowed: boolean
        if (scope.sourceRow === true) {
            kindAllowed =
                sourceRows !== null && (requestedKinds === null || kindsAllow(sourceRows.kinds, requestedKinds))
        } else {
            // A token whose kinds the policy refuses entirely can touch nothing.
            kindAllowed =
                (kinds === null || kinds.length > 0 || sourceRows !== null) &&
                (requestedKinds === null || kindsAllow(kinds, requestedKinds))
        }
        if (!kindAllowed) {
            throw this.error('forbidden_kind', 'the token does not allow this kind')
        }

        const requestedRefs = asList(scope.ref)
        if (requestedRefs !== null) {
            // A route that acts on named refs needs a token that names them, so a token lifted
            // from a log reaches only the refs of the one call it was minted for.
            if (refs === null || requestedRefs.length === 0 || !requestedRefs.every((ref) => refs.includes(ref))) {
                throw this.error('forbidden_ref', 'the token does not allow this ref')
            }
        } else if (refs !== null) {
            // Fail closed: a ref-narrowed token must not reach a route that cannot name the
            // refs it touches, such as a list.
            throw this.error('forbidden_ref', 'the token does not allow this ref')
        }
        return { kinds, sourceRows }
    }

    private error(code: IntegrationAuthErrorCode, message: string): IntegrationAuthError {
        return new IntegrationAuthError(code, message, this.deployment)
    }
}

/**
 * Check a kind that a route learns only after it loads the row, for example `GET /:ref`.
 * Throws `forbidden_kind` when the token or the policy does not allow this row.
 */
export function assertKindAllowed(auth: IntegrationAuth, kind: string, opts: { sourceRow?: boolean } = {}): void {
    const allowed =
        opts.sourceRow === true
            ? auth.sourceRows !== null && kindsAllow(auth.sourceRows.kinds, [kind])
            : kindsAllow(auth.kinds, [kind])
    if (!allowed) {
        const err = new IntegrationAuthError('forbidden_kind', 'the token does not allow this kind', auth.deployment)
        recordRejection(err)
        throw err
    }
}

export interface IntegrationVerifierOptions {
    /** Defaults to the per-pod memory store. The database-backed store replaces it. */
    replay?: ReplayStore
    /** Milliseconds since the epoch. Tests replace it. */
    now?: () => number
}

/** Refuse any algorithm but EdDSA before a key is tried, so the reason is its own metric label. */
function assertIntegrationAlgorithm(token: string): void {
    let alg: unknown
    try {
        alg = decodeProtectedHeader(token).alg
    } catch {
        throw new IntegrationAuthError('malformed', 'token was not accepted')
    }
    if (typeof alg !== 'string' || !INTEGRATION_ALGORITHMS.includes(alg)) {
        throw new IntegrationAuthError('bad_algorithm', 'token was not accepted')
    }
}

export class IntegrationVerifier {
    private readonly replay: ReplayStore
    private readonly now: () => number

    constructor(
        private readonly keys: IntegrationKeyLoader,
        opts: IntegrationVerifierOptions = {}
    ) {
        this.replay = opts.replay ?? new MemoryReplayStore()
        this.now = opts.now ?? Date.now
    }

    /** Verify the token and use up its `jti`. Throws an IntegrationAuthError. */
    async verify(token: string): Promise<IntegrationGrant> {
        try {
            return await this.verifyUnrecorded(token)
        } catch (err) {
            if (err instanceof IntegrationAuthError) {
                recordRejection(err)
            }
            throw err
        }
    }

    private async verifyUnrecorded(token: string): Promise<IntegrationGrant> {
        const nowMs = this.now()
        assertIntegrationAlgorithm(token)
        let verified: VerifiedToken
        try {
            verified = await verifyDeploymentToken(this.keys, token, {
                audience: INTEGRATIONS_AUDIENCE,
                algorithms: [...INTEGRATION_ALGORITHMS],
                clockTolerance: CLOCK_SKEW_SECONDS,
                currentDate: new Date(nowMs),
            })
        } catch (err) {
            if (err instanceof AuthError && err.reason !== 'no_keys_claim') {
                throw new IntegrationAuthError(err.reason, err.message)
            }
            throw err
        }

        const { deployment, payload } = verified
        let claims: IntegrationClaims
        try {
            claims = parseIntegrationClaims(payload, Math.floor(nowMs / 1000))
        } catch (err) {
            if (err instanceof IntegrationAuthError) {
                throw new IntegrationAuthError(err.code, err.message, deployment)
            }
            throw err
        }

        // Keyed by deployment, so one deployment cannot burn another deployment's token ids.
        const expiresAtMs = (claims.exp + CLOCK_SKEW_SECONDS) * 1000
        if (!(await this.replay.claim(deployment, claims.jti, expiresAtMs, nowMs))) {
            throw new IntegrationAuthError('replayed', 'token id was already used', deployment)
        }
        return new IntegrationGrant(deployment, claims)
    }
}
