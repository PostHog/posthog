import { request as httpRequest } from 'node:http'

import { InMemorySessionBus, SessionQueueManager } from '@posthog/agent-core'

import { RevisionResolver } from './resolver'
import { ServerDeps, buildServer } from './server'

/**
 * SSE flow test for `/listen/:id`. Drives a real HTTP request via node:http so we can
 * read frames as they arrive (supertest waits for the full body, which never completes
 * for an SSE stream).
 */
describe('agent-ingress /listen SSE flow', () => {
    it('streams subscribed events as SSE frames', async () => {
        const bus = new InMemorySessionBus()
        const deps: ServerDeps = {
            queue: {} as unknown as SessionQueueManager,
            bus,
            resolver: {} as unknown as RevisionResolver,
            domainSuffix: '.agents.posthog.com',
        }
        const app = buildServer(deps)

        let port = 0
        await new Promise<void>((resolve, reject) => {
            try {
                app.listen(0, () => {
                    // ultimate-express adds address() at runtime — the Express type doesn't expose it.
                    port = (app as unknown as { address(): { port: number } }).address().port
                    resolve()
                })
            } catch (err) {
                reject(err)
            }
        })

        try {
            await new Promise<void>((resolve, reject) => {
                const req = httpRequest(
                    {
                        host: 'localhost',
                        port,
                        path: '/listen/abc',
                        method: 'GET',
                    },
                    (res) => {
                        expect(res.statusCode).toBe(200)
                        expect(res.headers['content-type']).toBe('text/event-stream')
                        expect(res.headers['cache-control']).toBe('no-cache')

                        let buffer = ''
                        res.on('data', (chunk: Buffer) => {
                            buffer += chunk.toString('utf8')
                            if (buffer.includes('event: turn_completed')) {
                                expect(buffer).toContain('event: turn_started')
                                expect(buffer).toContain('"type":"turn_started"')
                                req.destroy()
                                resolve()
                            }
                        })
                        res.on('error', reject)
                    }
                )
                req.on('error', (err) => {
                    // destroy() emits ECONNRESET on the request — ignore that case
                    // because we triggered the close ourselves.
                    if ((err as NodeJS.ErrnoException).code === 'ECONNRESET') {
                        return
                    }
                    reject(err)
                })
                req.end()

                // Publish a few events once the subscription should be established.
                // Small delay so the `subscribeEvents` listener is wired before we publish.
                setTimeout(() => {
                    void bus.publishEvent('abc', { type: 'turn_started', at: '2026-05-14T00:00:00Z' })
                    void bus.publishEvent('abc', { type: 'turn_completed', at: '2026-05-14T00:00:01Z' })
                }, 50)
            })
        } finally {
            await bus.disconnect()
        }
    })
})
