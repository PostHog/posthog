import express, { Express } from 'ultimate-express'

import { SessionQuery, collectDefaults, logger, metricsContentType, metricsText } from '@posthog/agent-core'

import { requireInternalKey } from './auth'
import { registerSessionsRoutes } from './routes/sessions'

export interface JanitorServerDeps {
    query: SessionQuery
    /** Required for `/internal/*` routes. Routes refuse traffic when undefined. */
    internalApiSharedKey: string | undefined
}

export function buildServer(deps: JanitorServerDeps): Express {
    collectDefaults()
    const app = express()

    app.use(express.json({ limit: '64kb' }))
    app.use((req, _res, next) => {
        logger.debug('agent-janitor request', { method: req.method, path: req.path })
        next()
    })

    app.get('/health', (_req, res) => {
        res.json({ ok: true })
    })

    app.get('/metrics', async (_req, res) => {
        res.set('content-type', metricsContentType())
        res.send(await metricsText())
    })

    // Path-prefix middleware: any request under /internal/* runs through the shared-key check.
    app.use('/internal', requireInternalKey({ sharedKey: deps.internalApiSharedKey }))
    registerSessionsRoutes(app, { query: deps.query })

    return app
}
