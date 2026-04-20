import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js'
import type { IncomingMessage, ServerResponse } from 'node:http'

export function createSSEResponseAdapter(
    controller: ReadableStreamDefaultController<Uint8Array>,
    onClose: () => void
): { transport: SSEServerTransport; start: () => Promise<void> } {
    const encoder = new TextEncoder()

    const res = {
        writeHead: () => res,
        write: (chunk: string) => {
            controller.enqueue(encoder.encode(chunk))
            return true
        },
        on: () => res,
        end: () => {
            controller.close()
            onClose()
        },
    } as unknown as ServerResponse

    const transport = new SSEServerTransport('/sse', res)

    return { transport, start: () => transport.start() }
}

export async function handleSSEPostMessage(
    transport: SSEServerTransport,
    headers: Headers,
    url: string,
    body: unknown
): Promise<void> {
    const req = {
        method: 'POST',
        headers: Object.fromEntries(headers.entries()),
        url,
    } as unknown as IncomingMessage

    const res = {
        writeHead: () => res,
        end: () => undefined,
    } as unknown as ServerResponse

    await transport.handlePostMessage(req, res, body)
}
