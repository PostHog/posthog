import posthog from 'lib/posthog-typed'
import { uuid } from 'lib/utils/dom'

import type { HighlightFeedItemApi } from '../generated/api.schemas'

// A second on screen, enough to read the title, so a card scrolled past at speed does not count as shown.
export const CARD_SEEN_DWELL_MS = 1000

/** One feed fetch. Every card event carries its id, so a click, dismissal, or impression joins back to the ranked list it came from. */
export interface HighlightFeedLoad {
    feedLoadId: string
    // Each card's place as served, so a dismissal that shortens the list does not shift later cards' positions.
    positions: Record<string, number>
}

export function newHighlightFeedLoad(items: HighlightFeedItemApi[]): HighlightFeedLoad {
    return {
        feedLoadId: uuid(),
        positions: Object.fromEntries(items.map((item, index) => [item.observation.id, index])),
    }
}

/** The same load with a later page of unseen cards appended, each placed after every card served so far. */
export function withNextPage(load: HighlightFeedLoad, items: HighlightFeedItemApi[]): HighlightFeedLoad {
    const served = Object.keys(load.positions).length
    const positions = { ...load.positions }
    items.forEach((item, index) => {
        positions[item.observation.id] = served + index
    })
    return { ...load, positions }
}

function servedPosition(load: HighlightFeedLoad | null, item: HighlightFeedItemApi, position: number): number {
    return load?.positions[item.observation.id] ?? position
}

export function servedListProperties(
    load: HighlightFeedLoad | null,
    items: HighlightFeedItemApi[]
): Record<string, unknown> {
    return {
        feed_load_id: load?.feedLoadId ?? null,
        observation_ids: items.map((item) => item.observation.id),
        reason_kinds: items.map((item) => item.reason.kind),
    }
}

export function cardProperties(
    load: HighlightFeedLoad | null,
    item: HighlightFeedItemApi,
    position: number,
    surface: string
): Record<string, unknown> {
    const { observation, reason } = item
    const createdAt = Date.parse(observation.created_at)
    return {
        feed_load_id: load?.feedLoadId ?? null,
        surface,
        observation_id: observation.id,
        scanner_id: observation.scanner_id,
        // Joins to the player's `recording viewed summary` event.
        session_id: observation.session_id,
        position: servedPosition(load, item, position),
        reason_kind: reason.kind,
        observation_age_ms: Number.isFinite(createdAt) ? Math.max(0, Date.now() - createdAt) : null,
    }
}

/** Batches one load's seen cards into a single event. Flushes on tab hide too, since a closed tab sends nothing later. */
export class HighlightFeedImpressions {
    private seen = new Map<string, { position: number; reason_kind: string }>()
    // A tab hidden and shown again flushes twice in one load; a card is reported once per load.
    private reported = new Set<string>()
    private load: HighlightFeedLoad | null = null

    /** `onFlush` receives each batch of newly seen cards, for anything besides analytics that counts them. */
    constructor(
        private readonly surface: string,
        private readonly onFlush?: (load: HighlightFeedLoad, observationIds: string[]) => void
    ) {}

    start(load: HighlightFeedLoad | null): void {
        this.flush()
        this.reported.clear()
        this.load = load
    }

    /** Takes a later page of the same load without reporting its cards again. */
    extend(load: HighlightFeedLoad): void {
        this.load = load
    }

    add(item: HighlightFeedItemApi, position: number): void {
        if (!this.seen.has(item.observation.id) && !this.reported.has(item.observation.id)) {
            this.seen.set(item.observation.id, {
                position: servedPosition(this.load, item, position),
                reason_kind: item.reason.kind,
            })
        }
    }

    flush(): void {
        if (this.seen.size === 0) {
            return
        }
        posthog.capture('replay_vision_highlight_feed_impressions', {
            feed_load_id: this.load?.feedLoadId ?? null,
            surface: this.surface,
            count: this.seen.size,
            impressions: Array.from(this.seen, ([observation_id, card]) => ({ observation_id, ...card })),
        })
        if (this.load) {
            this.onFlush?.(this.load, Array.from(this.seen.keys()))
        }
        for (const observationId of this.seen.keys()) {
            this.reported.add(observationId)
        }
        this.seen.clear()
    }

    flushOnHideAndUnmount = (): (() => void) => {
        const flushWhenHidden = (): void => {
            if (document.visibilityState === 'hidden') {
                this.flush()
            }
        }
        document.addEventListener('visibilitychange', flushWhenHidden)
        return () => {
            document.removeEventListener('visibilitychange', flushWhenHidden)
            this.flush()
        }
    }
}
