// AWS Secrets Manager implementation of SecretStore.
//
// Rotation rides AWS's own staging labels rather than a bespoke envelope format:
// PutSecretValue promotes the new version to AWSCURRENT and demotes the old one to
// AWSPREVIOUS automatically, and `secrets rollback` in PostHog/secrets already knows
// how to move them back. So "is this key mid-rotation" is answered by diffing the two
// versions field by field — which also means a provider whose client_id did not change
// reports only the field that did.

import { GetSecretValueCommand, ResourceNotFoundException, SecretsManagerClient } from '@aws-sdk/client-secrets-manager'

import { logger } from '../lib/logging.js'
import { PROVIDERS } from '../providers.js'
import type { ProviderSnapshot, ResolvedSecret } from '../types.js'
import { RECOVERY_FIELD, type SecretStore } from './types.js'

interface VersionPayload {
    fields: Record<string, string>
    /** Credential fields flagged as in recovery, from the reserved flat field. */
    inRecovery: ReadonlySet<string>
    versionId: string
    createdAt: string | null
}

function parsePayload(raw: string, versionId: string, createdAt: Date | undefined): VersionPayload {
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('secret payload is not a JSON object')
    }

    const fields: Record<string, string> = {}
    const inRecovery = new Set<string>()

    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
        // Non-string values would silently stringify to "[object Object]" downstream.
        // Skipping them makes the field read as `missing`, which is loud and correct.
        if (typeof value !== 'string') {
            continue
        }
        if (key === RECOVERY_FIELD) {
            for (const field of value.split(',').map((part) => part.trim())) {
                if (field) {
                    inRecovery.add(field)
                }
            }
            continue
        }
        fields[key] = value
    }

    return { fields, inRecovery, versionId, createdAt: createdAt ? createdAt.toISOString() : null }
}

export interface SecretsManagerStoreOptions {
    client: SecretsManagerClient
    /** Wraps the provider name into an AWS secret id, e.g. `integrations-stripe-secrets`. */
    secretIdFor: (provider: string) => string
}

export function createSecretsManagerStore(opts: SecretsManagerStoreOptions): SecretStore {
    const { client, secretIdFor } = opts

    async function fetchVersion(secretId: string, stage: 'AWSCURRENT' | 'AWSPREVIOUS'): Promise<VersionPayload | null> {
        try {
            const response = await client.send(new GetSecretValueCommand({ SecretId: secretId, VersionStage: stage }))
            if (!response.SecretString) {
                return null
            }
            return parsePayload(response.SecretString, response.VersionId ?? '', response.CreatedDate)
        } catch (err) {
            // A secret with only ever one version has no AWSPREVIOUS stage. That is the
            // steady state, not a failure, so it must not fail the whole read.
            if (err instanceof ResourceNotFoundException) {
                return null
            }
            throw err
        }
    }

    return {
        async loadProvider(provider: string): Promise<ProviderSnapshot | null> {
            const definition = PROVIDERS[provider]
            if (!definition) {
                return null
            }
            const secretId = secretIdFor(provider)

            const current = await fetchVersion(secretId, 'AWSCURRENT')
            if (!current) {
                logger.warn('store:provider_missing', { provider, secretId })
                return null
            }
            const previous = await fetchVersion(secretId, 'AWSPREVIOUS')

            const fetchedAt = new Date().toISOString()
            const secrets: Record<string, ResolvedSecret> = {}

            // Only manifest keys are ever exposed. A field present in the secret but not
            // in the manifest is ignored rather than served, so adding a credential is a
            // reviewed code change and never just a secrets edit.
            for (const key of definition.keys) {
                const value = current.fields[key]
                if (value === undefined) {
                    continue
                }

                if (current.inRecovery.has(key)) {
                    secrets[key] = {
                        state: 'recovery',
                        versionId: current.versionId,
                        fetchedAt,
                    }
                    continue
                }

                const previousValue = previous?.fields[key]
                if (previousValue !== undefined && previousValue !== value) {
                    secrets[key] = {
                        state: 'rotating',
                        value,
                        previous: previousValue,
                        versionId: current.versionId,
                        fetchedAt,
                    }
                    continue
                }

                secrets[key] = { state: 'steady', value, versionId: current.versionId, fetchedAt }
            }

            return {
                provider,
                fetchedAt,
                versionId: current.versionId,
                currentActivatedAt: current.createdAt,
                secrets,
            }
        },
    }
}
