import posthog from 'lib/posthog-typed'
import { uuid } from 'lib/utils/dom'

import type { WatchFeedItemApi } from '../generated/api.schemas'

/** One feed fetch. Every card event carries its id, so a click, dismissal, or impression joins back to the ranked list it came from. */
export interface WatchFeedLoad {
    feedLoadId: string
    ranker: string
}

export function newWatchFeedLoad(ranker: string | null | undefined): WatchFeedLoad {
    return { feedLoadId: uuid(), ranker: ranker ?? 'weighted-score' }
}

export function servedListProperties(load: WatchFeedLoad | null, items: WatchFeedItemApi[]): Record<string, unknown> {
    return {
        feed_load_id: load?.feedLoadId ?? null,
        observation_ids: items.map((item) => item.observation.id),
        reason_kinds: items.map((item) => item.reason.kind),
    }
}

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
        // Joins to the player's `recording viewed summary` event.
        session_id: observation.session_id,
        position,
        reason_kind: reason.kind,
        observation_age_ms: Number.isFinite(createdAt) ? Math.max(0, Date.now() - createdAt) : null,
    }
}

/** Batches one load's seen cards into a single event. Flushes on tab hide too, since a closed tab sends nothing later. */
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
