/**
 * Decrypts fields written by Django's `EncryptedTextField` /
 * `EncryptedJSONStringField`. Ported from v1's
 * `services/agent-core/src/encryption/index.ts` — same key schedule and
 * compatible wire format.
 *
 * `ENCRYPTION_SALT_KEYS` is a comma-separated list of UTF-8 keys. Each is
 * base64-encoded into a Fernet key. On decrypt we try each in order so a
 * key rotation can ship without flushing in-flight encrypted rows: put the
 * new key first, leave the previous key behind it until rewrites complete.
 *
 * Used by the runner to decrypt `AgentApplication.encrypted_env` before
 * resolving secrets into `SecretBroker` for tool dispatch.
 */

import { Fernet } from 'fernet-nodejs'

export class EncryptedFields {
    private readonly fernets: Fernet[]

    constructor(encryptionSaltKeys: string) {
        const keys = encryptionSaltKeys.split(',').filter((k) => k.length > 0)
        this.fernets = keys.map((k) => new Fernet(Buffer.from(k, 'utf-8').toString('base64')))
    }

    /** True when at least one key is configured — guards against an env-misconfig. */
    get isConfigured(): boolean {
        return this.fernets.length > 0
    }

    encrypt(value: string): string {
        if (this.fernets.length === 0) {
            throw new Error('EncryptedFields: no keys configured (set ENCRYPTION_SALT_KEYS)')
        }
        return this.fernets[0].encrypt(value)
    }

    /**
     * Try each key in turn. If `ignoreDecryptionErrors` is set, returns the
     * raw input unchanged when no key works (used by lenient call sites that
     * need to tolerate plaintext-bypass for migration). Otherwise throws.
     */
    decrypt(value: string, options?: { ignoreDecryptionErrors?: boolean }): string {
        if (this.fernets.length === 0) {
            throw new Error('EncryptedFields: no keys configured (set ENCRYPTION_SALT_KEYS)')
        }
        let lastErr: Error | undefined
        for (const f of this.fernets) {
            try {
                return f.decrypt(value)
            } catch (err) {
                lastErr = err as Error
            }
        }
        if (options?.ignoreDecryptionErrors) {
            return value
        }
        throw lastErr ?? new Error('EncryptedFields: decryption failed')
    }

    /**
     * Decrypt a JSON-encoded env block (Django's `EncryptedJSONStringField`).
     * Returns `{}` for an empty / unset value so callers don't have to special-case.
     */
    decryptJsonEnv(value: string | null | undefined): Record<string, string> {
        if (!value) {
            return {}
        }
        const plain = this.decrypt(value)
        const parsed = JSON.parse(plain)
        if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
            throw new Error('EncryptedFields.decryptJsonEnv: decoded value is not a JSON object')
        }
        const out: Record<string, string> = {}
        for (const [k, v] of Object.entries(parsed)) {
            out[k] = String(v)
        }
        return out
    }

    /**
     * Decrypt a Django `EncryptedJSONField` value without forcing values to
     * strings. `EncryptedJSONField` stores the column as TEXT (per
     * `EncryptedFieldMixin.get_internal_type`) so the wire format is
     * identical to `EncryptedTextField`; only the Python-side type is
     * different. Returns `null` on empty input. Throws if the decoded value
     * isn't a JSON object.
     */
    decryptJson(value: string | null | undefined): Record<string, unknown> | null {
        if (!value) {
            return null
        }
        const plain = this.decrypt(value)
        const parsed = JSON.parse(plain)
        if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
            throw new Error('EncryptedFields.decryptJson: decoded value is not a JSON object')
        }
        return parsed as Record<string, unknown>
    }
}
