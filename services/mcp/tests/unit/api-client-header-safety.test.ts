import http from 'node:http'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { ApiClient } from '@/api/client'

// The forwarded MCP attribution headers carry client-supplied strings (`clientInfo.name`,
// the OAuth app name, the wrapping consumer), and the runtime converts header values to a
// ByteString — so a character above U+00FF in any of them throws before the request leaves
// the process, failing the API call rather than just losing attribution. The OAuth app name
// reaches the client from the token cache, which no ingest-side sanitizer covers. These
// tests go through the real `fetch` (the rest of the ApiClient suite stubs it, which
// structurally cannot catch this) against a throwaway local server.
describe('ApiClient header safety', () => {
    let server: http.Server
    let baseUrl: string
    let seenHeaders: http.IncomingHttpHeaders = {}

    beforeAll(async () => {
        server = http.createServer((req, res) => {
            seenHeaders = req.headers
            res.writeHead(200, { 'Content-Type': 'application/json' })
            res.end(JSON.stringify({ id: 2, name: 'test project' }))
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        baseUrl = `http://127.0.0.1:${(server.address() as { port: number }).port}`
    })

    afterAll(async () => {
        await new Promise<void>((resolve, reject) => server.close((err) => (err ? reject(err) : resolve())))
    })

    it('resolves the project when client-supplied names contain characters headers cannot carry', async () => {
        const client = new ApiClient({
            apiToken: 'phx_test',
            baseUrl,
            clientUserAgent: 'my-agent/1.0',
            mcpClientName: 'Claude \u{1F389} Code',
            mcpClientVersion: '1.0.0',
            mcpConsumer: 'wrapper',
            oauthClientName: 'Acme — Analytics',
        })

        const result = await client.projects().get({ projectId: '2' })

        expect(result.success).toBe(true)
        expect(seenHeaders['x-posthog-mcp-client-name']).toBe('Claude  Code')
        expect(seenHeaders['x-posthog-mcp-oauth-client-name']).toBe('Acme  Analytics')
        expect(seenHeaders['x-posthog-mcp-consumer']).toBe('wrapper')
    })

    it('confirms the unsanitized value would have been fatal', () => {
        // Guards the test above from silently passing if header validation ever stops
        // being enforced in this environment.
        expect(() => new Headers({ 'x-posthog-mcp-oauth-client-name': 'Acme — Analytics' })).toThrow(/ByteString/)
    })
})
