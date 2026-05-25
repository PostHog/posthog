import { describe, expect, it } from 'vitest'

import { createSseResponse } from '@/hono/sse-response'

async function readAllAsText(response: Response): Promise<string> {
    return await response.clone().text()
}

describe('createSseResponse', () => {
    it('returns a Response with the SSE content-type and stream body', () => {
        const { response } = createSseResponse()
        expect(response.status).toBe(200)
        expect(response.headers.get('Content-Type')).toBe('text/event-stream')
        expect(response.body).not.toBeNull()
    })

    it('writes JSONRPC messages as event: message frames with JSON data', async () => {
        const { response, writer } = createSseResponse()
        await writer.write({ jsonrpc: '2.0', id: 'a', method: 'elicitation/create', params: {} })
        await writer.write({ jsonrpc: '2.0', id: 1, result: { ok: true } })
        await writer.close()

        const text = await readAllAsText(response)
        const frames = text.split('\n\n').filter(Boolean)
        expect(frames).toHaveLength(2)
        expect(frames[0]).toBe(
            'event: message\ndata: {"jsonrpc":"2.0","id":"a","method":"elicitation/create","params":{}}'
        )
        expect(frames[1]).toBe('event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}')
    })

    it('reports closed after close() and no-ops further writes', async () => {
        const { response, writer } = createSseResponse()
        await writer.close()
        expect(writer.closed).toBe(true)
        await writer.write({ jsonrpc: '2.0', id: 'x', method: 'x', params: {} })
        // No throw; payload absent.
        const text = await readAllAsText(response)
        expect(text).toBe('')
    })

    it('tolerates write() after close without throwing', async () => {
        const { writer } = createSseResponse()
        await writer.close()
        await expect(writer.write({ jsonrpc: '2.0', id: 'x', method: 'x', params: {} })).resolves.toBeUndefined()
    })
})
