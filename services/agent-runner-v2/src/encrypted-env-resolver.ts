/**
 * Default `resolveSecrets` impl for production: read the AgentApplication
 * row, decrypt `encrypted_env` (Django's `EncryptedJSONStringField`), return
 * a plaintext `Record<string, string>`. The runner hands that to
 * `SecretBroker.mintSessionMap()` which nonce-wraps the values for the
 * sandbox.
 *
 * Pass an `EncryptedFields` constructed from `ENCRYPTION_SALT_KEYS` (same
 * env var Django reads from). Missing / empty env → returns `{}` so an
 * agent without configured secrets just gets no nonces — no crash.
 */

import { AgentSession, createLogger, EncryptedFields, RevisionStore } from '@posthog/agent-shared-v2'

const log = createLogger('encrypted-env')

export function makeEncryptedEnvResolver(deps: {
    revisions: RevisionStore
    encryption: EncryptedFields
}): (session: AgentSession) => Promise<Record<string, string>> {
    return async (session) => {
        const app = await deps.revisions.getApplication(session.application_id)
        if (!app?.encrypted_env) {
            return {}
        }
        try {
            return deps.encryption.decryptJsonEnv(app.encrypted_env)
        } catch (err) {
            // Don't crash the session — log and continue with empty secrets.
            // The agent will see undefined values and can react accordingly.
            log.error(
                { err: (err as Error).message, session_id: session.id, application_id: session.application_id },
                'encrypted_env.decrypt_failed'
            )
            return {}
        }
    }
}
