// The format matches `verify_signed_client_ip` in posthog/middleware.py: lowercase hex
// HMAC-SHA256 of `${ip}:${unixSeconds}`. A change to it must also go to Django, or every signature
// fails there.

export const SIGNED_CLIENT_IP_MAX_AGE_SECONDS = 60
export const SIGNED_CLIENT_IP_MAX_CLOCK_SKEW_SECONDS = 5

export interface SignedClientIpHeaderNames {
    ip: string
    timestamp: string
    signature: string
}

export const EDGE_CLIENT_IP_HEADERS: SignedClientIpHeaderNames = {
    ip: 'x-posthog-edge-client-ip',
    timestamp: 'x-posthog-edge-client-ip-timestamp',
    signature: 'x-posthog-edge-client-ip-signature',
}

// Read by ActivityLoggingMiddleware in posthog/middleware.py.
export const MCP_CLIENT_IP_HEADERS: SignedClientIpHeaderNames = {
    ip: 'x-posthog-mcp-client-ip',
    timestamp: 'x-posthog-mcp-client-ip-timestamp',
    signature: 'x-posthog-mcp-client-ip-signature',
}

export type SignedClientIpOutcome =
    | 'valid'
    | 'not_configured'
    | 'timestamp_out_of_window'
    | 'invalid_input'
    | 'bad_signature'

export function parseSigningKeys(value: string | undefined): string[] {
    return (value ?? '')
        .split(',')
        .map((key) => key.trim())
        .filter(Boolean)
}

const encoder = new TextEncoder()

function hmacKey(key: string, usage: 'sign' | 'verify'): Promise<CryptoKey> {
    return crypto.subtle.importKey('raw', encoder.encode(key), { name: 'HMAC', hash: 'SHA-256' }, false, [usage])
}

function hexToBytes(hex: string): Uint8Array<ArrayBuffer> | null {
    if (hex.length % 2 !== 0 || !/^[0-9a-f]*$/i.test(hex)) {
        return null
    }
    const bytes = new Uint8Array(hex.length / 2)
    for (let i = 0; i < bytes.length; i++) {
        bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16)
    }
    return bytes
}

export async function signClientIp(key: string, ip: string, timestamp: string): Promise<string> {
    const signature = await crypto.subtle.sign('HMAC', await hmacKey(key, 'sign'), encoder.encode(`${ip}:${timestamp}`))
    return Array.from(new Uint8Array(signature), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export async function signedClientIpHeaders(
    names: SignedClientIpHeaderNames,
    keys: string[],
    ip: string,
    nowSeconds: number = Math.floor(Date.now() / 1000)
): Promise<Record<string, string>> {
    const [newestKey] = keys
    if (!newestKey) {
        return {}
    }
    const timestamp = String(nowSeconds)
    return {
        [names.ip]: ip,
        [names.timestamp]: timestamp,
        [names.signature]: await signClientIp(newestKey, ip, timestamp),
    }
}

/** The caller checks that the IP itself is well formed. */
export async function verifySignedClientIp(
    ip: string | null,
    timestamp: string | null,
    signature: string | null,
    keys: string[],
    nowSeconds: number = Math.floor(Date.now() / 1000)
): Promise<SignedClientIpOutcome> {
    if (keys.length === 0) {
        return 'not_configured'
    }
    if (!ip || !timestamp || !signature || timestamp.length > 12 || !/^[0-9]+$/.test(timestamp)) {
        return 'invalid_input'
    }
    const ageSeconds = nowSeconds - Number(timestamp)
    if (ageSeconds < -SIGNED_CLIENT_IP_MAX_CLOCK_SKEW_SECONDS || ageSeconds > SIGNED_CLIENT_IP_MAX_AGE_SECONDS) {
        return 'timestamp_out_of_window'
    }
    const provided = hexToBytes(signature)
    if (!provided) {
        return 'bad_signature'
    }
    const message = encoder.encode(`${ip}:${timestamp}`)
    for (const key of keys) {
        if (await crypto.subtle.verify('HMAC', await hmacKey(key, 'verify'), provided, message)) {
            return 'valid'
        }
    }
    return 'bad_signature'
}
