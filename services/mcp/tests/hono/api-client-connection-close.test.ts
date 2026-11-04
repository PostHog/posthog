import { createHash } from 'node:crypto'
import { once } from 'node:events'
import { type Server, createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import { gzipSync } from 'node:zlib'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { ApiClient } from '@/api/client'
import { installHttpDispatcher } from '@/hono/http-dispatcher'

// Django gzips POST /query/ responses, and a server that closes each connection sends FIN right
// after the body. Node 24.22.1's bundled undici paused its HTTP/1 parser while the gzip decoder
// caught up, then threw assert(!this.paused) from the socket 'end' handler and exited the process
// (nodejs/undici#5360).
// The body must stay large and hard to compress, because a small body never pauses the parser.
const queryResult = {
    results: Array.from({ length: 16_384 }, (_, i) => [createHash('sha256').update(String(i)).digest('hex')]),
}
const gzippedQueryResult = gzipSync(JSON.stringify(queryResult))

describe('ApiClient against a server that closes every connection', () => {
    let server: Server
    let client: ApiClient
    let connectionClosed: Promise<unknown>

    beforeAll(async () => {
        installHttpDispatcher()
        server = createServer((_req, res) => {
            res.writeHead(200, {
                'Content-Type': 'application/json',
                'Content-Encoding': 'gzip',
                'Content-Length': gzippedQueryResult.length,
                Connection: 'close',
            })
            res.end(gzippedQueryResult)
        })
        server.on('connection', (socket) => {
            connectionClosed = once(socket, 'close')
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        const { port } = server.address() as AddressInfo
        client = new ApiClient({ apiToken: 'test-token', baseUrl: `http://127.0.0.1:${port}` })
    })

    afterAll(async () => {
        await new Promise((resolve) => server.close(resolve))
    })

    it('reads a large gzip query result without an uncaught exception', { timeout: 5000 }, async () => {
        // In production an uncaught exception exits the process. Vitest only reports it, and the
        // throw can come after the body is complete, so the test records it to fail on it.
        const uncaught: unknown[] = []
        const recordUncaught = (error: unknown): void => {
            uncaught.push(error)
        }
        process.on('uncaughtException', recordUncaught)
        try {
            const response = await client.request({
                method: 'POST',
                path: '/api/projects/1/query/',
                body: { query: { kind: 'HogQLQuery', query: 'select 1' } },
            })
            // The client runs its socket 'end' handler on a tick before the server can see the
            // connection close, so after this wait a throw from that handler is in `uncaught`.
            await connectionClosed

            expect(response).toEqual(queryResult)
            expect(uncaught).toEqual([])
        } finally {
            process.off('uncaughtException', recordUncaught)
        }
    })
})
