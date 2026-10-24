import { get } from 'node:http'
import type { AddressInfo } from 'node:net'

import { Analytics } from './analytics'
import { RateLimiter } from './rate-limiter'
import { createClubHoguinServer } from './server'
import { World } from './world'

describe('server', () => {
    it('never lets a browser cache the description that names the server process', async () => {
        const server = createClubHoguinServer({
            world: new World({ makeId: () => 'id', random: () => 0.5, serverId: 'this-process' }),
            analytics: new Analytics(undefined, 'https://example.com'),
            staticFiles: new Map(),
            now: Date.now,
            trustedProxyHops: 0,
            rateLimiter: new RateLimiter(300, 600),
            serverId: 'this-process',
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        try {
            const { port } = server.address() as AddressInfo
            // The Jest setup replaces fetch with a mock, so this asks with the HTTP client of Node.
            const response = await new Promise<{ cacheControl: string | undefined; body: string }>((resolve, reject) =>
                get(`http://127.0.0.1:${port}/api/world`, (incoming) => {
                    let body = ''
                    incoming.on('data', (chunk) => (body += chunk))
                    incoming.on('end', () => resolve({ cacheControl: incoming.headers['cache-control'], body }))
                }).on('error', reject)
            )

            expect(response.cacheControl).toBe('no-store')
            expect(JSON.parse(response.body).serverId).toBe('this-process')
        } finally {
            await new Promise((resolve) => server.close(resolve))
        }
    })
})
