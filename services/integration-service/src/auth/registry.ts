// The client registry: caller name -> signing keys + allowed providers.
//
// Lives in Secrets Manager (`<prefix>_clients`) rather than in code, so onboarding a
// caller or rotating its signing key is a secrets change with no service deploy. That
// matters because the alternative — a deploy per key rotation — is exactly the friction
// that makes people not rotate.
//
// Held in process memory only, never written to Redis. Everything else this service
// caches is a credential sealed under KMS; these are the keys that authenticate
// callers, and there is no working set argument for putting them anywhere but here.

import { GetSecretValueCommand, type SecretsManagerClient } from '@aws-sdk/client-secrets-manager'

import { logger } from '../lib/logging.js'
import { PROVIDERS } from '../providers.js'
import type { ClientRegistry, ClientRegistryEntry } from './types.js'

function parseRegistry(raw: string): ClientRegistry {
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('client registry is not a JSON object')
    }

    const registry: ClientRegistry = {}
    for (const [caller, value] of Object.entries(parsed as Record<string, unknown>)) {
        if (typeof value !== 'object' || value === null || Array.isArray(value)) {
            throw new Error(`client registry entry for ${caller} is not an object`)
        }
        const entry = value as Partial<ClientRegistryEntry>
        const keys = Array.isArray(entry.keys) ? entry.keys.filter((k) => typeof k === 'string' && k.length > 0) : []
        const providers = Array.isArray(entry.providers)
            ? entry.providers.filter((p) => typeof p === 'string' && p.length > 0)
            : []

        if (keys.length === 0) {
            throw new Error(`client registry entry for ${caller} has no signing keys`)
        }

        // A provider that does not exist in the manifest is almost certainly a typo, and
        // a typo'd allowlist silently grants nothing — which looks like a broken caller
        // at 3am. Fail the parse instead, so it surfaces at load.
        const unknown = providers.filter((p) => !(p in PROVIDERS))
        if (unknown.length > 0) {
            throw new Error(`client registry entry for ${caller} allows unknown provider(s): ${unknown.join(', ')}`)
        }

        registry[caller] = { keys, providers }
    }
    return registry
}

export class ClientRegistryLoader {
    private registry: ClientRegistry = {}
    private loaded = false

    constructor(
        private readonly client: SecretsManagerClient,
        private readonly secretId: string
    ) {}

    /** Replace the in-memory registry. Throws on the first load so boot fails closed. */
    async load(): Promise<void> {
        const response = await this.client.send(new GetSecretValueCommand({ SecretId: this.secretId }))
        if (!response.SecretString) {
            throw new Error(`client registry ${this.secretId} has no value`)
        }
        this.registry = parseRegistry(response.SecretString)
        this.loaded = true
        logger.info('auth:registry_loaded', { callers: Object.keys(this.registry).length })
    }

    /**
     * Reload, keeping the previous registry if the new one is unreadable. A malformed
     * edit must not lock every caller out of a running fleet; it should page instead.
     */
    async reload(): Promise<void> {
        try {
            await this.load()
        } catch (err) {
            logger.error('auth:registry_reload_failed', {
                error: err instanceof Error ? err.message : String(err),
            })
        }
    }

    get isLoaded(): boolean {
        return this.loaded
    }

    entryFor(caller: string): ClientRegistryEntry | null {
        return this.registry[caller] ?? null
    }
}
