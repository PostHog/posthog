import { dayjs } from 'lib/dayjs'

import type { ResourceEditedEvent } from '~/types'

export type ResourceEditedVerdict = 'ignore' | 'defer' | 'external'

export interface ResourceSaveQueueOptions {
    resourceType: ResourceEditedEvent['resource_type']
    getResourceId: () => string | null | undefined
    /** The newest server stamp this editor has loaded or saved. An event no newer than it is the echo of our own write. */
    getLoadedStamp: () => string | null | undefined
    /** Other reasons to hold events back, such as a load in flight or a publish about to reload. */
    isBusy?: () => boolean
}

/**
 * Runs an editor's saves one at a time, so a queued save fences on the stamp the save before it wrote
 * instead of coming back 409. Edit events that land mid-save are held until the saves settle, because
 * the server's event for our own write can beat its HTTP response.
 */
export class ResourceSaveQueue {
    private chain: Promise<unknown> = Promise.resolve()
    private pending = 0
    private deferred: ResourceEditedEvent | null = null

    constructor(private readonly options: ResourceSaveQueueOptions) {}

    get inFlight(): number {
        return this.pending
    }

    run<T>(save: () => Promise<T>): Promise<T> {
        this.pending += 1
        const settle = (): void => {
            this.pending -= 1
        }
        const current = this.chain.then(save, save)
        current.then(settle, settle)
        this.chain = current.then(
            () => undefined,
            () => undefined
        )
        return current
    }

    whenIdle(): Promise<void> {
        return this.chain.then(() => undefined)
    }

    classify(event: ResourceEditedEvent): ResourceEditedVerdict {
        if (event.resource_type !== this.options.resourceType || event.resource_id !== this.options.getResourceId()) {
            return 'ignore'
        }
        if (this.pending > 0 || this.options.isBusy?.()) {
            this.deferred = event
            return 'defer'
        }
        const loaded = this.options.getLoadedStamp()
        return loaded && dayjs(event.updated_at).isAfter(dayjs(loaded)) ? 'external' : 'ignore'
    }

    /** Call after a save or load settles, and dispatch the event again. */
    takeDeferred(): ResourceEditedEvent | null {
        const deferred = this.deferred
        this.deferred = null
        return deferred
    }
}
