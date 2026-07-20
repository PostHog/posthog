// The 2026-07-28 MCP revision (SEP-2575) removes the `initialize` handshake and
// protocol-level sessions: every request carries its protocol version and client
// identity in `params._meta`, servers answer `server/discover` for capability
// discovery, and results carry `resultType` plus the server's identity in
// `_meta`. Legacy (≤2025-11-25) clients keep the `initialize` path untouched, so
// both dialects are served side by side and a request's dialect is detected from
// the presence of the reserved `_meta` protocol-version key.

import { SUPPORTED_PROTOCOL_VERSIONS } from '@modelcontextprotocol/sdk/types.js'

export const STATELESS_PROTOCOL_VERSION = '2026-07-28'

/** Newest first — `server/discover` advertises these, stateless first. */
export const ALL_SUPPORTED_PROTOCOL_VERSIONS: readonly string[] = [
    STATELESS_PROTOCOL_VERSION,
    ...SUPPORTED_PROTOCOL_VERSIONS,
]

export const SERVER_DISCOVER_METHOD = 'server/discover'

// Reserved `_meta` keys defined by the 2026-07-28 spec.
export const META_PROTOCOL_VERSION = 'io.modelcontextprotocol/protocolVersion'
export const META_CLIENT_INFO = 'io.modelcontextprotocol/clientInfo'
export const META_SERVER_INFO = 'io.modelcontextprotocol/serverInfo'

// Spec error-code range -32020..-32099 is reserved for MCP; -32022 is
// UnsupportedProtocolVersionError.
export const UNSUPPORTED_PROTOCOL_VERSION_ERROR_CODE = -32022

export interface RequestProtocolMeta {
    protocolVersion?: string | undefined
    clientName?: string | undefined
    clientVersion?: string | undefined
}

/**
 * Extract the reserved protocol `_meta` keys from a JSON-RPC request's params.
 * Returns an empty object for legacy requests (no `_meta` protocol version), so
 * callers can use `protocolVersion === STATELESS_PROTOCOL_VERSION` as the
 * dialect switch.
 */
export function parseRequestProtocolMeta(params: unknown): RequestProtocolMeta {
    if (!params || typeof params !== 'object') {
        return {}
    }
    const meta = (params as { _meta?: unknown })._meta
    if (!meta || typeof meta !== 'object') {
        return {}
    }
    const metaRecord = meta as Record<string, unknown>
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
    return ALL_SUPPORTED_PROTOCOL_VERSIONS.includes(version)
}
