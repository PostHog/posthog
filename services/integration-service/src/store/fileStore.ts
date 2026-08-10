// Reads the credentials out of a mounted Kubernetes Secret.
//
// External Secrets Operator syncs the AWS secret into a Kubernetes Secret, and kubelet
// mounts it as a directory: one file per key, the file contents being the value. ESO is
// already how every PostHog deployment receives its secrets, so this service stops being
// the exception that calls Secrets Manager at runtime.
//
// Kubelet rewrites the mount in place when the content changes, so a rotation reaches the
// pod without a restart. It swaps the `..data` symlink atomically, which means a read
// never sees a half-written set.
//
// What this replaces is worth recording: the service previously read Secrets Manager over
// the API and cached the result in Redis under a KMS-wrapped data key. The envelope
// encryption existed only to keep plaintext out of Redis. With the values arriving on a
// tmpfs mount instead, Redis holds no credentials and the crypto has no job.

import { createHash } from 'node:crypto'
import { readFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'

import { logger } from '../lib/logging.js'
import { PROVIDERS } from '../providers.js'
import type { ResolvedSecret, SecretsSnapshot } from '../types.js'
import { FALLBACK_SUFFIX, RECOVERY_KEYS, type SecretStore } from './types.js'

/** Kubelet's own bookkeeping inside a projected secret volume. Never a credential. */
const IGNORED_ENTRIES = new Set(['..data'])

function commaList(value: string | undefined): string[] {
    if (!value) {
        return []
    }
    return value
        .split(',')
        .map((part) => part.trim())
        .filter(Boolean)
}

export interface FileStoreOptions {
    /** Directory the Kubernetes Secret is mounted at. */
    dir: string
    /**
     * Records when a content hash was first seen and returns that timestamp. Persisted, so
     * every replica agrees and the answer survives a restart — see the note on
     * SecretsSnapshot.changedAt.
     */
    observeVersion: (contentHash: string) => Promise<string | null>
}

export function createFileStore(opts: FileStoreOptions): SecretStore {
    return {
        async load(): Promise<SecretsSnapshot | null> {
            let entries: string[]
            try {
                entries = await readdir(opts.dir)
            } catch (err) {
                logger.error('store:mount_unreadable', {
                    dir: opts.dir,
                    error: err instanceof Error ? err.message : String(err),
                })
                return null
            }

            const values: Record<string, string> = {}
            for (const entry of entries) {
                if (IGNORED_ENTRIES.has(entry) || entry.startsWith('..')) {
                    continue
                }
                try {
                    // Trailing newlines are easy to introduce by hand and would silently
                    // break an API call, so trim rather than trust the file byte for byte.
                    values[entry] = (await readFile(join(opts.dir, entry), 'utf8')).trim()
                } catch (err) {
                    logger.warn('store:key_unreadable', {
                        key: entry,
                        error: err instanceof Error ? err.message : String(err),
                    })
                }
            }

            if (Object.keys(values).length === 0) {
                logger.warn('store:mount_empty', { dir: opts.dir })
                return null
            }

            // Hash the whole set, sorted, so the id is stable and identifies the content
            // rather than an AWS version we can no longer see from a mount.
            const contentHash = createHash('sha256')
                .update(
                    Object.keys(values)
                        .sort()
                        .map((key) => `${key}=${values[key]}`)
                        .join('\n')
                )
                .digest('hex')
                .slice(0, 16)

            const inRecovery = new Set(commaList(values[RECOVERY_KEYS]))
            const fetchedAt = new Date().toISOString()
            const secrets: Record<string, ResolvedSecret> = {}

            // Only manifest keys are ever exposed. A file present on the mount but not in
            // the manifest is ignored rather than served, so adding a credential is a
            // reviewed code change and never just a secrets edit. This is also what keeps
            // the caller signing keys sharing this secret from being served as credentials.
            for (const definition of Object.values(PROVIDERS)) {
                for (const key of definition.keys) {
                    const value = values[key]
                    if (value === undefined) {
                        continue
                    }
                    if (inRecovery.has(key)) {
                        secrets[key] = { state: 'recovery', versionId: contentHash, fetchedAt }
                        continue
                    }
                    const previous = commaList(values[`${key}${FALLBACK_SUFFIX}`])[0]
                    if (previous !== undefined && previous !== value) {
                        secrets[key] = { state: 'rotating', value, previous, versionId: contentHash, fetchedAt }
                        continue
                    }
                    secrets[key] = { state: 'steady', value, versionId: contentHash, fetchedAt }
                }
            }

            return {
                fetchedAt,
                versionId: contentHash,
                changedAt: await opts.observeVersion(contentHash),
                secrets,
            }
        },
    }
}

/** Every signing key on the mount, keyed by deployment. Read straight from the files. */
export async function readSigningKeys(dir: string, prefix: string): Promise<Record<string, string[]>> {
    const out: Record<string, string[]> = {}
    let entries: string[]
    try {
        entries = await readdir(dir)
    } catch {
        return out
    }
    for (const entry of entries) {
        if (!entry.startsWith(prefix)) {
            continue
        }
        const value = (await readFile(join(dir, entry), 'utf8')).trim()
        const keys = commaList(value)
        if (keys.length > 0) {
            out[entry.slice(prefix.length).toLowerCase().replaceAll('_', '-')] = keys
        }
    }
    return out
}
