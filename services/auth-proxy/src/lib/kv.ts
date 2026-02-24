import type { Region } from './constants'

export interface ClientMapping {
    us_client_id: string
    eu_client_id: string
    us_client_secret?: string
    eu_client_secret?: string
    created_at: number
}

const CLIENT_PREFIX = 'client:'
const REGION_PREFIX = 'region:'

const REGION_SELECTION_TTL = 3600

export async function getClientMapping(kv: KVNamespace, proxyClientId: string): Promise<ClientMapping | null> {
    const data = await kv.get(`${CLIENT_PREFIX}${proxyClientId}`, 'json')
    return data as ClientMapping | null
}

export async function putClientMapping(kv: KVNamespace, proxyClientId: string, mapping: ClientMapping): Promise<void> {
    await kv.put(`${CLIENT_PREFIX}${proxyClientId}`, JSON.stringify(mapping))
}

export async function getRegionSelection(kv: KVNamespace, key: string): Promise<Region | null> {
    const data = await kv.get(`${REGION_PREFIX}${key}`)
    if (data === 'us' || data === 'eu') {
        return data
    }
    return null
}

export async function putRegionSelection(kv: KVNamespace, key: string, region: Region): Promise<void> {
    await kv.put(`${REGION_PREFIX}${key}`, region, {
        expirationTtl: REGION_SELECTION_TTL,
    })
}
