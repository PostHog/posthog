// Envelope encryption of one integration's secret blob.
//
// enc_version 1:
//   plaintext  = canonical JSON of the secret blob (sorted keys, no whitespace), UTF-8
//   cipher     = AES-256-GCM under a fresh 32-byte data key per write
//   nonce      = 12 random bytes
//   AAD        = canonical JSON of {"integration_id","kind","owner_id"}, UTF-8
//   ciphertext = GCM output followed by the 16-byte tag
// The data key is wrapped by the KMS with the same three fields as its encryption context.

import { createCipheriv, createDecipheriv, randomBytes } from 'node:crypto'

import { type JsonObject, canonicalJson, contextAad } from './canonical'
import { DataKeyCache } from './data-key-cache'
import { type KmsOperation, dekCacheHitsTotal, kmsCallsTotal } from './metrics'
import { type EncryptionContext, EnvelopeError, type Kms, KmsError, type WrappedDataKey } from './types'

export const ENC_VERSION = 1

const KEY_BYTES = 32
const NONCE_BYTES = 12
const TAG_BYTES = 16

/** One row of `integration_secrets`, less the row id. */
export interface SealedSecret {
    keyId: string
    wrappedKey: Buffer
    ciphertext: Buffer
    nonce: Buffer
    encVersion: number
}

function isPlainObject(value: unknown): value is JsonObject {
    return typeof value === 'object' && value !== null && Object.getPrototypeOf(value) === Object.prototype
}

export class Envelope {
    constructor(
        private readonly kms: Kms,
        private readonly cache: DataKeyCache = new DataKeyCache()
    ) {}

    async seal(secret: JsonObject, context: EncryptionContext): Promise<SealedSecret> {
        if (!isPlainObject(secret)) {
            throw new TypeError('the secret blob must be a JSON object')
        }
        // Encode first, so a bad blob or context fails before it costs a KMS call.
        const plaintext = Buffer.from(canonicalJson(secret), 'utf8')
        const aad = contextAad(context)

        const dataKey = await this.callKms('generate_data_key', () => this.kms.generateDataKey(context))
        if (dataKey.plaintextKey.length !== KEY_BYTES) {
            dataKey.plaintextKey.fill(0)
            throw new KmsError('rejected', 'KMS returned a data key of the wrong length')
        }

        const nonce = randomBytes(NONCE_BYTES)
        const cipher = createCipheriv('aes-256-gcm', dataKey.plaintextKey, nonce, { authTagLength: TAG_BYTES })
        cipher.setAAD(aad)
        const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final(), cipher.getAuthTag()])
        plaintext.fill(0)

        // A row is often read soon after it is written, so keep its data key.
        this.cache.set(dataKey.wrappedKey, dataKey.plaintextKey)
        return { keyId: dataKey.keyId, wrappedKey: dataKey.wrappedKey, ciphertext, nonce, encVersion: ENC_VERSION }
    }

    async open(sealed: SealedSecret, context: EncryptionContext): Promise<JsonObject> {
        if (sealed.encVersion !== ENC_VERSION) {
            throw new EnvelopeError('unsupported_version', `unsupported enc_version ${sealed.encVersion}`)
        }
        if (sealed.nonce.length !== NONCE_BYTES || sealed.ciphertext.length < TAG_BYTES) {
            throw new EnvelopeError('malformed', 'sealed secret has a malformed nonce or ciphertext')
        }
        const aad = contextAad(context)

        // A cached key must be used before the next await (see DataKeyCache).
        const cached = this.cache.get(sealed.wrappedKey)
        if (cached) {
            dekCacheHitsTotal.inc()
            // The cache is keyed by the wrapped key only. The AAD still binds the row, so a
            // ciphertext copied to another row fails here and not only in KMS.
            return decryptBlob(cached, sealed, aad)
        }

        const key = await this.callKms('decrypt', () => this.kms.decrypt(sealed.wrappedKey, context))
        try {
            const secret = decryptBlob(key, sealed, aad)
            this.cache.set(sealed.wrappedKey, key)
            return secret
        } catch (err) {
            key.fill(0)
            throw err
        }
    }

    /**
     * Wraps the data key of a sealed secret under `targetKeyId`. The ciphertext and nonce do not
     * change. The cache entry for the old wrapped key expires on its own.
     */
    rewrap(wrappedKey: Buffer, context: EncryptionContext, targetKeyId: string): Promise<WrappedDataKey> {
        return this.callKms('rewrap', () => this.kms.rewrap(wrappedKey, context, targetKeyId))
    }

    private async callKms<T>(op: KmsOperation, call: () => Promise<T>): Promise<T> {
        try {
            const result = await call()
            kmsCallsTotal.labels({ op, outcome: 'ok' }).inc()
            return result
        } catch (err) {
            kmsCallsTotal.labels({ op, outcome: err instanceof KmsError ? err.reason : 'unavailable' }).inc()
            throw err
        }
    }
}

function decryptBlob(key: Buffer, sealed: SealedSecret, aad: Buffer): JsonObject {
    const body = sealed.ciphertext.subarray(0, sealed.ciphertext.length - TAG_BYTES)
    const tag = sealed.ciphertext.subarray(sealed.ciphertext.length - TAG_BYTES)
    const decipher = createDecipheriv('aes-256-gcm', key, sealed.nonce, { authTagLength: TAG_BYTES })
    decipher.setAAD(aad)
    decipher.setAuthTag(tag)

    let plaintext: Buffer
    try {
        plaintext = Buffer.concat([decipher.update(body), decipher.final()])
    } catch {
        // GCM gives no reason. The usual causes are another row's context or a changed byte.
        throw new EnvelopeError('decrypt_failed', 'secret ciphertext does not match its key or encryption context')
    }
    try {
        const secret: unknown = JSON.parse(plaintext.toString('utf8'))
        if (!isPlainObject(secret)) {
            throw new EnvelopeError('malformed', 'decrypted secret is not a JSON object')
        }
        return secret
    } catch (err) {
        if (err instanceof EnvelopeError) {
            throw err
        }
        throw new EnvelopeError('malformed', 'decrypted secret is not valid JSON')
    } finally {
        plaintext.fill(0)
    }
}
