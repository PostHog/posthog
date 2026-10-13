// The mounted Kubernetes Secret: reads it and holds the secrets it carries.
//
// Kubelet projects the secret as a directory, one file per key, and rewrites it in place
// when the content changes, swapping the `..data` symlink atomically. So a rotation reaches
// the pod without a restart and a read never sees a half-written set.

import { createHash } from 'node:crypto'
import { readFile, readdir, readlink } from 'node:fs/promises'
import { join } from 'node:path'

import { logger } from './lib/logging'
import { mountErrorsTotal, servingStaleSeconds } from './metrics'
import type { Secret, MountedSecrets } from './types'

/**
 * Marks an entry that is never served as a secret, whatever a token asks for. Secret
 * names are the third party's own environment-variable names, so a double underscore cannot
 * collide with one.
 */
export const RESERVED_PREFIX = '__'

/** Comma-separated names of the secrets that are in recovery. */
export const RECOVERY_KEYS = 'INTEGRATION_RECOVERY_KEYS'

/** Suffix holding the staged (incoming) value during a rotation, comma-separated, newest first. */
export const FALLBACK_SUFFIX = '_FALLBACKS'

function commaList(value: string | undefined): string[] {
    if (!value) {
        return []
    }
    return value
        .split(',')
        .map((part) => part.trim())
        .filter(Boolean)
}

/** Every file on the mount, by name. Kubelet's own dot-prefixed bookkeeping is skipped. */
export async function readMount(dir: string): Promise<Record<string, string> | null> {
    // Kubelet swaps `..data` atomically between versions. Reading through the resolved
    // target pins one version for the whole loop, so a swap mid-read cannot hand back a
    // mix of old and new entries.
    let root = dir
    try {
        root = join(dir, await readlink(join(dir, '..data')))
    } catch {
        // Not a kubelet projection (tests, local dev): read the directory as-is.
    }

    let entries: string[]
    try {
        entries = await readdir(root)
    } catch (err) {
        logger.error('mount:unreadable', { dir, error: err instanceof Error ? err.message : String(err) })
        return null
    }

    const values: Record<string, string> = {}
    for (const entry of entries.filter((name) => !name.startsWith('.'))) {
        try {
            // Trailing newlines are easy to introduce by hand and would silently break an
            // API call, so trim rather than trust the file byte for byte.
            values[entry] = (await readFile(join(root, entry), 'utf8')).trim()
        } catch (err) {
            logger.warn('mount:entry_unreadable', {
                key: entry,
                error: err instanceof Error ? err.message : String(err),
            })
        }
    }

    return values
}

export interface SecretMountOptions {
    /** Directory the Kubernetes Secret is mounted at. */
    dir: string
    now?: () => number
}

/**
 * Holds the last successfully parsed secret set. A reload that fails keeps serving what
 * is already held, so a mount blip does not take a warm pod out of rotation; the staleness
 * gauge is what makes that visible.
 */
export class SecretMount {
    private held: MountedSecrets | null = null

    constructor(private readonly opts: SecretMountOptions) {}

    /**
     * The secrets currently being served. Null until the first successful read, which is
     * what the server's readiness probe reports: a pod with no secrets must not serve,
     * because it would answer every resolve all-missing, which callers treat as terminal.
     */
    current(): MountedSecrets | null {
        return this.held
    }

    async reload(): Promise<void> {
        const now = this.opts.now ?? Date.now
        const values = await readMount(this.opts.dir)
        const next = values ? this.build(values) : null
        if (next) {
            this.held = next
            servingStaleSeconds.set(0)
        } else {
            mountErrorsTotal.inc()
            if (this.held) {
                servingStaleSeconds.set((now() - Date.parse(this.held.fetchedAt)) / 1000)
            }
        }
    }

    private build(values: Record<string, string>): MountedSecrets | null {
        // Sorted so the same content always hashes to the same version id.
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
        const secrets: Record<string, Secret> = {}

        for (const [key, value] of Object.entries(values)) {
            // Signing keys, the recovery list and rotation siblings are the mount's own
            // machinery. A sibling IS served, but as the `incoming` field of the key it belongs
            // to — never as a secret in its own right, which would hand out a staged value under
            // a name nobody asked for, alongside the list of burned keys.
            if (key.startsWith(RESERVED_PREFIX) || key === RECOVERY_KEYS || key.endsWith(FALLBACK_SUFFIX)) {
                continue
            }
            if (inRecovery.has(key)) {
                secrets[key] = { state: 'recovery', versionId: contentHash, fetchedAt }
                continue
            }
            const incoming = commaList(values[`${key}${FALLBACK_SUFFIX}`])[0]
            if (incoming !== undefined && incoming !== value) {
                secrets[key] = { state: 'rotating', value, incoming, versionId: contentHash, fetchedAt }
                continue
            }
            secrets[key] = { state: 'steady', value, versionId: contentHash, fetchedAt }
        }

        if (Object.keys(secrets).length === 0) {
            // Counting files rather than secrets would call a mount holding nothing but
            // signing keys healthy, and every resolve would answer all-missing, which a
            // caller treats as a deleted secret.
            logger.warn('mount:no_secrets', { dir: this.opts.dir })
            return null
        }

        return { fetchedAt, versionId: contentHash, secrets }
    }
}
