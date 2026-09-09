import type { Region } from './constants'

export interface ClientMapping {
    us_client_id: string
    eu_client_id: string
    us_client_secret?: string
    eu_client_secret?: string
    redirect_uris?: string[]
    created_at: number
}

const CLIENT_PREFIX = 'client:'
const REGION_PREFIX = 'region:'
const CALLBACK_PREFIX = 'callback:'
const FLOW_PREFIX = 'flow:'

const REGION_SELECTION_TTL = 3600
const CALLBACK_TTL = 3600
const FLOW_TTL = 3600

// Cloudflare KV caps key names at 512 bytes. Callers may pass opaque values
// (notably the OAuth `state` parameter) that exceed that limit, so we derive
// a bounded cache key via SHA-256 before hitting KV.
export async function hashKey(raw: string): Promise<string> {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw))
    return Array.from(new Uint8Array(digest))
        .map((b) => b.toString(16).padStart(2, '0'))
        .join('')
}

export async function getClientMapping(kv: KVNamespace, proxyClientId: string): Promise<ClientMapping | null> {
    const data = await kv.get(`${CLIENT_PREFIX}${proxyClientId}`, 'json')
    return data as ClientMapping | null
}

export async function putClientMapping(kv: KVNamespace, proxyClientId: string, mapping: ClientMapping): Promise<void> {
    await kv.put(`${CLIENT_PREFIX}${proxyClientId}`, JSON.stringify(mapping))
}

export async function getRegionSelection(kv: KVNamespace, key: string): Promise<Region | null> {
    const data = await kv.get(`${REGION_PREFIX}${await hashKey(key)}`)
    if (data === 'us' || data === 'eu') {
        return data
    }
    return null
}

export async function putRegionSelection(kv: KVNamespace, key: string, region: Region): Promise<void> {
    await kv.put(`${REGION_PREFIX}${await hashKey(key)}`, region, {
        expirationTtl: REGION_SELECTION_TTL,
    })
}

export async function putCallbackRedirectUri(kv: KVNamespace, key: string, redirectUri: string): Promise<void> {
    await kv.put(`${CALLBACK_PREFIX}${await hashKey(key)}`, redirectUri, { expirationTtl: CALLBACK_TTL })
}

export async function getCallbackRedirectUri(kv: KVNamespace, key: string): Promise<string | null> {
    return kv.get(`${CALLBACK_PREFIX}${await hashKey(key)}`)
}

export interface FlowRecord {
    redirect_uri: string
    state: string | null
}

export async function putFlowRecord(kv: KVNamespace, nonce: string, record: FlowRecord): Promise<void> {
    await kv.put(`${FLOW_PREFIX}${await hashKey(nonce)}`, JSON.stringify(record), { expirationTtl: FLOW_TTL })
}

export async function getFlowRecord(kv: KVNamespace, nonce: string): Promise<FlowRecord | null> {
    const data = await kv.get(`${FLOW_PREFIX}${await hashKey(nonce)}`, 'json')
    return data as FlowRecord | null
}

export async function deleteFlowRecord(kv: KVNamespace, nonce: string): Promise<void> {
    await kv.delete(`${FLOW_PREFIX}${await hashKey(nonce)}`)
}

/**
 * Derive the regional client_id and optional client_secret rewrite for a given
 * region from a client mapping. Returns null if the mapping has no client_id
 * for the requested region.
 */
export function resolveMappingRewrite(
    mapping: ClientMapping,
    region: Region
): { regionalClientId: string; clientSecretRewrite?: { from: string; to: string } } | null {
    const regionalClientId = region === 'eu' ? mapping.eu_client_id : mapping.us_client_id
    if (!regionalClientId) {
        return null
    }

    const proxySecret = mapping.us_client_secret
    const regionalSecret = region === 'eu' ? mapping.eu_client_secret : mapping.us_client_secret
    let clientSecretRewrite: { from: string; to: string } | undefined
    if (proxySecret && regionalSecret && proxySecret !== regionalSecret) {
        clientSecretRewrite = { from: proxySecret, to: regionalSecret }
    }

    return { regionalClientId, clientSecretRewrite }
}
