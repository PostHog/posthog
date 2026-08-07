// AWS Secrets Manager implementation of SecretStore.
//
// One secret holds every platform integration credential as flat `KEY: value` pairs, which
// is how every other PostHog service stores its configuration and what the
// PostHog/secrets CLI and UI can manage.
//
// Rotation state comes from an explicit `<KEY>_FALLBACKS` sibling rather than AWS staging
// labels — see the note on FALLBACK_SUFFIX for why the labels cannot work once everything
// shares one secret.

import { GetSecretValueCommand, ResourceNotFoundException, SecretsManagerClient } from '@aws-sdk/client-secrets-manager'

import { logger } from '../lib/logging.js'
import { PROVIDERS } from '../providers.js'
import type { ResolvedSecret, SecretsSnapshot } from '../types.js'
import { FALLBACK_SUFFIX, RECOVERY_KEYS, type SecretStore } from './types.js'

function commaList(value: string | undefined): string[] {
    if (!value) {
        return []
    }
    return value
        .split(',')
        .map((part) => part.trim())
        .filter(Boolean)
}

export interface SecretsManagerStoreOptions {
    client: SecretsManagerClient
    secretId: string
}

export function createSecretsManagerStore(opts: SecretsManagerStoreOptions): SecretStore {
    return {
        async load(): Promise<SecretsSnapshot | null> {
            let response
            try {
                response = await opts.client.send(new GetSecretValueCommand({ SecretId: opts.secretId }))
            } catch (err) {
                if (err instanceof ResourceNotFoundException) {
                    logger.warn('store:secret_missing', { secretId: opts.secretId })
                    return null
                }
                throw err
            }
            if (!response.SecretString) {
                logger.warn('store:secret_empty', { secretId: opts.secretId })
                return null
            }

            const parsed: unknown = JSON.parse(response.SecretString)
            if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
                throw new Error('secret payload is not a JSON object')
            }

            // Non-string values would stringify to "[object Object]" downstream. Dropping
            // them makes the field read as `missing`, which is loud and correct.
            const fields: Record<string, string> = {}
            for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
                if (typeof value === 'string') {
                    fields[key] = value
                }
            }

            const inRecovery = new Set(commaList(fields[RECOVERY_KEYS]))
            const fetchedAt = new Date().toISOString()
            const versionId = response.VersionId ?? ''
            const secrets: Record<string, ResolvedSecret> = {}

            // Only manifest keys are ever exposed. A field present in the secret but not in
            // the manifest is ignored rather than served, so adding a credential is a
            // reviewed code change and never just a secrets edit.
            for (const definition of Object.values(PROVIDERS)) {
                for (const key of definition.keys) {
                    const value = fields[key]
                    if (value === undefined) {
                        continue
                    }

                    if (inRecovery.has(key)) {
                        secrets[key] = { state: 'recovery', versionId, fetchedAt }
                        continue
                    }

                    const previous = commaList(fields[`${key}${FALLBACK_SUFFIX}`])[0]
                    if (previous !== undefined && previous !== value) {
                        secrets[key] = { state: 'rotating', value, previous, versionId, fetchedAt }
                        continue
                    }

                    secrets[key] = { state: 'steady', value, versionId, fetchedAt }
                }
            }

            return {
                fetchedAt,
                versionId,
                // "When did this secret last change", not "when did this field rotate". An
                // unrelated edit moves it forward, which only makes the retirement verdict
                // more conservative — the correct direction to be wrong in.
                versionCreatedAt: response.CreatedDate ? response.CreatedDate.toISOString() : null,
                secrets,
            }
        },
    }
}
