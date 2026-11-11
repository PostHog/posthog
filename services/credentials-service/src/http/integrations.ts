// `/v1/integrations/*`. Each route names its operation, so the token must hold it and the
// deployment's policy must allow it. The owner always comes from the token: no route reads an
// owner or a team from the path, the query or the body.

import { type Context, Hono, type Next } from 'hono'
import { bodyLimit } from 'hono/body-limit'
import { randomUUID } from 'node:crypto'

import { IntegrationAuthError, type IntegrationVerifier } from '../auth/integrations'
import { type IntegrationAuthEnv, createIntegrationAuth, integrationAuthErrorResponse } from '../auth/middleware'
import { IntegrationApiError } from '../integrations/errors'
import { toRecordJson } from '../integrations/record'
import type { Caller, IntegrationsService } from '../integrations/service'
import {
    crossTeamBody,
    newIntegrationBody,
    parse,
    parseIdempotencyKey,
    parseIfMatch,
    parseListQuery,
    patchBody,
    refsBody,
} from '../integrations/validation'
import { logger } from '../lib/logging'

const MAX_BODY_BYTES = 1024 * 1024
const REQUEST_ID = /^[A-Za-z0-9._-]{1,128}$/
// Marks a body that is not JSON. Validation turns it into a 400 after the auth check.
const NOT_JSON = Symbol('not-json')

export interface IntegrationRoutesOptions {
    verifier: IntegrationVerifier
    service: IntegrationsService
}

type Env = {
    Variables: IntegrationAuthEnv['Variables'] & {
        requestId: string
        body: unknown
    }
}

function caller<E extends Env>(c: Context<E>): Caller {
    const auth = c.get('integrationAuth')
    return {
        auth,
        actor: {
            deployment: auth.deployment,
            caller: auth.caller,
            userId: auth.userId,
            jti: auth.jti,
            requestId: c.get('requestId'),
        },
    }
}

function body<E extends Env>(c: Context<E>): unknown {
    const value = c.get('body')
    if (value === NOT_JSON) {
        throw new IntegrationApiError('validation', 'the body must be JSON')
    }
    return value
}

/** Reads one field of the raw body for the auth scope. Anything malformed is `undefined`. */
function bodyField(c: Context, name: string): string | readonly string[] | undefined {
    const value: unknown = c.get('body')
    if (typeof value !== 'object' || value === null) {
        return undefined
    }
    const field = (value as Record<string, unknown>)[name]
    if (typeof field === 'string') {
        return field
    }
    if (Array.isArray(field) && field.every((item) => typeof item === 'string')) {
        return field as string[]
    }
    return undefined
}

function etag(version: number): string {
    return `"${version}"`
}

export function createIntegrationRoutes(opts: IntegrationRoutesOptions): Hono<Env> {
    const requireIntegrationAuth = createIntegrationAuth(opts.verifier)
    const service = opts.service
    const app = new Hono<Env>()

    app.onError((err, c) => {
        if (err instanceof IntegrationApiError) {
            return c.json(err.body(), err.status)
        }
        if (err instanceof IntegrationAuthError) {
            return integrationAuthErrorResponse(c, err)
        }
        // The name and message only. Neither the request body nor a decrypted value reaches a log.
        logger.error('integrations:internal_error', {
            route: c.req.routePath,
            requestId: c.get('requestId'),
            error: err.name,
            message: err.message,
        })
        return c.json({ error: { code: 'internal', message: 'internal error', details: {} } }, 500)
    })

    app.use(
        '*',
        bodyLimit({
            maxSize: MAX_BODY_BYTES,
            onError: (c) =>
                c.json({ error: { code: 'validation', message: 'the body is too large', details: {} } }, 413),
        })
    )

    app.use('*', async (c, next) => {
        const header = c.req.header('X-Request-Id')
        c.set('requestId', header && REQUEST_ID.test(header) ? header : randomUUID())
        // Responses can carry decrypted credentials, so no cache may store them.
        c.header('Cache-Control', 'no-store')
        await next()
    })

    // The auth scope of some routes is in the body, so read the body before the auth check.
    // Parse errors wait until after it, so an unauthenticated caller still gets a 401.
    async function readBody(c: Context<Env>, next: Next): Promise<void> {
        try {
            c.set('body', await c.req.json())
        } catch {
            c.set('body', NOT_JSON)
        }
        await next()
    }

    app.get('/', requireIntegrationAuth('read', { kind: (c) => c.req.queries('kind') }), async (c) => {
        const query = parseListQuery(c.req.queries())
        return c.json(await service.list(caller(c), query))
    })

    app.post(
        '/batch-get',
        readBody,
        requireIntegrationAuth('read', { ref: (c) => bodyField(c, 'refs') }),
        async (c) => {
            const { refs } = parse(refsBody, body(c))
            return c.json(await service.batchGet(caller(c), refs))
        }
    )

    app.post(
        '/resolve',
        readBody,
        requireIntegrationAuth('resolve', { ref: (c) => bodyField(c, 'refs') }),
        async (c) => {
            const { refs } = parse(refsBody, body(c))
            return c.json(await service.resolve(caller(c), refs))
        }
    )

    app.post(
        '/list-across-teams',
        readBody,
        requireIntegrationAuth('list_across_teams', { kind: (c) => bodyField(c, 'kinds') }),
        async (c) => {
            const filter = parse(crossTeamBody, body(c))
            return c.json(await service.listAcrossTeams(caller(c), filter))
        }
    )

    app.post('/', readBody, requireIntegrationAuth('write', { kind: (c) => bodyField(c, 'kind') }), async (c) => {
        const input = parse(newIntegrationBody, body(c))
        const idempotencyKey = parseIdempotencyKey(c.req.header('Idempotency-Key'))
        const { row, replayed } = await service.create(caller(c), input, idempotencyKey)
        c.header('ETag', etag(row.version))
        if (replayed) {
            c.header('Idempotent-Replayed', 'true')
        }
        return c.json(toRecordJson(row), 201)
    })

    app.put('/upsert', readBody, requireIntegrationAuth('write', { kind: (c) => bodyField(c, 'kind') }), async (c) => {
        const input = parse(newIntegrationBody, body(c))
        const { row, created } = await service.upsert(caller(c), input)
        c.header('ETag', etag(row.version))
        return c.json({ record: toRecordJson(row), created }, created ? 201 : 200)
    })

    app.get('/:ref', requireIntegrationAuth('read', { ref: (c) => c.req.param('ref') }), async (c) => {
        const row = await service.get(caller(c), c.req.param('ref'))
        c.header('ETag', etag(row.version))
        return c.json(toRecordJson(row))
    })

    app.patch('/:ref', requireIntegrationAuth('write', { ref: (c) => c.req.param('ref') }), readBody, async (c) => {
        const patch = parse(patchBody, body(c))
        const ifMatch = parseIfMatch(c.req.header('If-Match'))
        const row = await service.patch(caller(c), c.req.param('ref'), patch, ifMatch)
        c.header('ETag', etag(row.version))
        return c.json(toRecordJson(row))
    })

    app.delete('/:ref', requireIntegrationAuth('delete', { ref: (c) => c.req.param('ref') }), async (c) => {
        await service.delete(caller(c), c.req.param('ref'), parseIfMatch(c.req.header('If-Match')))
        return c.body(null, 204)
    })

    return app
}
