// The mounted Kubernetes Secret: reads it, holds the credentials it carries, and drives
// readiness from whether this pod holds any.
//
// Kubelet projects the secret as a directory, one file per key, and rewrites it in place
// when the content changes, swapping the `..data` symlink atomically. So a rotation reaches
// the pod without a restart and a read never sees a half-written set.

import { createHash } from 'node:crypto'
import { readFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'

import { logger } from './lib/logging'
import { mountErrorsTotal, servingStaleSeconds } from './metrics'
import type { Credential, Lifecycle, MountedCredentials } from './types'

/**
 * Marks an entry that is never served as a credential, whatever a token asks for. Credential
 * names are the third party's own environment-variable names, so a double underscore cannot
 * collide with one.
 */
export const RESERVED_PREFIX = '__'

/** Comma-separated names of the credentials that are in recovery. */
export const RECOVERY_KEYS = 'INTEGRATION_RECOVERY_KEYS'

/**
 * Suffix holding the outgoing value during a rotation, comma-separated, newest first.
 *
 * A sibling key rather than an AWS staging label: `AWSPREVIOUS` applies to a whole secret
 * version, so with everything in one secret an unrelated edit would silently end an
 * in-flight rotation's overlap.
 */
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
    let entries: string[]
    try {
        entries = await readdir(dir)
    } catch (err) {
        logger.error('mount:unreadable', { dir, error: err instanceof Error ? err.message : String(err) })
        return null
    }

    const values: Record<string, string> = {}
    for (const entry of entries) {
        if (entry.startsWith('.')) {
            continue
        }
        try {
            // Trailing newlines are easy to introduce by hand and would silently break an
            // API call, so trim rather than trust the file byte for byte.
            values[entry] = (await readFile(join(dir, entry), 'utf8')).trim()
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
    lifecycle: Lifecycle
    now?: () => number
}

/**
 * Readiness tracks whether this pod holds credentials, not merely that a read ran: a pod
 * with none would answer every resolve all-missing, which callers treat as terminal. A read
 * that returns nothing keeps what is held, so a mount blip does not take a warm fleet out
 * of rotation and an empty mount at boot recovers once ESO syncs, without a crash loop.
 */
export class SecretMount {
    private held: MountedCredentials | null = null

    constructor(private readonly opts: SecretMountOptions) {}

    /** The credentials currently being served, if any. */
    current(): MountedCredentials | null {
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
                // Keeping what is already held is what stops an unreadable mount failing
                // every read. The gauge is what stops that being silent.
                servingStaleSeconds.set((now() - Date.parse(this.held.fetchedAt)) / 1000)
            } else if (this.opts.lifecycle.ready) {
                logger.error('mount:credentials_lost', { dir: this.opts.dir })
            }
        }
        this.opts.lifecycle.ready = this.held !== null
    }

    private build(values: Record<string, string>): MountedCredentials | null {
        // Hash the whole set, sorted, so the id is stable and identifies the content rather
        // than an AWS version we can no longer see from a mount.
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
        const credentials: Record<string, Credential> = {}

        for (const [key, value] of Object.entries(values)) {
            // The one rule keeping the signing keys on this mount out of a response.
            if (key.startsWith(RESERVED_PREFIX)) {
                continue
            }
            if (inRecovery.has(key)) {
                credentials[key] = { state: 'recovery', versionId: contentHash, fetchedAt }
                continue
            }
            const previous = commaList(values[`${key}${FALLBACK_SUFFIX}`])[0]
            if (previous !== undefined && previous !== value) {
                credentials[key] = { state: 'rotating', value, previous, versionId: contentHash, fetchedAt }
                continue
            }
            credentials[key] = { state: 'steady', value, versionId: contentHash, fetchedAt }
        }

        if (Object.keys(credentials).length === 0) {
            // Counting files rather than credentials would call a mount holding nothing but
            // signing keys healthy, and every resolve would answer all-missing, which a
            // caller treats as a deleted credential.
            logger.warn('mount:no_credentials', { dir: this.opts.dir })
            return null
        }

        return { fetchedAt, versionId: contentHash, credentials }
    }
}
