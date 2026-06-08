/**
 * Per-agent Slack secret resolution out of `AgentApplication.encrypted_env`.
 *
 * The Slack signing secret and bot token both live in `encrypted_env` —
 * authored once, freeze-gate enforces presence, decrypted at request time
 * with the same `EncryptedFields` helper used everywhere else. Both ingress
 * (signing secret verify, ack reactions) and runner (failure notifier, future
 * trigger-driven reply machinery) need this lookup.
 *
 * Interface is named for its origin use case (signing secret) but resolves
 * any key in `encrypted_env` — the name predates the bot-token use. Callers
 * pass the conventional `SLACK_SIGNING_SECRET_KEY` or `SLACK_BOT_TOKEN_KEY`.
 */

import { AgentApplication } from '../spec/spec'
import { EncryptedFields } from './encryption'

export interface SlackSigningSecretResolver {
    /** Resolve a named entry from the application's `encrypted_env`. Returns null on
     *  missing env, decrypt failure, or absent / empty value. Never throws. */
    resolve(secretKey: string, application: AgentApplication): Promise<string | null>
}

/**
 * Production / harness impl. Decrypts the application's `encrypted_env` and
 * plucks the named entry. Identical shape used by ingress and runner; lifted
 * here so both wire the same resolver rather than reimplementing the lookup.
 */
export class EncryptedEnvSlackSecretResolver implements SlackSigningSecretResolver {
    constructor(private readonly encryption: EncryptedFields) {}

    async resolve(secretKey: string, application: AgentApplication): Promise<string | null> {
        if (!application.encrypted_env) {
            return null
        }
        try {
            const env = this.encryption.decryptJsonEnv(application.encrypted_env)
            const value = env[secretKey]
            return typeof value === 'string' && value.length > 0 ? value : null
        } catch {
            return null
        }
    }
}
