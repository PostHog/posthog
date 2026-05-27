/**
 * Internal HTTP for Django. Endpoints:
 *   GET  /sessions/:id            — full session state
 *   POST /sessions/:id/cancel     — mark failed
 *   POST /sweep                   — trigger a sweep (used in tests / debug)
 *   GET  /healthz
 *
 * Auth: an internal shared-secret header. Real prod wiring uses team-scoped
 * tokens — kept simple here.
 */

import express, { Express, NextFunction, Request, Response } from 'express'

import { SessionQueue } from '@posthog/agent-shared-v2'

import { SweepDeps, sweepOnce } from './sweep'

export interface JanitorServerOpts {
    queue: SessionQueue
    sweep: SweepDeps
    internalSecret?: string
}

export function buildJanitorApp(opts: JanitorServerOpts): Express {
    const app = express()
    app.use(express.json())
    if (opts.internalSecret) {
        app.use((req: Request, res: Response, next: NextFunction) => {
            if (req.path === '/healthz') {
                next()
                return
            }
            const auth = req.headers['x-internal-secret']
            if (auth !== opts.internalSecret) {
                res.status(401).json({ error: 'unauthorized' })
                return
            }
            next()
        })
    }
    app.get('/healthz', (_req, res) => {
        res.json({ ok: true })
    })
    app.get('/sessions/:id', async (req, res) => {
        const s = await opts.queue.get(req.params.id)
        if (!s) {
            res.status(404).json({ error: 'not_found' })
            return
        }
        res.json(s)
    })
    app.post('/sessions/:id/cancel', async (req, res) => {
        const s = await opts.queue.get(req.params.id)
        if (!s) {
            res.status(404).json({ error: 'not_found' })
            return
        }
        await opts.queue.update(req.params.id, { state: 'failed' })
        res.json({ ok: true })
    })
    app.post('/sweep', async (_req, res) => {
        const result = await sweepOnce(opts.sweep)
        res.json(result)
    })
    return app
}
