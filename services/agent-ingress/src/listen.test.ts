import { request as httpRequest } from 'node:http'

import { ApplicationsRepository, InMemorySessionBus, ResolvedRevision, SessionQueueManager } from '@posthog/agent-core'

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
        const resolver = {
            resolveDomain: async () =>
                ({
                    applicationId: 'b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a01',
                    applicationSlug: 'analytics-bot',
                    teamId: 7,
                    revisionId: 'b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a02',
                    revisionState: 'ready',
                    bundleS3Key: 's3://bundles/abc',
                    bundleSha256: 'abcd',
                    topLevelConfig: {},
                    parsedManifest: null,
                    auth: { mode: 'public' },
                }) as ResolvedRevision,
            resolveApplication: async () => null,
            invalidate: () => undefined,
        } as unknown as RevisionResolver
        const repository = {
            decryptEnv: async () => ({}),
            verifyTokenIdentity: async (teamId: number) => ({
                kind: 'service' as const,
                orgId: String(teamId),
                caller: 'team-secret',
            }),
        } as unknown as ApplicationsRepository

        const deps: ServerDeps = {
            queue: {
                getPrincipal: async () => null,
            } as unknown as SessionQueueManager,
            bus,
            resolver,
            repository,
            identities: {
                resolveIdentity: async () => {
                    throw new Error('IdentitiesRepository not stubbed in this test')
                },
            } as unknown as import('@posthog/agent-core').IdentitiesRepository,
            domainSuffix: '.agents.posthog.com',
            routingMode: 'domain',
        }
        const app = buildServer(deps)

        let port = 0
        await new Promise<void>((resolve, reject) => {
            try {
                app.listen(0, () => {
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
                        headers: { 'x-original-host': 'analytics-bot.agents.posthog.com' },
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
                    if ((err as NodeJS.ErrnoException).code === 'ECONNRESET') {
                        return
                    }
                    reject(err)
                })
                req.end()

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
