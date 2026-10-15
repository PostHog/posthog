import posthog from 'lib/posthog-typed'
import { uuid } from 'lib/utils/dom'

import type { WatchFeedItemApi } from '../generated/api.schemas'

/** One fetch of the feed, as the events that came from it name it. A later ranker trains on these events,
 * so every event about a card carries the load it came from: that is what ties a click, a dismissal, or an
 * impression back to the ranked list it was picked out of. */
export interface WatchFeedLoad {
    feedLoadId: string
    ranker: string
}

export function newWatchFeedLoad(ranker: string | null | undefined): WatchFeedLoad {
    return { feedLoadId: uuid(), ranker: ranker ?? 'weighted-score' }
}

/** The ranked list as served, in order, so a card the reader never opened still counts as shown at its place. */
export function servedListProperties(load: WatchFeedLoad | null, items: WatchFeedItemApi[]): Record<string, unknown> {
    return {
        feed_load_id: load?.feedLoadId ?? null,
        observation_ids: items.map((item) => item.observation.id),
        reason_kinds: items.map((item) => item.reason.kind),
    }
}

/** What every per-card event says about the card, so the events join on the same keys. */
export function cardProperties(
    load: WatchFeedLoad | null,
    item: WatchFeedItemApi,
    position: number,
    surface: string
): Record<string, unknown> {
    const { observation, reason } = item
    const createdAt = Date.parse(observation.created_at)
    return {
        feed_load_id: load?.feedLoadId ?? null,
        ranker: load?.ranker ?? null,
        surface,
        observation_id: observation.id,
        scanner_id: observation.scanner_id,
        // The recording's id, so the `recording viewed summary` event the player sends later joins to this card.
        session_id: observation.session_id,
        position,
        reason_kind: reason.kind,
        observation_age_ms: Number.isFinite(createdAt) ? Math.max(0, Date.now() - createdAt) : null,
    }
}

/**
 * Collects the cards a reader actually saw during one feed load and sends them as one event, so a page of
 * 50 cards costs one event instead of 50. Flushed when the load is replaced, the surface unmounts, or the
 * tab is hidden: the last of these is the only one a closed tab still reaches.
 */
export class WatchFeedImpressions {
    private seen = new Map<string, { position: number; reason_kind: string }>()
    // A tab hidden and shown again flushes twice in one load; a card is reported once per load.
    private reported = new Set<string>()
    private load: WatchFeedLoad | null = null

    constructor(private readonly surface: string) {}

    start(load: WatchFeedLoad | null): void {
        this.flush()
        this.reported.clear()
        this.load = load
    }

    add(item: WatchFeedItemApi, position: number): void {
        if (!this.seen.has(item.observation.id) && !this.reported.has(item.observation.id)) {
            this.seen.set(item.observation.id, { position, reason_kind: item.reason.kind })
        }
    }

    flush(): void {
        if (this.seen.size === 0) {
            return
        }
        posthog.capture('replay_vision_watch_feed_impressions', {
            feed_load_id: this.load?.feedLoadId ?? null,
            ranker: this.load?.ranker ?? null,
            surface: this.surface,
            count: this.seen.size,
            impressions: Array.from(this.seen, ([observation_id, card]) => ({ observation_id, ...card })),
        })
        for (const observationId of this.seen.keys()) {
            this.reported.add(observationId)
        }
        this.seen.clear()
    }

    /** A `cache.disposables` setup: flushes when the tab is hidden, and once more when the logic unmounts. */
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
