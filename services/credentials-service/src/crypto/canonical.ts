import type { EncryptionContext } from './types'

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }
export type JsonObject = { [key: string]: JsonValue }

/**
 * JSON with object keys sorted at every level and no whitespace, so equal values always give equal
 * bytes. Throws on a value that JSON cannot carry exactly, instead of the silent `null` or key drop
 * of JSON.stringify.
 */
export function canonicalJson(value: JsonValue): string {
    if (value === null || typeof value === 'string' || typeof value === 'boolean') {
        return JSON.stringify(value)
    }
    if (typeof value === 'number') {
        if (!Number.isFinite(value)) {
            throw new TypeError('canonical JSON cannot encode a non-finite number')
        }
        return JSON.stringify(value)
    }
    if (Array.isArray(value)) {
        const items: string[] = []
        for (let i = 0; i < value.length; i++) {
            // map() skips holes and join() leaves them empty, which is not valid JSON.
            if (!(i in value)) {
                throw new TypeError('canonical JSON cannot encode a sparse array')
            }
            items.push(canonicalJson(value[i] as JsonValue))
        }
        return `[${items.join(',')}]`
    }
    if (typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype) {
        const keys = Object.keys(value).sort()
        return `{${keys.map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key] as JsonValue)}`).join(',')}}`
    }
    throw new TypeError(`canonical JSON cannot encode a value of type ${typeof value}`)
}

/** The KMS encryption context. KMS needs string values. */
export function kmsEncryptionContext(context: EncryptionContext): Record<string, string> {
    assertContext(context)
    return { integration_id: context.integrationId, owner_id: context.ownerId, kind: context.kind }
}

/** The AES-GCM AAD: the canonical JSON of the same three fields that KMS gets. */
export function contextAad(context: EncryptionContext): Buffer {
    return Buffer.from(canonicalJson(kmsEncryptionContext(context)), 'utf8')
}

function assertContext(context: EncryptionContext): void {
    // An empty field would bind every row that shares the other two fields to one context.
    for (const [field, value] of Object.entries(context)) {
        if (typeof value !== 'string' || value.length === 0) {
            throw new TypeError(`encryption context field ${field} must be a non-empty string`)
        }
    }
}
