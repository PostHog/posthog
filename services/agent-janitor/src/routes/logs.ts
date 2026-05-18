import { Express, Request, Response } from 'ultimate-express'

import { SessionLogStore } from '@posthog/agent-core'

/**
 * HACK — see `agent-core/src/session-logs/`. Returns the buffered tail
 * (up to MAX_BUFFERED entries, ~1h TTL) of a session's timeline as JSON.
 * The UI polls this; we dropped SSE because Django/DRF kept negotiating
 * `text/event-stream` away and returning 406.
 *
 * Slated for removal once the real loki/clickhouse pipeline lands.
 */
export interface SessionLogsDeps {
    logStore: SessionLogStore
}

export function registerSessionLogsRoutes(app: Express, deps: SessionLogsDeps): void {
    app.get('/internal/sessions/:id/logs', async (req: Request, res: Response) => {
        const sessionId = req.params.id
        if (!sessionId) {
            res.status(400).json({ error: 'session id required' })
            return
        }
        const entries = await deps.logStore.getBuffered(sessionId)
        res.json({ entries })
    })
}
