import posthog from 'lib/posthog-typed'
import { uuid } from 'lib/utils/dom'
import { getCurrentTeamIdOrNone } from 'lib/utils/getAppContext'

import { visionScannersWatchFeedImpressionsCreate } from '../generated/api'
import type { WatchFeedItemApi } from '../generated/api.schemas'

// A second on screen, enough to read the title, so a card scrolled past at speed does not count as shown.
export const CARD_SEEN_DWELL_MS = 1000

// The impressions endpoint takes at most this many ids per request.
const IMPRESSIONS_BATCH_SIZE = 100

/** One feed fetch. Every card event carries its id, so a click, dismissal, or impression joins back to the ranked list it came from. */
export interface WatchFeedLoad {
    feedLoadId: string
    ranker: string
    // Each card's place as served, so a dismissal that shortens the list does not shift later cards' positions.
    positions: Record<string, number>
}

export function newWatchFeedLoad(
    ranker: string | null | undefined,
    items: WatchFeedItemApi[],
    feedLoadId: string = uuid()
): WatchFeedLoad {
    return {
        feedLoadId,
        ranker: ranker ?? 'weighted-score',
        positions: Object.fromEntries(items.map((item, index) => [item.observation.id, index])),
    }
}

/** The same load with a later page appended, each new card placed after every card served so far. */
export function withNextPage(load: WatchFeedLoad, items: WatchFeedItemApi[]): WatchFeedLoad {
    const positions = { ...load.positions }
    for (const item of items) {
        if (!(item.observation.id in positions)) {
            positions[item.observation.id] = Object.keys(positions).length
        }
    }
    return { ...load, positions }
}

function servedPosition(load: WatchFeedLoad | null, item: WatchFeedItemApi, position: number): number {
    return load?.positions[item.observation.id] ?? position
}

export function servedListProperties(load: WatchFeedLoad | null, items: WatchFeedItemApi[]): Record<string, unknown> {
    return {
        feed_load_id: load?.feedLoadId ?? null,
        ranker: load?.ranker ?? null,
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
        position: servedPosition(load, item, position),
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

    /** Takes a later page of the same load without reporting its cards again. */
    extend(load: WatchFeedLoad): void {
        this.load = load
    }

    add(item: WatchFeedItemApi, position: number): void {
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
        posthog.capture('replay_vision_watch_feed_impressions', {
            feed_load_id: this.load?.feedLoadId ?? null,
            ranker: this.load?.ranker ?? null,
            surface: this.surface,
            count: this.seen.size,
            impressions: Array.from(this.seen, ([observation_id, card]) => ({ observation_id, ...card })),
        })
        const teamId = getCurrentTeamIdOrNone()
        if (teamId && this.load) {
            // The server counts impressions so the feed ranks a card lower each time it is shown. Best effort:
            // a lost batch only means one card ranks a little higher next time.
            const ids = Array.from(this.seen.keys())
            for (let start = 0; start < ids.length; start += IMPRESSIONS_BATCH_SIZE) {
                void visionScannersWatchFeedImpressionsCreate(String(teamId), {
                    feed_load_id: this.load.feedLoadId,
                    observation_ids: ids.slice(start, start + IMPRESSIONS_BATCH_SIZE),
                }).catch(() => {})
            }
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
