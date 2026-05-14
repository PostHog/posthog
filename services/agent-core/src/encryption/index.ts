import { Fernet } from 'fernet-nodejs'

/**
 * Decrypts fields written by Django's `EncryptedTextField` / `EncryptedJSONStringField`.
 *
 * Copied from nodejs/src/cdp/utils/encryption-utils.ts (per the cherry-pick-by-copy rule
 * in services/agent-core/README.md — we never import from nodejs/). Identical key
 * schedule: `ENCRYPTION_SALT_KEYS` is a comma-separated list of utf-8 keys, each
 * base64-encoded into a Fernet key. Decrypt tries each key in order — newer keys first
 * during rotation.
 */
export class EncryptedFields {
    private fernets: Fernet[] = []

    constructor(encryptionSaltKeys: string) {
        const saltKeys = encryptionSaltKeys.split(',').filter((key) => key)
        this.fernets = saltKeys.map((key) => new Fernet(Buffer.from(key, 'utf-8').toString('base64')))
    }

    encrypt(value: string): string {
        if (!this.fernets.length) {
            throw new Error('Encryption keys are not set')
        }
        return this.fernets[0].encrypt(value)
    }

    decrypt(value: string, options?: { ignoreDecryptionErrors: boolean }): string | undefined {
        if (!this.fernets.length) {
            throw new Error('Encryption keys are not set')
        }
        let error: Error | undefined
        for (const fernet of this.fernets) {
            try {
                return fernet.decrypt(value)
            } catch (e) {
                error = e as Error
            }
        }

        if (options?.ignoreDecryptionErrors) {
            return value
        }

        throw error
    }
}
