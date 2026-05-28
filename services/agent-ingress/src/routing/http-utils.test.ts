/**
 * Unit tests for the ingress error-handling middleware. The per-route tests
 * in `server.test.ts` cover the integration; these tests exercise the
 * typed-branch translations of `errorHandler` directly so future routes that
 * reach for `.parse()` (or throw the typed errors directly) are guaranteed
 * to get the structured response.
 */

import express, { Request, Response, Router } from 'express'
import request from 'supertest'
import { z } from 'zod'

import { createLogger } from '@posthog/agent-shared'

import { asyncHandler, errorHandler } from './http-utils'
import { AmbiguousRevisionError } from './resolver'

function buildHarness(routes: (r: Router) => void): express.Express {
    const app = express()
    app.use(express.json())
    const r = Router()
    routes(r)
    app.use(r)
    app.use(errorHandler(createLogger('test')))
    return app
}

describe('errorHandler', () => {
    it('translates a ZodError thrown inside an async route into a structured 400', async () => {
        // A future route reaching for `.parse()` instead of `.safeParse()`
        // throws ZodError; the global middleware should still respond cleanly.
        const Schema = z.object({ name: z.string().min(1) })
        const app = buildHarness((r) => {
            r.post(
                '/parse',
                asyncHandler(async (req: Request, res: Response) => {
                    const parsed = Schema.parse(req.body)
                    res.json(parsed)
                })
            )
        })
        const res = await request(app).post('/parse').send({ name: '' })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_request')
        expect(res.body.issues[0].path).toEqual(['name'])
        expect(res.body.issues[0].message).toMatch(/too small|at least 1/i)
    })

    it('translates AmbiguousRevisionError into a 400 with candidate ids', async () => {
        const app = buildHarness((r) => {
            r.get(
                '/ambiguous',
                asyncHandler(async (_req: Request, _res: Response) => {
                    throw new AmbiguousRevisionError('app-uuid', 'abcd', ['rev-1', 'rev-2'])
                })
            )
        })
        const res = await request(app).get('/ambiguous')
        expect(res.status).toBe(400)
        expect(res.body).toMatchObject({
            error: 'ambiguous_revision',
            prefix: 'abcd',
            application_id: 'app-uuid',
            candidates: ['rev-1', 'rev-2'],
        })
    })

    it('translates a malformed JSON body into a 400 invalid_json', async () => {
        const app = buildHarness((r) => {
            r.post('/anything', (_req: Request, res: Response) => res.json({ ok: true }))
        })
        const res = await request(app).post('/anything').set('Content-Type', 'application/json').send('{not valid json')
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_json')
    })

    it('falls back to a JSON 500 for unknown errors', async () => {
        const app = buildHarness((r) => {
            r.get(
                '/boom',
                asyncHandler(async () => {
                    throw new Error('unexpected')
                })
            )
        })
        const res = await request(app).get('/boom')
        expect(res.status).toBe(500)
        expect(res.body).toEqual({ error: 'internal_error' })
    })
})

describe('asyncHandler', () => {
    it('forwards synchronous thrown errors into the global error middleware', async () => {
        // Synchronous throw inside an async function still becomes a rejected
        // promise — asyncHandler should funnel it.
        const app = buildHarness((r) => {
            r.get(
                '/sync-throw',
                asyncHandler(() => {
                    throw new AmbiguousRevisionError('app', 'ab', ['r1', 'r2'])
                })
            )
        })
        const res = await request(app).get('/sync-throw')
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('ambiguous_revision')
    })
})
