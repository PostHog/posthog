// The Kubernetes Secret's contents: parses them and holds the secrets they carry.
//
// The values come from a secret source (see source.ts). For the directory source, kubelet
// projects the secret as a directory, one file per key, and rewrites it in place when the
// content changes, swapping the `..data` symlink atomically. So a rotation reaches the pod
// without a restart and a read never sees a half-written set.

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

/**
 * OAuth client secrets and minter keys (for example a GitHub App private key). Reserved, so
 * `/v1/secrets/resolve` never serves one to any caller. Only the in-process provider code reads
 * them.
 */
export const PROVIDER_PREFIX = `${RESERVED_PREFIX}PROVIDER_`

/** Comma-separated names of the secrets that are in recovery. */
export const RECOVERY_KEYS = 'CREDENTIALS_RECOVERY_KEYS'

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

/**
 * Every file on the mount, by name. Kubelet's own dot-prefixed bookkeeping is skipped.
 * Null when the directory or any one entry cannot be read.
 */
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
            // A partial snapshot would drop every entry that failed, such as an allowlist,
            // which would leave its deployment unrestricted.
            return null
        }
    }

    return values
}

export interface SecretMountOptions {
    /** Directory `reload()` reads. Absent when a secret source calls `apply()` instead. */
    dir?: string
    now?: () => number
}

/**
 * Holds the last successfully parsed secret set. A reload that fails keeps serving what
 * is already held, so a mount blip does not take a warm pod out of rotation; the staleness
 * gauge is what makes that visible.
 */
export class SecretMount {
    private held: MountedSecrets | null = null
    // The values `held` was built from, so `withdraw()` can take names away from them.
    private heldValues: Record<string, string> | null = null

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
        if (this.opts.dir === undefined) {
            throw new Error('SecretMount.reload() needs a directory')
        }
        this.apply(await readMount(this.opts.dir))
    }

    /**
     * Replace the held set with one parsed from `values`, the whole secret at one version.
     * Null means the source could not be read, which keeps what is held.
     */
    apply(values: Record<string, string> | null): void {
        const now = this.opts.now ?? Date.now
        const next = values ? this.build(values) : null
        if (values && next) {
            this.held = next
            this.heldValues = values
            servingStaleSeconds.set(0)
        } else {
            mountErrorsTotal.inc()
            if (this.held) {
                servingStaleSeconds.set((now() - Date.parse(this.held.fetchedAt)) / 1000)
            }
        }
    }

    /**
     * Apply only what `values` takes away. A name it no longer carries stops being served, and a
     * name it adds to the recovery list is served as recovery. Every value it adds or changes stays
     * out, for a snapshot whose signing keys the service refused: the keys still held could read it.
     */
    withdraw(values: Record<string, string> | null): void {
        const held = this.heldValues
        if (values === null || held === null) {
            this.apply(null)
            return
        }
        const kept: Record<string, string> = {}
        for (const [name, value] of Object.entries(held)) {
            if (Object.prototype.hasOwnProperty.call(values, name)) {
                kept[name] = value
            }
        }
        const recovery = new Set([...commaList(held[RECOVERY_KEYS]), ...commaList(values[RECOVERY_KEYS])])
        if (recovery.size > 0) {
            kept[RECOVERY_KEYS] = [...recovery].join(',')
        }
        this.apply(kept)
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
            logger.warn('mount:no_secrets', { dir: this.opts.dir ?? null })
            return null
        }

        return { fetchedAt, versionId: contentHash, secrets }
    }
}
