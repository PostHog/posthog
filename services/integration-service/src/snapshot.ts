// Holds the credential snapshot and the readiness it implies.
//
// Readiness tracks whether this pod actually holds a snapshot, not merely that a reload
// ran: a pod with none would answer every resolve all-missing, which callers treat as
// terminal, so it must fail its probe instead. A reload that returns nothing keeps the
// previous snapshot, so a transient mount blip does not take a warm fleet out of rotation,
// and an empty mount at boot recovers on its own once ESO syncs, without a crash loop.

import type { Lifecycle } from './http/app'
import { logger } from './lib/logging'
import { secretAgeSeconds, servingStaleSeconds, storeErrorsTotal } from './metrics'
import type { SecretStore } from './store/fileStore'
import type { SecretsSnapshot } from './types'

export interface SnapshotManagerOptions {
    store: SecretStore
    lifecycle: Lifecycle
    /** Mount directory, for log context only. */
    dir: string
    now?: () => number
}

export class SnapshotManager {
    private snapshot: SecretsSnapshot | null = null

    constructor(private readonly opts: SnapshotManagerOptions) {}

    /** The snapshot currently being served, if any. */
    current(): SecretsSnapshot | null {
        return this.snapshot
    }

    async reload(): Promise<void> {
        const now = this.opts.now ?? Date.now
        const next = await this.opts.store.load()
        if (next) {
            this.snapshot = next
            servingStaleSeconds.set(0)
            if (next.changedAt) {
                secretAgeSeconds.set((now() - Date.parse(next.changedAt)) / 1000)
            }
        } else {
            storeErrorsTotal.inc()
            if (this.snapshot) {
                // Keeping the last snapshot is what stops an unreadable mount failing every
                // read. The gauge is what stops that being silent.
                servingStaleSeconds.set((now() - Date.parse(this.snapshot.fetchedAt)) / 1000)
            } else if (this.opts.lifecycle.ready) {
                logger.error('secrets:snapshot_lost', { dir: this.opts.dir })
            }
        }
        this.opts.lifecycle.ready = this.snapshot !== null
    }
}
