import { sanitizeHeaderValue } from '@/lib/utils'

export interface McpClientInfo {
    clientName?: string | undefined
    clientVersion?: string | undefined
    protocolVersion?: string | undefined
}

/**
 * Parse the MCP `clientInfo` + `protocolVersion` out of any JSON-RPC
 * `initialize` message in the POST body (streamable-http endpoint). Body can
 * be a single object or a batch array. Returns an empty object on non-POST,
 * non-JSON, no-initialize, or any parse error.
 *
 * Clones the request before reading so the downstream MCP transport still
 * sees the original body.
 *
 * Why extract this eagerly: the agents-framework's async
 * `getInitializeRequest()` reads from Durable Object storage, which is only
 * written *after* `onStart`/`init()` has already run. On the first connect
 * that leaves `init()` with no client info to base tool-registration
 * decisions on. Parsing the body at the worker entry point closes that gap.
 */
export async function extractClientInfoFromBody(request: Request): Promise<McpClientInfo> {
    if (request.method !== 'POST') {
        return {}
    }
    try {
        const bodyText = await request.clone().text()
        if (!bodyText) {
            return {}
        }
        const parsed: unknown = JSON.parse(bodyText)
        const messages = Array.isArray(parsed) ? parsed : [parsed]
        for (const msg of messages) {
            if (!msg || typeof msg !== 'object' || (msg as { method?: unknown }).method !== 'initialize') {
                continue
            }
            const params = (
                msg as {
                    params?: {
                        clientInfo?: { name?: unknown; version?: unknown }
                        protocolVersion?: unknown
                    }
                }
            ).params
            if (!params) {
                continue
            }
            return {
                clientName: sanitizeHeaderValue(
                    typeof params.clientInfo?.name === 'string' ? params.clientInfo.name : undefined
                ),
                clientVersion: sanitizeHeaderValue(
                    typeof params.clientInfo?.version === 'string' ? params.clientInfo.version : undefined
                ),
                protocolVersion: sanitizeHeaderValue(
                    typeof params.protocolVersion === 'string' ? params.protocolVersion : undefined
                ),
            }
        }
    } catch {
        // Malformed body — fall back to the framework's async resolution path.
    }
    return {}
}
