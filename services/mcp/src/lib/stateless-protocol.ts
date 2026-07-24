// The 2026-07-28 MCP revision (SEP-2575) removes the `initialize` handshake and
// protocol-level sessions: every request carries its protocol version and client
// identity in `params._meta`, servers answer `server/discover` for capability
// discovery, and results carry `resultType` plus the server's identity in
// `_meta`. Legacy (≤2025-11-25) clients keep the `initialize` path untouched, so
// both dialects are served side by side and a request's dialect is detected from
// the reserved `_meta` protocol-version key or a modern `MCP-Protocol-Version`
// header (SEP-2243 requires the operation headers below on every modern request,
// and requires servers that process the body to reject header/body mismatches).

import { ErrorCode } from '@modelcontextprotocol/sdk/types.js'

export const STATELESS_PROTOCOL_VERSION = '2026-07-28'

/**
 * Versions selectable via per-request `_meta` — the modern era only (the spec
 * scopes per-request metadata to "revision 2026-07-28 and later"). Legacy
 * versions are deliberately absent: they are only reachable through the
 * `initialize` handshake, and advertising them here (or accepting them in
 * `_meta`) would steer a conforming modern client into retrying with a version
 * we cannot serve statelessly. `server/discover` and the
 * UnsupportedProtocolVersionError `data.supported` list both use this set.
 */
export const MODERN_PROTOCOL_VERSIONS: readonly string[] = [STATELESS_PROTOCOL_VERSION]

export const SERVER_DISCOVER_METHOD = 'server/discover'

// Reserved `_meta` keys defined by the 2026-07-28 spec.
export const META_PROTOCOL_VERSION = 'io.modelcontextprotocol/protocolVersion'
export const META_CLIENT_INFO = 'io.modelcontextprotocol/clientInfo'
export const META_CLIENT_CAPABILITIES = 'io.modelcontextprotocol/clientCapabilities'
export const META_SERVER_INFO = 'io.modelcontextprotocol/serverInfo'

// Spec error-code range -32020..-32099 is reserved for MCP; -32022 is
// UnsupportedProtocolVersionError, -32020 is SEP-2243's HeaderMismatch
// (originally -32001, reassigned by spec PR #2907).
export const UNSUPPORTED_PROTOCOL_VERSION_ERROR_CODE = -32022
export const HEADER_MISMATCH_ERROR_CODE = -32020

// SEP-2243 operation headers, mandatory on modern-dialect HTTP requests.
export const PROTOCOL_VERSION_HEADER = 'MCP-Protocol-Version'
export const MCP_METHOD_HEADER = 'Mcp-Method'
export const MCP_NAME_HEADER = 'Mcp-Name'

// Methods where `Mcp-Name` is required, and the params field it must mirror.
const NAME_HEADER_PARAM: Record<string, 'name' | 'uri'> = {
    'tools/call': 'name',
    'prompts/get': 'name',
    'resources/read': 'uri',
}

export interface RequestProtocolMeta {
    protocolVersion?: string | undefined
    clientName?: string | undefined
    clientVersion?: string | undefined
}

function requestMetaRecord(params: unknown): Record<string, unknown> | undefined {
    if (!params || typeof params !== 'object') {
        return undefined
    }
    const meta = (params as { _meta?: unknown })._meta
    if (!meta || typeof meta !== 'object') {
        return undefined
    }
    return meta as Record<string, unknown>
}

/**
 * Extract the reserved protocol `_meta` keys from a JSON-RPC request's params.
 * Returns an empty object for legacy requests (no `_meta` protocol version), so
 * callers can use `protocolVersion === STATELESS_PROTOCOL_VERSION` as the
 * dialect switch.
 */
export function parseRequestProtocolMeta(params: unknown): RequestProtocolMeta {
    const metaRecord = requestMetaRecord(params)
    if (!metaRecord) {
        return {}
    }
    const clientInfo = metaRecord[META_CLIENT_INFO]
    const clientInfoRecord =
        clientInfo && typeof clientInfo === 'object' ? (clientInfo as Record<string, unknown>) : undefined
    return {
        protocolVersion:
            typeof metaRecord[META_PROTOCOL_VERSION] === 'string'
                ? (metaRecord[META_PROTOCOL_VERSION] as string)
                : undefined,
        clientName: typeof clientInfoRecord?.name === 'string' ? clientInfoRecord.name : undefined,
        clientVersion: typeof clientInfoRecord?.version === 'string' ? clientInfoRecord.version : undefined,
    }
}

export function isSupportedProtocolVersion(version: string): boolean {
    return MODERN_PROTOCOL_VERSIONS.includes(version)
}

export interface ProtocolHeaders {
    protocolVersion: string | null
    method: string | null
    name: string | null
}

/** Accepts the minimal `Headers` surface so unit tests can pass a plain `new Headers()`. */
export function readProtocolHeaders(headers: Pick<Headers, 'get'>): ProtocolHeaders {
    return {
        protocolVersion: headers.get(PROTOCOL_VERSION_HEADER),
        method: headers.get(MCP_METHOD_HEADER),
        name: headers.get(MCP_NAME_HEADER),
    }
}

