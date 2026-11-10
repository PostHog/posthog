// Tokens for the `/v1/integrations/*` routes. Same HS256 keys and deployment identity as the
// secrets route (jwt.ts), with a separate audience and a much shorter life. Unlike a secrets
// token, the claims carry the owner, so every query a route runs binds the owner from here and
// never from the request.

import type { JWTPayload } from 'jose'

import { logger } from '../lib/logging'
import { integrationAuthTotal } from '../metrics'
import { type VerifiedToken, verifyDeploymentToken } from './jwt'
import { type CrossTeamOp, type IntegrationOp, deploymentAllows, isCrossTeamOp, isIntegrationOp } from './policy'
import type { SigningKeyLoader } from './registry'
import { ReplayCache } from './replay'
import { AuthError, type AuthFailureReason, INTEGRATIONS_AUDIENCE } from './types'

export const MAX_TOKEN_LIFETIME_SECONDS = 60
export const CLOCK_SKEW_SECONDS = 30

const MAX_LIST_ITEMS = 200
const KIND_PATTERN = /^[a-z0-9][a-z0-9_-]{0,63}$/
// The canonical forms of `IntegrationReference` (posthog/integrations/references.py).
const REF_PATTERN = /^(0|[1-9][0-9]{0,18}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/
const JTI_PATTERN = /^[A-Za-z0-9_-]{16,128}$/
const MAX_CALLER_LENGTH = 100

const ALLOWED_CLAIMS = new Set(['aud', 'exp', 'iat', 'jti', 'owner', 'ops', 'kinds', 'refs', 'user_id', 'caller'])

export type IntegrationAuthErrorCode =
    | Exclude<AuthFailureReason, 'no_keys_claim'>
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
    /** Null only when every op in the token is a cross-team op. */
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
    /** Bind `owner.id` into every query. A cross-team op may have no owner. */
    owner: O extends CrossTeamOp ? Owner | null : Owner
    userId: number | null
    jti: string
    /** When set, a route that lists rows must only return these kinds. */
    kinds: readonly string[] | null
    /** When set, a route that lists rows must only return these refs. */
    refs: readonly string[] | null
}

export interface IntegrationScope {
    /** The kind (or kinds) the request touches, when the route knows it. */
    kind?: string | readonly string[] | undefined
    /** The ref (or refs) the request touches. A ref-narrowed token needs this. */
    ref?: string | readonly string[] | undefined
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

    let owner: Owner | null = null
    if (payload['owner'] !== undefined) {
        owner = parseOwner(payload['owner'])
    } else if (!ops.every(isCrossTeamOp)) {
        throw invalid('owner is required unless every op is a cross-team op')
    }

    const kinds = payload['kinds'] === undefined ? null : stringList('kinds', payload['kinds'], KIND_PATTERN)
    const refs = payload['refs'] === undefined ? null : stringList('refs', payload['refs'], REF_PATTERN)

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
     * and in the deployment's policy. A token that names kinds or refs allows only those.
     */
    authorize<O extends IntegrationOp>(op: O, scope: IntegrationScope = {}): IntegrationAuth<O> {
        try {
            this.check(op, scope)
        } catch (err) {
            if (err instanceof IntegrationAuthError) {
                recordRejection(err)
            }
            throw err
        }
        record(this.deployment, 'ok')
        const { owner, userId, jti, kinds, refs, caller } = this.claims
        return {
            op,
            deployment: this.deployment,
            caller,
            // check() rejects a null owner for every op that is not cross-team.
            owner: owner as unknown as IntegrationAuth<O>['owner'],
            userId,
            jti,
            kinds,
            refs,
        }
    }

    private check(op: IntegrationOp, scope: IntegrationScope): void {
        const { ops, owner, kinds, refs } = this.claims
        if (!ops.includes(op) || !deploymentAllows(this.deployment, op)) {
            throw this.error('forbidden_op', `operation ${op} is not allowed`)
        }
        if (owner === null && !isCrossTeamOp(op)) {
            throw this.error('forbidden_op', `operation ${op} needs an owner`)
        }

        const requestedKinds = asList(scope.kind)
        if (kinds !== null && requestedKinds !== null && !requestedKinds.every((kind) => kinds.includes(kind))) {
            throw this.error('forbidden_kind', 'the token does not allow this kind')
        }

        // Fail closed: a ref-narrowed token must not reach a route that cannot name the refs
        // it touches, such as a list.
        const requestedRefs = asList(scope.ref)
        if (refs !== null && (requestedRefs === null || !requestedRefs.every((ref) => refs.includes(ref)))) {
            throw this.error('forbidden_ref', 'the token does not allow this ref')
        }
    }

    private error(code: IntegrationAuthErrorCode, message: string): IntegrationAuthError {
        return new IntegrationAuthError(code, message, this.deployment)
    }
}

/**
 * Check a kind that a route learns only after it loads the row, for example `GET /:ref`.
 * Throws `forbidden_kind` when the token narrows by kind and does not name this one.
 */
export function assertKindAllowed(auth: IntegrationAuth, kind: string): void {
    if (auth.kinds !== null && !auth.kinds.includes(kind)) {
        const err = new IntegrationAuthError('forbidden_kind', 'the token does not allow this kind', auth.deployment)
        recordRejection(err)
        throw err
    }
}

export interface IntegrationVerifierOptions {
    replay?: ReplayCache
    /** Milliseconds since the epoch. Tests replace it. */
    now?: () => number
}

export class IntegrationVerifier {
    private readonly replay: ReplayCache
    private readonly now: () => number

    constructor(
        private readonly keys: SigningKeyLoader,
        opts: IntegrationVerifierOptions = {}
    ) {
        this.replay = opts.replay ?? new ReplayCache()
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
        let verified: VerifiedToken
        try {
            verified = await verifyDeploymentToken(this.keys, token, {
                audience: INTEGRATIONS_AUDIENCE,
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
        if (!this.replay.claim(`${deployment}\u0000${claims.jti}`, nowMs)) {
            throw new IntegrationAuthError('replayed', 'token id was already used', deployment)
        }
        return new IntegrationGrant(deployment, claims)
    }
}
