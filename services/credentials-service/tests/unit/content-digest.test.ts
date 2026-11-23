import { createHmac } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import { type JsonObject, type JsonValue, canonicalJson } from '@/crypto/canonical'
import { type DigestParts, contentDigest } from '@/integrations/digest'

interface WireParts {
    config: JsonObject
    errors: string
    external_id: string | null
    sensitive_config: JsonObject
    unreadable_keys: string[]
}

interface Vector {
    name: string
    value?: JsonValue
    parts?: WireParts
    ieee_hex?: string
    salt_b64: string
    canonical: string
    digest: string
}

// The Python implementation reads the same file, so a vector added here pins both.
const VECTORS: Vector[] = JSON.parse(
    readFileSync(new URL('../fixtures/content-digest-vectors.json', import.meta.url), 'utf8')
) as Vector[]

const VALUE_VECTORS = VECTORS.filter((v) => v.parts === undefined)
const PARTS_VECTORS = VECTORS.filter((v) => v.parts !== undefined)

function toParts(wire: WireParts): DigestParts {
    return {
        config: wire.config,
        errors: wire.errors,
        externalId: wire.external_id,
        sensitiveConfig: wire.sensitive_config,
        unreadableKeys: wire.unreadable_keys,
    }
}

function hmacHex(salt: Buffer, message: string): string {
    return createHmac('sha256', salt).update(message, 'utf8').digest('hex')
}

const PARTS: DigestParts = {
    config: { a: 1 },
    errors: '',
    externalId: 'x',
    sensitiveConfig: { token: 't' },
    unreadableKeys: [],
}

describe('content digest vectors', () => {
    it('cover both value and parts vectors', () => {
        expect(VALUE_VECTORS.length).toBeGreaterThan(0)
        expect(PARTS_VECTORS.length).toBeGreaterThan(0)
    })

    it.each(VALUE_VECTORS.map((v) => [v.name, v] as const))('canonical json: %s', (_name, vector) => {
        const value = vector.value as JsonValue
        const canonical = canonicalJson(value)
        expect(canonical).toBe(vector.canonical)
        expect(hmacHex(Buffer.from(vector.salt_b64, 'base64'), canonical)).toBe(vector.digest)
        if (vector.ieee_hex !== undefined) {
            const bits = Buffer.alloc(8)
            bits.writeDoubleBE(value as number)
            // JSON.parse('-0') is -0, which has the sign bit of the RFC vector.
            expect(bits.toString('hex')).toBe(vector.ieee_hex)
        }
    })

    it.each(PARTS_VECTORS.map((v) => [v.name, v] as const))('content digest: %s', (_name, vector) => {
        const salt = Buffer.from(vector.salt_b64, 'base64')
        const digest = contentDigest(salt, toParts(vector.parts as WireParts))
        expect(digest).toBe(vector.digest)
        expect(hmacHex(salt, vector.canonical)).toBe(digest)
    })
})

describe('contentDigest', () => {
    it('changes with the salt', () => {
        const a = contentDigest(Buffer.from('salt-a'), PARTS)
        const b = contentDigest(Buffer.from('salt-b'), PARTS)
        expect(a).toMatch(/^[0-9a-f]{64}$/)
        expect(b).not.toBe(a)
    })

    it('does not depend on the order of unreadable keys', () => {
        const salt = Buffer.from('salt-a')
        expect(contentDigest(salt, { ...PARTS, unreadableKeys: ['b', 'a'] })).toBe(
            contentDigest(salt, { ...PARTS, unreadableKeys: ['a', 'b'] })
        )
    })

    it.each([
        ['config', { ...PARTS, config: { a: 2 } }],
        ['errors', { ...PARTS, errors: 'failed' }],
        ['external id', { ...PARTS, externalId: null }],
        ['sensitive config', { ...PARTS, sensitiveConfig: { token: 'u' } }],
        ['unreadable keys', { ...PARTS, unreadableKeys: ['token'] }],
    ])('changes when %s changes', (_field, changed) => {
        const salt = Buffer.from('salt-a')
        expect(contentDigest(salt, changed)).not.toBe(contentDigest(salt, PARTS))
    })

    it('rejects an empty salt', () => {
        expect(() => contentDigest(Buffer.alloc(0), PARTS)).toThrow(TypeError)
    })

    it('rejects a value that canonical JSON cannot carry', () => {
        expect(() => contentDigest(Buffer.from('salt-a'), { ...PARTS, config: { a: Number.NaN } })).toThrow(TypeError)
    })
})
