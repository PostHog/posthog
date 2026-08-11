// The mounted Kubernetes Secret: reads it, holds the credentials it currently carries, and
// drives readiness from whether this pod holds any.
//
// External Secrets Operator syncs the AWS secret into a Kubernetes Secret, and kubelet
// mounts it as a directory: one file per key, the file contents being the value. Kubelet
// rewrites the mount in place when the content changes, so a rotation reaches the pod
// without a restart, and it swaps the `..data` symlink atomically, so a read never sees a
// half-written set.

import { createHash } from 'node:crypto'
import { readFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'

import { logger } from './lib/logging'
import { secretAgeSeconds, mountErrorsTotal, servingStaleSeconds } from './metrics'
import type { Credential, Lifecycle, MountedCredentials } from './types'

/**
 * Marks an entry that is never served as a credential, whatever a token asks for. The
 * signing keys share this mount, and a double underscore cannot collide with a credential
 * name, which are the third party's own environment-variable names.
 */
export const RESERVED_PREFIX = '__'

/**
 * Reserved key naming the credentials that are in recovery, comma-separated.
 *
 * Uppercase and flat because PostHog/secrets only manages `[A-Z0-9_]+` keys with plain
 * string values.
 */
export const RECOVERY_KEYS = 'INTEGRATION_RECOVERY_KEYS'

/**
 * Suffix marking the outgoing value during a rotation: `STRIPE_APP_SECRET_KEY` alongside
 * `STRIPE_APP_SECRET_KEY_FALLBACKS`, comma-separated, newest first.
 *
 * A sibling key rather than an AWS staging label, because `AWSPREVIOUS` applies to a whole
 * secret version: with every credential in one secret, rotating Google or simply adding an
 * unrelated key would consume the slot Stripe's in-flight rotation was using and end its
 * overlap silently. A mount cannot see staging labels at all.
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

    if (Object.keys(values).length === 0) {
        logger.warn('mount:empty', { dir })
        return null
    }
    return values
}

export interface SecretMountOptions {
    /** Directory the Kubernetes Secret is mounted at. */
    dir: string
    lifecycle: Lifecycle
    /**
     * Records when a content hash was first seen and returns that timestamp. Persisted, so
     * every replica agrees and the answer survives a restart.
     */
    observeVersion: (contentHash: string) => Promise<string | null>
    now?: () => number
}

/**
 * Readiness tracks whether this pod actually holds credentials, not merely that a read ran:
 * a pod with none would answer every resolve all-missing, which callers treat as terminal,
 * so it must fail its probe instead. A read that returns nothing keeps what is already held,
 * so a transient mount blip does not take a warm fleet out of rotation, and an empty mount
 * at boot recovers on its own once ESO syncs, without a crash loop.
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
        const next = await this.load()
        if (next) {
            this.held = next
            servingStaleSeconds.set(0)
            if (next.changedAt) {
                secretAgeSeconds.set((now() - Date.parse(next.changedAt)) / 1000)
            }
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

    private async load(): Promise<MountedCredentials | null> {
        const values = await readMount(this.opts.dir)
        if (!values) {
            return null
        }

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
            // THE rule that keeps the caller signing keys sharing this mount from ever being
            // served as credentials.
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

        return {
            fetchedAt,
            versionId: contentHash,
            changedAt: await this.opts.observeVersion(contentHash),
            credentials,
        }
    }
}
