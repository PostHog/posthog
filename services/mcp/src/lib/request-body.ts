import { ErrorCode, JSONRPC_VERSION } from '@modelcontextprotocol/sdk/types.js'

export const MAX_BODY_BYTES = 1_048_576

// A chunked request carries no Content-Length, so the cap must also hold while the body streams in.
export async function readBodyWithinLimit(req: Request, maxBytes: number): Promise<string | undefined> {
    if (!req.body) {
        return ''
    }
    const reader = req.body.getReader()
    const decoder = new TextDecoder()
    let size = 0
    let text = ''
    for (;;) {
        const { done, value } = await reader.read()
        if (done) {
            return text + decoder.decode()
        }
        size += value.byteLength
        if (size > maxBytes) {
            await reader.cancel()
            return undefined
        }
        text += decoder.decode(value, { stream: true })
    }
}

export function bodyTooLargeResponse(): Response {
    return new Response(
        JSON.stringify({
            jsonrpc: JSONRPC_VERSION,
            id: null,
            error: { code: ErrorCode.InvalidRequest, message: 'Request body too large' },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
    )
}

/** The request with its body read within the cap, so later steps can read it again. Undefined above the cap. */
export async function withBodyWithinLimit(request: Request, maxBytes: number): Promise<Request | undefined> {
    if (!request.body) {
        return request
    }
    const text = await readBodyWithinLimit(request, maxBytes)
    return text === undefined ? undefined : new Request(request, { body: text })
}
