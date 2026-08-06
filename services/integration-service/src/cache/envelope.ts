// Envelope encryption for anything this service writes to Redis.
//
// The point: raw read access to Redis must not be enough to read a credential. Values
// are sealed with AES-256-GCM under a data key that only ever exists in plaintext
// inside this process; the copy that travels with the ciphertext is wrapped by an AWS
// KMS CMK that only this service's IRSA role can decrypt. So an attacker who dumps
// Redis gets ciphertext, unwrapping requires a KMS permission they do not have, and
// every unwrap that does happen is a CloudTrail event.
//
// Two bindings stop a sealed value being moved somewhere it does not belong:
//   - the GCM AAD is `<env>|<cacheKey>`, so a ciphertext cannot be replayed under a
//     different secret name or lifted between regions;
//   - the KMS EncryptionContext pins the wrapped data key to this service and env, so
//     the unwrap itself fails if either is wrong.
//
// Data keys rotate on a timer. Records sealed under an older key stay readable: the
// wrapped key travels inside the record, and unwrapped keys are memoized by digest so
// a rotation costs one KMS call per replica, not one per read.

import { DecryptCommand, GenerateDataKeyCommand, type KMSClient } from '@aws-sdk/client-kms'
import { createCipheriv, createDecipheriv, createHash, randomBytes } from 'node:crypto'

const ALGORITHM = 'aes-256-gcm'
const NONCE_BYTES = 12
const TAG_BYTES = 16
const RECORD_VERSION = 1

/** Wire format of a sealed value. Field names are short because these are hot Redis reads. */
interface EnvelopeRecord {
    v: number
    /** KMS-wrapped data key, base64. */
    dek: string
    /** GCM nonce, base64. */
    n: string
    /** GCM auth tag, base64. */
    t: string
    /** Ciphertext, base64. */
    c: string
}

interface DataKey {
    plaintext: Buffer
    wrapped: Buffer
    /** sha256 of the wrapped key — the memo key for unwrapped data keys. */
    digest: string
}

export interface EnvelopeCipherOptions {
    kms: KMSClient
    keyId: string
    /** Logical environment (dev | prod-us | prod-eu). Bound into AAD and KMS context. */
    env: string
    /** How long a data key is used for sealing before a new one is generated. */
    rotationMs: number
    /** Injected in tests so key rotation is exercisable without a clock. */
    now?: () => number
    /** Metrics hook. Kept as a callback so this module stays free of the metrics registry. */
    onKms?: (op: 'generate_data_key' | 'decrypt', result: 'ok' | 'error') => void
}

export class EnvelopeCipher {
    private readonly kms: KMSClient
    private readonly keyId: string
    private readonly env: string
    private readonly rotationMs: number
    private readonly now: () => number
    private readonly onKms: (op: 'generate_data_key' | 'decrypt', result: 'ok' | 'error') => void

    private current: DataKey | null = null
    private currentGeneratedAt = 0
    private generating: Promise<DataKey> | null = null
    private readonly unwrapped = new Map<string, Buffer>()

    constructor(opts: EnvelopeCipherOptions) {
        this.kms = opts.kms
        this.keyId = opts.keyId
        this.env = opts.env
        this.rotationMs = opts.rotationMs
        this.now = opts.now ?? Date.now
        this.onKms = opts.onKms ?? ((): void => {})
    }

    private encryptionContext(): Record<string, string> {
        return { service: 'integration-service', env: this.env }
    }

    private aad(cacheKey: string): Buffer {
        return Buffer.from(`${this.env}|${cacheKey}`, 'utf8')
    }

    /** Generate a fresh data key, or reuse the current one while it is still in date. */
    private async dataKey(): Promise<DataKey> {
        if (this.current && this.now() - this.currentGeneratedAt < this.rotationMs) {
            return this.current
        }
        // Single-flight: a burst of writes just after expiry must not each call KMS.
        if (this.generating) {
            return this.generating
        }

        this.generating = (async (): Promise<DataKey> => {
            let response
            try {
                response = await this.kms.send(
                    new GenerateDataKeyCommand({
                        KeyId: this.keyId,
                        KeySpec: 'AES_256',
                        EncryptionContext: this.encryptionContext(),
                    })
                )
            } catch (err) {
                this.onKms('generate_data_key', 'error')
                throw err
            }
            this.onKms('generate_data_key', 'ok')
            if (!response.Plaintext || !response.CiphertextBlob) {
                throw new Error('KMS GenerateDataKey returned no key material')
            }
            const plaintext = Buffer.from(response.Plaintext)
            const wrapped = Buffer.from(response.CiphertextBlob)
            const key: DataKey = {
                plaintext,
                wrapped,
                digest: createHash('sha256').update(wrapped).digest('hex'),
            }
            this.current = key
            this.currentGeneratedAt = this.now()
            this.unwrapped.set(key.digest, plaintext)
            return key
        })()

        try {
            return await this.generating
        } finally {
            this.generating = null
        }
    }

    /** Unwrap a data key that arrived with a record, memoizing by digest. */
    private async unwrap(wrapped: Buffer): Promise<Buffer> {
        const digest = createHash('sha256').update(wrapped).digest('hex')
        const memo = this.unwrapped.get(digest)
        if (memo) {
            return memo
        }
        let response
        try {
            response = await this.kms.send(
                new DecryptCommand({
                    CiphertextBlob: wrapped,
                    KeyId: this.keyId,
                    EncryptionContext: this.encryptionContext(),
                })
            )
        } catch (err) {
            this.onKms('decrypt', 'error')
            throw err
        }
        this.onKms('decrypt', 'ok')
        if (!response.Plaintext) {
            throw new Error('KMS Decrypt returned no key material')
        }
        const plaintext = Buffer.from(response.Plaintext)
        this.unwrapped.set(digest, plaintext)
        return plaintext
    }

    async seal(plaintext: string, cacheKey: string): Promise<string> {
        const key = await this.dataKey()
        const nonce = randomBytes(NONCE_BYTES)
        const cipher = createCipheriv(ALGORITHM, key.plaintext, nonce, { authTagLength: TAG_BYTES })
        cipher.setAAD(this.aad(cacheKey))
        const ciphertext = Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final()])
        const record: EnvelopeRecord = {
            v: RECORD_VERSION,
            dek: key.wrapped.toString('base64'),
            n: nonce.toString('base64'),
            t: cipher.getAuthTag().toString('base64'),
            c: ciphertext.toString('base64'),
        }
        return JSON.stringify(record)
    }

    /**
     * Open a sealed value. Throws on any tampering, wrong cache key, or wrong
     * environment — callers treat a throw as a cache miss rather than an outage, so a
     * poisoned entry degrades to a Secrets Manager read instead of a failed request.
     */
    async open(sealed: string, cacheKey: string): Promise<string> {
        const record = JSON.parse(sealed) as EnvelopeRecord
        if (record.v !== RECORD_VERSION) {
            throw new Error(`unsupported envelope version ${record.v}`)
        }
        const key = await this.unwrap(Buffer.from(record.dek, 'base64'))
        const decipher = createDecipheriv(ALGORITHM, key, Buffer.from(record.n, 'base64'), {
            authTagLength: TAG_BYTES,
        })
        decipher.setAAD(this.aad(cacheKey))
        decipher.setAuthTag(Buffer.from(record.t, 'base64'))
        return Buffer.concat([decipher.update(Buffer.from(record.c, 'base64')), decipher.final()]).toString('utf8')
    }
}
