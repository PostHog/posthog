import { DecryptCommand, GenerateDataKeyCommand } from '@aws-sdk/client-kms'
import { randomBytes } from 'node:crypto'
import { describe, expect, it, vi } from 'vitest'

import { EnvelopeCipher } from '@/cache/envelope.js'

// A fake KMS that wraps a data key by prefixing it, so unwrapping is verifiable without
// real crypto. It also records the encryption context, which is half of what binds a
// sealed value to this service and environment.
function fakeKms(): { client: any; generateCalls: number; decryptCalls: number; contexts: unknown[] } {
    const state = { generateCalls: 0, decryptCalls: 0, contexts: [] as unknown[] }
    const client = {
        send(command: unknown) {
            if (command instanceof GenerateDataKeyCommand) {
                state.generateCalls++
                state.contexts.push(command.input.EncryptionContext)
                const plaintext = randomBytes(32)
                return Promise.resolve({
                    Plaintext: plaintext,
                    CiphertextBlob: Buffer.concat([Buffer.from('wrapped:'), plaintext]),
                })
            }
            if (command instanceof DecryptCommand) {
                state.decryptCalls++
                state.contexts.push(command.input.EncryptionContext)
                const blob = Buffer.from(command.input.CiphertextBlob as Uint8Array)
                return Promise.resolve({ Plaintext: blob.subarray('wrapped:'.length) })
            }
            throw new Error('unexpected KMS command')
        },
    }
    return Object.assign(state, { client }) as any
}

function cipherWith(kms: any, now: () => number = Date.now, rotationMs = 3_600_000): EnvelopeCipher {
    return new EnvelopeCipher({ kms: kms.client, keyId: 'test-cmk', env: 'prod-us', rotationMs, now })
}

describe('envelope cipher', () => {
    it('round-trips a value under the same cache key', async () => {
        const cipher = cipherWith(fakeKms())
        const sealed = await cipher.seal('sk-live-secret', 'provider:stripe')
        expect(await cipher.open(sealed, 'provider:stripe')).toBe('sk-live-secret')
    })

    it('never puts the plaintext in the sealed record', async () => {
        const sealed = await cipherWith(fakeKms()).seal('sk-live-secret', 'provider:stripe')
        expect(sealed).not.toContain('sk-live-secret')
    })

    // The AAD is `<env>|<cacheKey>`. Without it a ciphertext could be moved between
    // secrets, so a low-value credential's entry could be replayed as a high-value one.
    it('refuses to open a value under a different cache key', async () => {
        const cipher = cipherWith(fakeKms())
        const sealed = await cipher.seal('sk-live-secret', 'provider:stripe')
        await expect(cipher.open(sealed, 'provider:google-ads')).rejects.toThrow(Error)
    })

    it('refuses to open a value sealed in a different environment', async () => {
        const kms = fakeKms()
        const inProdUs = cipherWith(kms)
        const inProdEu = new EnvelopeCipher({
            kms: kms.client,
            keyId: 'test-cmk',
            env: 'prod-eu',
            rotationMs: 3_600_000,
        })
        const sealed = await inProdUs.seal('sk-live-secret', 'provider:stripe')
        await expect(inProdEu.open(sealed, 'provider:stripe')).rejects.toThrow(Error)
    })

    it.each([
        ['ciphertext', 'c'],
        ['auth tag', 't'],
        ['nonce', 'n'],
    ])('refuses to open a record with a tampered %s', async (_label, field) => {
        const cipher = cipherWith(fakeKms())
        const record = JSON.parse(await cipher.seal('sk-live-secret', 'provider:stripe'))
        record[field] = Buffer.from(randomBytes(Buffer.from(record[field], 'base64').length)).toString('base64')
        await expect(cipher.open(JSON.stringify(record), 'provider:stripe')).rejects.toThrow(Error)
    })

    it('binds the wrapped data key to this service and environment via the KMS context', async () => {
        const kms = fakeKms()
        await cipherWith(kms).seal('v', 'provider:stripe')
        expect(kms.contexts[0]).toEqual({ service: 'integration-service', env: 'prod-us' })
    })

    it('reuses one data key across many seals rather than calling KMS per write', async () => {
        const kms = fakeKms()
        const cipher = cipherWith(kms)
        for (let i = 0; i < 10; i++) {
            await cipher.seal(`value-${i}`, `provider:p${i}`)
        }
        expect(kms.generateCalls).toBe(1)
    })

    it('generates one data key under concurrent first writes', async () => {
        const kms = fakeKms()
        const cipher = cipherWith(kms)
        await Promise.all(Array.from({ length: 8 }, (_, i) => cipher.seal(`v${i}`, `provider:p${i}`)))
        expect(kms.generateCalls).toBe(1)
    })

    // The reason the wrapped key travels inside the record: a rotation must not orphan
    // everything already in Redis.
    it('still opens a record sealed under a previous data key after rotation', async () => {
        const kms = fakeKms()
        let clock = 0
        const cipher = cipherWith(kms, () => clock, 1000)

        const sealedOld = await cipher.seal('older-value', 'provider:stripe')
        clock += 5000
        const sealedNew = await cipher.seal('newer-value', 'provider:stripe')

        expect(kms.generateCalls).toBe(2)
        expect(await cipher.open(sealedOld, 'provider:stripe')).toBe('older-value')
        expect(await cipher.open(sealedNew, 'provider:stripe')).toBe('newer-value')
    })

    it('unwraps an unknown data key once and memoizes it', async () => {
        const kms = fakeKms()
        const writer = cipherWith(kms)
        const sealed = await writer.seal('shared-value', 'provider:stripe')

        // A second replica: same CMK, no data key of its own yet.
        const reader = cipherWith(kms)
        expect(await reader.open(sealed, 'provider:stripe')).toBe('shared-value')
        expect(await reader.open(sealed, 'provider:stripe')).toBe('shared-value')
        expect(kms.decryptCalls).toBe(1)
    })

    it('rejects a record with an unsupported envelope version', async () => {
        const cipher = cipherWith(fakeKms())
        const record = JSON.parse(await cipher.seal('v', 'provider:stripe'))
        record.v = 99
        await expect(cipher.open(JSON.stringify(record), 'provider:stripe')).rejects.toThrow(/envelope version/)
    })

    it('reports KMS outcomes through the metrics hook', async () => {
        const onKms = vi.fn()
        const kms = fakeKms()
        const cipher = new EnvelopeCipher({
            kms: kms.client,
            keyId: 'test-cmk',
            env: 'prod-us',
            rotationMs: 3_600_000,
            onKms,
        })
        await cipher.seal('v', 'provider:stripe')
        expect(onKms).toHaveBeenCalledWith('generate_data_key', 'ok')
    })
})
