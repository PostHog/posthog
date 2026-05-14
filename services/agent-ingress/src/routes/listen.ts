import { Express, Request, Response } from 'ultimate-express'

import { SessionEvent, logger } from '@posthog/agent-core'

import { ServerDeps } from '../types'

/**
 * SSE stream of session events. Subscribes to the bus channel for the given session id
 * and writes each event as a Server-Sent Events frame.
 *
 * The bus is best-effort; durable session state lives in the queue row + final state blob.
 */
export function registerListen(app: Express, deps: ServerDeps): void {
    app.get('/listen/:id', async (req: Request, res: Response) => {
        const sessionId = req.params.id
        if (!sessionId) {
            return res.status(400).json({ error: 'session id required' })
        }

        res.setHeader('content-type', 'text/event-stream')
        res.setHeader('cache-control', 'no-cache')
        res.setHeader('connection', 'keep-alive')
        res.flushHeaders?.()
        res.write('retry: 5000\n\n')

        const sendEvent = (event: SessionEvent): void => {
            res.write(`event: ${event.type}\n`)
            res.write(`data: ${JSON.stringify(event)}\n\n`)
        }

        const unsubscribe = await deps.bus.subscribeEvents(sessionId, sendEvent)

        // Heartbeat so intermediaries (proxies, CDNs) don't time out the connection.
        const heartbeat = setInterval(() => {
            res.write(': heartbeat\n\n')
        }, 15_000)

        const cleanup = async (): Promise<void> => {
            clearInterval(heartbeat)
            try {
                await unsubscribe()
            } catch (err) {
                logger.error('listen cleanup error', { sessionId, error: String(err) })
            }
        }

        req.on('close', () => {
            void cleanup()
        })
    })
}
