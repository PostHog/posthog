/**
 * Parse + validate per-request `_meta` and the SEP-2243 routing headers for
 * the v2026 pipeline. The result is a fully-typed `V2026RequestMeta`; any
 * deviation throws `V2026ProtocolError` with the right JSON-RPC code +
 * HTTP status.
 */

import {
    META_KEY_CLIENT_CAPABILITIES,
    META_KEY_CLIENT_INFO,
    META_KEY_LOG_LEVEL,
    META_KEY_PROTOCOL_VERSION,
    METHOD_HEADER,
    NAME_HEADER,
    PROTOCOL_VERSION_2026_07_28,
    PROTOCOL_VERSION_HEADER,
} from './constants'
import { invalidParams, unsupportedProtocolVersion } from './errors'

type LoggingLevel = 'debug' | 'info' | 'notice' | 'warning' | 'error' | 'critical' | 'alert' | 'emergency'
const LOG_LEVELS: ReadonlySet<string> = new Set([
    'debug',
    'info',
    'notice',
    'warning',
    'error',
    'critical',
    'alert',
    'emergency',
])

export interface Implementation {
    name: string
    version: string
    [key: string]: unknown
}

/** Narrow shape — we only care about the fields the dispatcher branches on today. */
export interface ClientCapabilities {
    elicitation?: { form?: object; url?: object }
    sampling?: object
    roots?: object
    [key: string]: unknown
}

export interface V2026RequestMeta {
    protocolVersion: typeof PROTOCOL_VERSION_2026_07_28
    clientInfo: Implementation
    clientCapabilities: ClientCapabilities
    logLevel?: LoggingLevel
    /** Method from the routing header — must match the body's method. */
    method: string
    /** Name from the routing header (when applicable: tools/call, resources/read, prompts/get). */
    name: string | undefined
}

const SUPPORTED_VERSIONS = [PROTOCOL_VERSION_2026_07_28]

interface JsonRpcRequestLike {
    jsonrpc?: unknown
    method?: unknown
    params?: unknown
    [key: string]: unknown
}

/**
 * Parse the routing headers + `_meta`. Caller is expected to have already
 * deserialized the JSON-RPC body. The function:
 *
 *   1. Pulls the routing headers (`MCP-Protocol-Version`, `Mcp-Method`,
 *      `Mcp-Name`).
 *   2. Validates the body's method matches `Mcp-Method`.
 *   3. Extracts and validates `params._meta` per SEP-2575.
 *   4. Verifies the meta `protocolVersion` matches the header (SEP-2575
 *      §Per-request Version).
 */
export function parseV2026Meta(req: Request, body: JsonRpcRequestLike): V2026RequestMeta {
    const headerVersion = req.headers.get(PROTOCOL_VERSION_HEADER)
    const method = req.headers.get(METHOD_HEADER)
    const headerName = req.headers.get(NAME_HEADER) ?? undefined

    if (!headerVersion) {
        throw invalidParams(`Missing ${PROTOCOL_VERSION_HEADER} header`)
    }
    if (!SUPPORTED_VERSIONS.includes(headerVersion as typeof PROTOCOL_VERSION_2026_07_28)) {
        throw unsupportedProtocolVersion(headerVersion, SUPPORTED_VERSIONS)
    }
    if (!method) {
        throw invalidParams(`Missing ${METHOD_HEADER} header`)
    }
    if (typeof body.method !== 'string') {
        throw invalidParams('Request body missing `method`')
    }
    if (method !== body.method) {
        throw invalidParams(`${METHOD_HEADER} header (${method}) does not match body method (${body.method})`)
    }

    const params = isRecord(body.params) ? body.params : undefined
    const meta = params && isRecord(params['_meta']) ? params['_meta'] : undefined
    if (!meta) {
        throw invalidParams('Request params missing `_meta`')
    }

    const bodyVersion = meta[META_KEY_PROTOCOL_VERSION]
    if (typeof bodyVersion !== 'string') {
        throw invalidParams(`Missing ${META_KEY_PROTOCOL_VERSION} in _meta`)
    }
    if (bodyVersion !== headerVersion) {
        throw invalidParams(
            `Header ${PROTOCOL_VERSION_HEADER} (${headerVersion}) does not match _meta (${bodyVersion})`
        )
    }

    const clientInfo = meta[META_KEY_CLIENT_INFO]
    if (!isImplementation(clientInfo)) {
        throw invalidParams(`Missing or malformed ${META_KEY_CLIENT_INFO} in _meta`)
    }

    const clientCapabilities = meta[META_KEY_CLIENT_CAPABILITIES]
    if (!isRecord(clientCapabilities)) {
        throw invalidParams(`Missing or malformed ${META_KEY_CLIENT_CAPABILITIES} in _meta`)
    }

    const logLevelRaw = meta[META_KEY_LOG_LEVEL]
    let logLevel: LoggingLevel | undefined
    if (logLevelRaw !== undefined) {
        if (typeof logLevelRaw !== 'string' || !LOG_LEVELS.has(logLevelRaw)) {
            throw invalidParams(`Invalid ${META_KEY_LOG_LEVEL} value`)
        }
        logLevel = logLevelRaw as LoggingLevel
    }

    return {
        protocolVersion: PROTOCOL_VERSION_2026_07_28,
        clientInfo,
        clientCapabilities,
        ...(logLevel ? { logLevel } : {}),
        method,
        name: headerName,
    }
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isImplementation(value: unknown): value is Implementation {
    if (!isRecord(value)) {
        return false
    }
    return typeof value['name'] === 'string' && typeof value['version'] === 'string'
}