/**
 * A message speaks the modern dialect when its `_meta` declares a protocol
 * version (any value — unsupported ones still get the modern error shape) or
 * the `MCP-Protocol-Version` header carries a modern version. A legacy header
 * value (e.g. `2025-06-18`, sent by conforming ≤2025-11-25 clients) is not a
 * modern signal and must not trigger enforcement.
 */
export function isModernRequest(headers: ProtocolHeaders, meta: RequestProtocolMeta): boolean {
    return (
        meta.protocolVersion !== undefined ||
        (headers.protocolVersion !== null && isSupportedProtocolVersion(headers.protocolVersion))
    )
}

export interface ProtocolValidationError {
    code: number
    message: string
    data?: Record<string, unknown>
}

function headerRequired(header: string, context: string): ProtocolValidationError {
    return {
        code: HEADER_MISMATCH_ERROR_CODE,
        message: `Header mismatch: ${header} header is required for ${context}`,
    }
}

function headerMismatch(header: string, headerValue: string, bodyValue: string | undefined): ProtocolValidationError {
    return {
        code: HEADER_MISMATCH_ERROR_CODE,
        message: `Header mismatch: ${header} header value '${headerValue}' does not match body value ${bodyValue === undefined ? '(missing)' : `'${bodyValue}'`}`,
    }
}

function invalidMetaField(field: string, reason: string): ProtocolValidationError {
    return {
        code: ErrorCode.InvalidParams,
        message: `Invalid params: _meta ${reason} ${field}`,
    }
}

/**
 * Full modern-dialect validation for a single JSON-RPC message: the SEP-2243
 * operation headers must be present and mirror the body, and the SEP-2575
 * required `_meta` fields must be present. Returns null when valid. Callers
 * gate on `isModernRequest` first — legacy messages must never reach this.
 */
export function validateModernRequest(
    headers: ProtocolHeaders,
    message: { method?: unknown; params?: unknown }
): ProtocolValidationError | null {
    const meta = parseRequestProtocolMeta(message.params)

    // Unsupported versions win over header errors: -32022 carries the
    // machine-readable `data.supported` retry list, and fixing the version
    // forces a fresh request anyway.
    if (meta.protocolVersion !== undefined && !isSupportedProtocolVersion(meta.protocolVersion)) {
        return {
            code: UNSUPPORTED_PROTOCOL_VERSION_ERROR_CODE,
            message: `Unsupported protocol version: ${meta.protocolVersion}`,
            data: { supported: [...MODERN_PROTOCOL_VERSIONS], requested: meta.protocolVersion },
        }
    }

    if (headers.protocolVersion === null) {
        return headerRequired(PROTOCOL_VERSION_HEADER, `protocol version ${STATELESS_PROTOCOL_VERSION}`)
    }
    if (headers.protocolVersion !== meta.protocolVersion) {
        return headerMismatch(PROTOCOL_VERSION_HEADER, headers.protocolVersion, meta.protocolVersion)
    }

    const bodyMethod = typeof message.method === 'string' ? message.method : undefined
    if (headers.method === null) {
        return headerRequired(MCP_METHOD_HEADER, `protocol version ${STATELESS_PROTOCOL_VERSION}`)
    }
    if (headers.method !== bodyMethod) {
        return headerMismatch(MCP_METHOD_HEADER, headers.method, bodyMethod)
    }

    const nameParam = bodyMethod !== undefined ? NAME_HEADER_PARAM[bodyMethod] : undefined
    if (bodyMethod !== undefined && nameParam !== undefined) {
        // Non-ASCII names/URIs can't ride in an HTTP header and inherently
        // mismatch — a property of SEP-2243, not this implementation.
        const paramsRecord =
            message.params && typeof message.params === 'object'
                ? (message.params as Record<string, unknown>)
                : undefined
        const bodyName = typeof paramsRecord?.[nameParam] === 'string' ? (paramsRecord[nameParam] as string) : undefined
        if (headers.name === null) {
            return headerRequired(MCP_NAME_HEADER, bodyMethod)
        }
        if (headers.name !== bodyName) {
            return headerMismatch(MCP_NAME_HEADER, headers.name, bodyName)
        }
    }

    const metaRecord = requestMetaRecord(message.params)
    const clientInfo = metaRecord?.[META_CLIENT_INFO]
    if (!clientInfo || typeof clientInfo !== 'object') {
        return invalidMetaField(META_CLIENT_INFO, 'is missing required field')
    }
    const clientInfoRecord = clientInfo as Record<string, unknown>
    if (typeof clientInfoRecord.name !== 'string' || typeof clientInfoRecord.version !== 'string') {
        return invalidMetaField(META_CLIENT_INFO, 'requires string name and version in field')
    }
    const clientCapabilities = metaRecord?.[META_CLIENT_CAPABILITIES]
    if (!clientCapabilities || typeof clientCapabilities !== 'object') {
        return invalidMetaField(META_CLIENT_CAPABILITIES, 'is missing required field')
    }

    return null
}
