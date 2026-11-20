/**
 * The row a secret belongs to. It is the KMS encryption context of the data key and the AES-GCM
 * AAD of the secret, so a ciphertext copied to another row, owner or kind fails to decrypt.
 */
export interface EncryptionContext {
    integrationId: string
    /** The team id for team-owned rows, in decimal. */
    ownerId: string
    kind: string
}

export interface WrappedDataKey {
    /** The data key encrypted under `keyId`. Safe to store. */
    wrappedKey: Buffer
    /** The KMS key that wrapped `wrappedKey`. For AWS this is the key ARN, never the alias. */
    keyId: string
}

export interface DataKey extends WrappedDataKey {
    /** 32 bytes. The caller owns it and zeroes it when it is no longer needed. */
    plaintextKey: Buffer
}

export interface Kms {
    readonly provider: 'aws' | 'local'
    generateDataKey(context: EncryptionContext): Promise<DataKey>
    decrypt(wrappedKey: Buffer, context: EncryptionContext): Promise<Buffer>
    /** Wraps the same data key under `targetKeyId`. The ciphertext of the secret does not change. */
    rewrap(wrappedKey: Buffer, context: EncryptionContext, targetKeyId: string): Promise<WrappedDataKey>
}

/**
 * `unavailable`: KMS did not answer (timeout, network, throttling), so a retry later can work.
 * `rejected`: KMS answered no (wrong context, unknown or disabled key, access denied).
 */
export type KmsFailure = 'unavailable' | 'rejected'

export class KmsError extends Error {
    constructor(
        readonly reason: KmsFailure,
        message: string
    ) {
        super(message)
        this.name = 'KmsError'
    }
}

export type EnvelopeFailure = 'unsupported_version' | 'malformed' | 'decrypt_failed'

export class EnvelopeError extends Error {
    constructor(
        readonly reason: EnvelopeFailure,
        message: string
    ) {
        super(message)
        this.name = 'EnvelopeError'
    }
}
