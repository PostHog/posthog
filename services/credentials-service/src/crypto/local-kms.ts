// A KMS stand-in for dev, CI and hobby. It wraps data keys with AES-256-GCM under keys from
// config, and binds the same encryption context as AWS KMS through the AAD. The envelope
// above it does not change, so a row written here has the same columns as a row written
// with AWS KMS.
//
// Wrapped key layout, version 1:
//   0x01 | key fingerprint (8) | nonce (12) | encrypted data key (32) | GCM tag (16)

import { createCipheriv, createDecipheriv, createHash, randomBytes } from 'node:crypto'

import { contextAad } from './canonical'
import { type DataKey, type EncryptionContext, type Kms, KmsError, type WrappedDataKey } from './types'

const WRAP_VERSION = 0x01
const FINGERPRINT_BYTES = 8
const NONCE_BYTES = 12
const KEY_BYTES = 32
const TAG_BYTES = 16
const WRAPPED_BYTES = 1 + FINGERPRINT_BYTES + NONCE_BYTES + KEY_BYTES + TAG_BYTES
const KEY_ID_PREFIX = 'local:'

function fingerprint(key: Buffer): Buffer {
    return createHash('sha256').update(key).digest().subarray(0, FINGERPRINT_BYTES)
}

export class LocalKms implements Kms {
    readonly provider = 'local'

    /** Wrapping keys by `local:<fingerprint hex>`. */
    private readonly keys = new Map<string, Buffer>()
    private readonly currentKeyId: string

    /** `keys[0]` wraps new data keys. Every key unwraps. */
    constructor(keys: readonly Buffer[]) {
        if (keys.length === 0) {
            throw new Error('LocalKms needs at least one key')
        }
        for (const key of keys) {
            if (key.length !== KEY_BYTES) {
                throw new Error(`LocalKms keys must be ${KEY_BYTES} bytes`)
            }
            this.keys.set(LocalKms.keyIdFor(key), Buffer.from(key))
        }
        this.currentKeyId = LocalKms.keyIdFor(keys[0] as Buffer)
    }

    /** The key id of a local wrapping key. It names the key without exposing it. */
    static keyIdFor(key: Buffer): string {
        return `${KEY_ID_PREFIX}${fingerprint(key).toString('hex')}`
    }

    // Async so that a throw rejects the promise, as an AWS KMS failure does.
    async generateDataKey(context: EncryptionContext): Promise<DataKey> {
        const plaintextKey = randomBytes(KEY_BYTES)
        const wrappedKey = this.wrap(plaintextKey, context, this.currentKeyId)
        return { plaintextKey, wrappedKey, keyId: this.currentKeyId }
    }

    async decrypt(wrappedKey: Buffer, context: EncryptionContext): Promise<Buffer> {
        return this.unwrap(wrappedKey, context)
    }

    async rewrap(wrappedKey: Buffer, context: EncryptionContext, targetKeyId: string): Promise<WrappedDataKey> {
        const plaintextKey = this.unwrap(wrappedKey, context)
        try {
            return { wrappedKey: this.wrap(plaintextKey, context, targetKeyId), keyId: targetKeyId }
        } finally {
            plaintextKey.fill(0)
        }
    }

    private wrap(plaintextKey: Buffer, context: EncryptionContext, keyId: string): Buffer {
        const key = this.keys.get(keyId)
        if (!key) {
            throw new KmsError('rejected', `unknown local key ${keyId}`)
        }
        const nonce = randomBytes(NONCE_BYTES)
        const cipher = createCipheriv('aes-256-gcm', key, nonce)
        cipher.setAAD(contextAad(context))
        const encrypted = Buffer.concat([cipher.update(plaintextKey), cipher.final()])
        return Buffer.concat([
            Buffer.from([WRAP_VERSION]),
            Buffer.from(keyId.slice(KEY_ID_PREFIX.length), 'hex'),
            nonce,
            encrypted,
            cipher.getAuthTag(),
        ])
    }

    private unwrap(wrappedKey: Buffer, context: EncryptionContext): Buffer {
        if (wrappedKey.length !== WRAPPED_BYTES || wrappedKey[0] !== WRAP_VERSION) {
            throw new KmsError('rejected', 'malformed local wrapped key')
        }
        let offset = 1
        const keyFingerprint = wrappedKey.subarray(offset, (offset += FINGERPRINT_BYTES))
        const nonce = wrappedKey.subarray(offset, (offset += NONCE_BYTES))
        const encrypted = wrappedKey.subarray(offset, (offset += KEY_BYTES))
        const tag = wrappedKey.subarray(offset)

        const keyId = `${KEY_ID_PREFIX}${keyFingerprint.toString('hex')}`
        const key = this.keys.get(keyId)
        if (!key) {
            throw new KmsError('rejected', `unknown local key ${keyId}`)
        }
        const decipher = createDecipheriv('aes-256-gcm', key, nonce, { authTagLength: TAG_BYTES })
        decipher.setAAD(contextAad(context))
        decipher.setAuthTag(tag)
        try {
            return Buffer.concat([decipher.update(encrypted), decipher.final()])
        } catch {
            throw new KmsError('rejected', 'local wrapped key does not match the encryption context')
        }
    }
}
