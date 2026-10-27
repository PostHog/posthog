import { ErrorCode, JSONRPC_VERSION } from '@modelcontextprotocol/sdk/types.js'

import { redactToken } from '@/lib/utils'

import { requestBodyTooLargeTotal } from './metrics'

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

export function rejectBodyTooLarge(token: string | undefined): Response {
    requestBodyTooLargeTotal.inc()
    // A log alert matches this line, so keep its prefix stable. The token is cut to its last 4
    // characters, which traces a repeat sender without exposing the credential.
    console.warn(
        '[RequestBody] body too large',
        JSON.stringify({ maxBytes: MAX_BODY_BYTES, token: token ? redactToken(token) : null })
    )
    return new Response(
        JSON.stringify({
            jsonrpc: JSONRPC_VERSION,
            id: null,
            error: { code: ErrorCode.InvalidRequest, message: 'Request body too large' },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
    )
}
