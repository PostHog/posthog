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

const REGION_SELECTION_TTL = 3600
const CALLBACK_TTL = 3600

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
