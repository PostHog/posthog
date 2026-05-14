import { createServer, Server } from 'node:http'
import { AddressInfo } from 'node:net'

import { InternalApiClient } from './client'

interface RecordedRequest {
    method: string
    url: string
    headers: Record<string, string | string[] | undefined>
    body: string
}

interface FakeServerHandle {
    server: Server
    baseUrl: string
    recorded: RecordedRequest[]
    setHandler: (handler: HandlerFn) => void
    close: () => Promise<void>
}

type HandlerFn = (req: RecordedRequest) => { status: number; body?: unknown; delayMs?: number }

async function startFakeServer(initialHandler: HandlerFn): Promise<FakeServerHandle> {
    const recorded: RecordedRequest[] = []
    let handler: HandlerFn = initialHandler

    const server = createServer((req, res) => {
        let body = ''
        req.on('data', (chunk: Buffer) => {
            body += chunk.toString('utf8')
        })
        req.on('end', () => {
            const recordedReq: RecordedRequest = {
                method: req.method ?? '',
                url: req.url ?? '',
                headers: req.headers,
                body,
            }
            recorded.push(recordedReq)
            const reply = handler(recordedReq)
            const send = (): void => {
                res.statusCode = reply.status
                if (reply.body !== undefined) {
                    res.setHeader('content-type', 'application/json')
                    res.end(JSON.stringify(reply.body))
                } else {
                    res.end()
                }
            }
            if (reply.delayMs) {
                setTimeout(send, reply.delayMs)
            } else {
                send()
            }
        })
    })

    await new Promise<void>((resolve) => server.listen(0, resolve))
    const port = (server.address() as AddressInfo).port
    return {
        server,
        baseUrl: `http://localhost:${port}`,
        recorded,
        setHandler: (next) => {
            handler = next
        },
        close: () =>
            new Promise<void>((resolve) => {
                server.close(() => resolve())
            }),
    }
}

const VALID_RESOLVE_PAYLOAD = {
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
}

describe('InternalApiClient', () => {
    let fake: FakeServerHandle

    afterEach(async () => {
        await fake.close()
    })

    describe('resolve', () => {
        it('returns the parsed payload on 200', async () => {
            fake = await startFakeServer(() => ({ status: 200, body: VALID_RESOLVE_PAYLOAD }))
            const client = new InternalApiClient({ baseUrl: fake.baseUrl })

            const result = await client.resolve({ domain: 'analytics-bot.agents.posthog.com' })

            expect(result?.applicationSlug).toBe('analytics-bot')
            expect(fake.recorded[0].url).toContain('/internal/agents/applications/resolve')
            expect(fake.recorded[0].url).toContain('domain=analytics-bot.agents.posthog.com')
        })

        it('returns null on 404', async () => {
            fake = await startFakeServer(() => ({ status: 404 }))
            const client = new InternalApiClient({ baseUrl: fake.baseUrl })

            const result = await client.resolve({ domain: 'missing.agents.posthog.com' })
            expect(result).toBeNull()
        })

        it('throws on 5xx', async () => {
            fake = await startFakeServer(() => ({ status: 500, body: { error: 'boom' } }))
            const client = new InternalApiClient({ baseUrl: fake.baseUrl })

            await expect(client.resolve({ domain: 'x.agents.posthog.com' })).rejects.toThrow(/500/)
        })

        it('forwards the shared key on the x-internal-key header', async () => {
            fake = await startFakeServer(() => ({ status: 200, body: VALID_RESOLVE_PAYLOAD }))
            const client = new InternalApiClient({ baseUrl: fake.baseUrl, sharedKey: 'sek-ret' })

            await client.resolve({ domain: 'analytics-bot.agents.posthog.com' })

            expect(fake.recorded[0].headers['x-internal-key']).toBe('sek-ret')
        })

        it('does not send x-internal-key when no key is configured', async () => {
            fake = await startFakeServer(() => ({ status: 200, body: VALID_RESOLVE_PAYLOAD }))
            const client = new InternalApiClient({ baseUrl: fake.baseUrl })

            await client.resolve({ domain: 'analytics-bot.agents.posthog.com' })

            expect(fake.recorded[0].headers['x-internal-key']).toBeUndefined()
        })

        it('aborts when the request exceeds the timeout', async () => {
            fake = await startFakeServer(() => ({ status: 200, body: VALID_RESOLVE_PAYLOAD, delayMs: 200 }))
            const client = new InternalApiClient({ baseUrl: fake.baseUrl, timeoutMs: 25 })

            await expect(client.resolve({ domain: 'slow.agents.posthog.com' })).rejects.toThrow()
        })
    })

    describe('decryptSecrets', () => {
        it('sends a POST with the requested names and parses the reply', async () => {
            fake = await startFakeServer(() => ({
                status: 200,
                body: { secrets: { OPENAI_API_KEY: 'sk-1', POSTHOG_KEY: 'phc' } },
            }))
            const client = new InternalApiClient({ baseUrl: fake.baseUrl, sharedKey: 'sek-ret' })

            const result = await client.decryptSecrets('b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a01', [
                'OPENAI_API_KEY',
                'POSTHOG_KEY',
            ])

            expect(result.secrets.OPENAI_API_KEY).toBe('sk-1')
            const recorded = fake.recorded[0]
            expect(recorded.method).toBe('POST')
            expect(recorded.url).toBe('/internal/agents/secrets/b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a01/decrypt')
            expect(JSON.parse(recorded.body)).toEqual({ names: ['OPENAI_API_KEY', 'POSTHOG_KEY'] })
            expect(recorded.headers['x-internal-key']).toBe('sek-ret')
        })

        it('throws on non-2xx replies', async () => {
            fake = await startFakeServer(() => ({ status: 403, body: { error: 'forbidden' } }))
            const client = new InternalApiClient({ baseUrl: fake.baseUrl })

            await expect(
                client.decryptSecrets('b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a01', ['ANY'])
            ).rejects.toThrow(/403/)
        })
    })
})
