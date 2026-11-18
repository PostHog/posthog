// The integrations callers: one Ed25519 PUBLIC key per deployment, mounted as a directory with
// one `<deployment>.pub` PEM file per caller. Each caller holds its private key as a mounted
// file of its own. The service holds no private key, so a leak of this mount or of the
// credentials-service secret does not let anyone sign as a caller.
//
// This registry is separate from the platform-secrets `__CALLER_KEY_*` HS256 keys
// (registry.ts). A key from one never verifies a token for the other route.
//
// A file can hold more than one PEM block, newest first. The service accepts all of them, so a
// rotation adds the new key, moves the caller to it, then drops the old one.

import { type KeyObject, createPublicKey } from 'node:crypto'

import { logger } from '../lib/logging'
import { integrationKeyReloadFailuresTotal, integrationKeysLastLoadedTimestamp } from '../metrics'
import { readMount } from '../mount'

export const PUBLIC_KEY_SUFFIX = '.pub'

// A Kubernetes object name, the same shape as the `apps/<name>` deployments in charts.
const DEPLOYMENT_PATTERN = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/
const PEM_BLOCK = /-----BEGIN PUBLIC KEY-----[\s\S]+?-----END PUBLIC KEY-----/g

export type IntegrationPublicKeys = Record<string, KeyObject[]>

function hasOwn(record: object, key: string): boolean {
    return Object.prototype.hasOwnProperty.call(record, key)
}

function parseFile(name: string, contents: string): KeyObject[] {
    // A private key on the service would undo the reason for EdDSA. Refuse it, whatever the
    // file is called.
    if (contents.includes('PRIVATE KEY')) {
        throw new Error(`${name} holds a private key; mount only public keys`)
    }
    const blocks = contents.match(PEM_BLOCK) ?? []
    if (blocks.length === 0) {
        throw new Error(`${name} holds no PEM public key`)
    }
    return blocks.map((block) => {
        let key: KeyObject
        try {
            key = createPublicKey(block)
        } catch {
            throw new Error(`${name} holds a PEM block that is not a valid public key`)
        }
        if (key.asymmetricKeyType !== 'ed25519') {
            throw new Error(`${name} holds a ${String(key.asymmetricKeyType)} key; only Ed25519 is accepted`)
        }
        return key
    })
}

/**
 * Every public key in one snapshot of the directory, keyed by deployment. Throws on any file
 * that is not `<deployment>.pub` with Ed25519 public keys, and on one key listed for two
 * deployments, because the verifier stops at the first key that verifies and the two would
 * collapse into one identity.
 */
export function parseIntegrationPublicKeys(files: Record<string, string>): IntegrationPublicKeys {
    const keys: IntegrationPublicKeys = {}
    const owner = new Map<string, string>()
    for (const [name, contents] of Object.entries(files)) {
        if (!name.endsWith(PUBLIC_KEY_SUFFIX)) {
            throw new Error(`unexpected file ${name}; only <deployment>${PUBLIC_KEY_SUFFIX} files belong here`)
        }
        const deployment = name.slice(0, -PUBLIC_KEY_SUFFIX.length)
        if (!DEPLOYMENT_PATTERN.test(deployment)) {
            throw new Error(`${name} does not name a deployment`)
        }
        const parsed = parseFile(name, contents)
        for (const key of parsed) {
            const der = key.export({ type: 'spki', format: 'der' }).toString('base64')
            const existing = owner.get(der)
            if (existing !== undefined && existing !== deployment) {
                throw new Error(`a public key for ${deployment} is also listed for ${existing}`)
            }
            owner.set(der, deployment)
        }
        if (hasOwn(keys, deployment)) {
            throw new Error(`two files both name the deployment ${deployment}`)
        }
        keys[deployment] = parsed
    }
    return keys
}

export class IntegrationKeyLoader {
    private keys: IntegrationPublicKeys = {}
    private loaded = false

    /** @param dir The directory `load()` and `reload()` read. */
    constructor(private readonly dir: string) {}

    /** Replace the in-memory key set. Throws on the first load so boot fails closed. */
    async load(): Promise<void> {
        const files = await readMount(this.dir)
        if (files === null) {
            throw new Error(`could not read ${this.dir}`)
        }
        this.loadFrom(files)
    }

    /** As `load()`, from one snapshot of the directory. */
    loadFrom(files: Record<string, string>): void {
        const keys = parseIntegrationPublicKeys(files)
        if (Object.keys(keys).length === 0) {
            throw new Error(`no ${PUBLIC_KEY_SUFFIX} files in ${this.dir}`)
        }
        this.keys = keys
        this.loaded = true
        integrationKeysLastLoadedTimestamp.set(Date.now() / 1000)
        logger.info('auth:integration_keys_loaded', { deployments: Object.keys(keys).sort() })
    }

    /**
     * Reload, keeping the previous keys if the directory is unreadable or invalid, so a
     * malformed edit cannot lock a running fleet out. The metrics make that visible when a
     * revocation does not land.
     */
    async reload(): Promise<void> {
        try {
            await this.load()
        } catch (err) {
            integrationKeyReloadFailuresTotal.inc()
            logger.error('auth:integration_keys_reload_failed', {
                error: err instanceof Error ? err.message : String(err),
            })
        }
    }

    get isLoaded(): boolean {
        return this.loaded
    }

    /** Every deployment and its accepted public keys, for the verifier to try in turn. */
    entries(): [string, KeyObject[]][] {
        return Object.entries(this.keys)
    }
}
