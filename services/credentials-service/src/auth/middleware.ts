// Hono glue for integration routes. A route declares its operation, and the handler reads the
// result from `c.var.integrationAuth`:
//
//   const requireIntegrationAuth = createIntegrationAuth(verifier)
//   app.get('/v1/integrations/:ref', requireIntegrationAuth('read', { ref: (c) => c.req.param('ref') }), handler)
//
// The owner always comes from the token. No route may take it from the path, query or body.

import type { Context, MiddlewareHandler } from 'hono'

import {
    type IntegrationAuth,
    IntegrationAuthError,
    type IntegrationGrant,
    type IntegrationVerifier,
    recordRejection,
} from './integrations'
import { bearerToken } from './jwt'
import type { IntegrationOp } from './policy'
import { AuthError } from './types'

type ScopeSource = string | readonly string[] | ((c: Context) => string | readonly string[] | undefined)

export interface IntegrationScopeSpec {
    kind?: ScopeSource | undefined
    ref?: ScopeSource | undefined
}

export interface IntegrationAuthEnv<O extends IntegrationOp = IntegrationOp> {
    Variables: {
        integrationGrant: IntegrationGrant | undefined
        // `op` is widened so that stacked middlewares (say `read` then `refresh`) merge into one
        // usable type instead of an impossible intersection of two op literals.
        integrationAuth: Omit<IntegrationAuth<O>, 'op'> & { op: IntegrationOp }
    }
}

function read(source: ScopeSource | undefined, c: Context): string | readonly string[] | undefined {
    return typeof source === 'function' ? source(c) : source
}

/**
 * The JSON error body for a rejected request: `{error: {code, message}}`. A 401 carries no
 * detail, the same as the secrets route: the reason is a metric label and a log line, not
 * something an unauthenticated caller gets to enumerate. A 403 names the forbidden code,
 * because the caller holds a valid token by then.
 */
export function integrationAuthErrorResponse(c: Context, err: IntegrationAuthError): Response {
    if (err.status === 401) {
        return c.json({ error: { code: 'unauthorized', message: 'Unauthorized' } }, 401)
    }
    return c.json({ error: { code: err.code, message: err.message } }, 403)
}

export function createIntegrationAuth(
    verifier: IntegrationVerifier
): <O extends IntegrationOp>(op: O, scope?: IntegrationScopeSpec) => MiddlewareHandler<IntegrationAuthEnv<O>> {
    // Two middlewares on one request share one grant, because a second verify of the same
    // token would count as a replay.
    async function grantFor(c: Context<IntegrationAuthEnv>): Promise<IntegrationGrant> {
        const existing = c.get('integrationGrant')
        if (existing) {
            return existing
        }
        let token: string
        try {
            token = bearerToken(c.req.header('Authorization'))
        } catch (err) {
            if (err instanceof AuthError) {
                const rejection = new IntegrationAuthError('missing_token', err.message)
                recordRejection(rejection)
                throw rejection
            }
            throw err
        }
        const grant = await verifier.verify(token)
        c.set('integrationGrant', grant)
        return grant
    }

    return function requireIntegrationAuth<O extends IntegrationOp>(
        op: O,
        scope: IntegrationScopeSpec = {}
    ): MiddlewareHandler<IntegrationAuthEnv<O>> {
        return async (c, next) => {
            let auth: IntegrationAuth<O>
            try {
                const grant = await grantFor(c as unknown as Context<IntegrationAuthEnv>)
                auth = grant.authorize(op, { kind: read(scope.kind, c), ref: read(scope.ref, c) })
            } catch (err) {
                if (err instanceof IntegrationAuthError) {
                    return integrationAuthErrorResponse(c, err)
                }
                throw err
            }
            c.set('integrationAuth', auth)
            await next()
            return undefined
        }
    }
}
