import type { FeedItem, FeedUnit, Moment } from './feedModel'

/** One page of the vertical feed: a moment of a recording on the Moment tab, the whole recording on Full recording. */
export interface FeedCardEntry {
    /** The list key and the player key. The card on screen keeps it across a tab switch, so its page stays loaded. */
    key: string
    /** The card's position in the whole feed. */
    index: number
    item: FeedItem
    /** The moment this card plays, as an index into `moments`. Always 0 on Full recording. */
    ordinal: number
    moments: readonly Moment[]
    /** The first card of its recording: auto-advance to a new recording lands here. */
    first: boolean
}

/** Gives one card of a recording the key of the card that was on screen before a tab switch. */
export interface KeyOverride {
    ordinal: number
    key: string
}

function baseKey(sessionId: string, ordinal: number): string {
    return `${sessionId}:${ordinal}`
}

/** The key of a moment card. An override moves a key to another moment and swaps the two, so keys stay unique. */
export function momentCardKey(sessionId: string, ordinal: number, override: KeyOverride | undefined): string {
    if (!override) {
        return baseKey(sessionId, ordinal)
    }
    if (ordinal === override.ordinal) {
        return override.key
    }
    const moved = Number(override.key.slice(sessionId.length + 1))
    return ordinal === moved ? baseKey(sessionId, override.ordinal) : baseKey(sessionId, ordinal)
}

export function fullCardKey(sessionId: string, override: KeyOverride | undefined): string {
    return override?.key ?? baseKey(sessionId, 0)
}

export function buildFeedCards(
    items: readonly FeedItem[],
    unit: FeedUnit,
    momentsFor: (item: FeedItem) => readonly Moment[],
    overrides: ReadonlyMap<string, KeyOverride>
): FeedCardEntry[] {
    const cards: FeedCardEntry[] = []
    for (const item of items) {
        const { sessionId } = item.recording
        const moments = momentsFor(item)
        const override = overrides.get(sessionId)
        if (unit === 'session') {
            cards.push({
                key: fullCardKey(sessionId, override),
                index: cards.length,
                item,
                ordinal: 0,
                moments,
                first: true,
            })
            continue
        }
        moments.forEach((_moment, ordinal) => {
            cards.push({
                key: momentCardKey(sessionId, ordinal, override),
                index: cards.length,
                item,
                ordinal,
                moments,
                first: ordinal === 0,
            })
        })
    }
    return cards
}

/** The moment whose window holds `seconds`, else the one whose window is closest to it. */
export function nearestMoment(moments: readonly Moment[], seconds: number): number {
    'worklet'
    let best = 0
    let bestDistance = Number.POSITIVE_INFINITY
    moments.forEach((moment, index) => {
        const distance = Math.max(0, moment.startSeconds - seconds, seconds - moment.endSeconds)
        if (distance < bestDistance) {
            best = index
            bestDistance = distance
        }
    })
    return best
}

/**
 * Where playback goes after `index`: the next moment of the same recording, else the first card of a later recording
 * that has ended. Of the next `lookahead` such recordings, the first that can play at once wins.
 */
export function nextCardIndex(
    cards: readonly FeedCardEntry[],
    index: number,
    isReady: (item: FeedItem) => boolean,
    lookahead: number
): number | null {
    const entry = cards[index]
    const following = cards[index + 1]
    if (!entry) {
        return null
    }
    if (following && following.item.recording.sessionId === entry.item.recording.sessionId) {
        return index + 1
    }
    const candidates: number[] = []
    for (let position = index + 1; position < cards.length; position += 1) {
        const card = cards[position] as FeedCardEntry
        if (card.first && !card.item.recording.ongoing) {
            candidates.push(position)
        }
    }
    const ready = candidates.slice(0, lookahead).find((position) => isReady((cards[position] as FeedCardEntry).item))
    return ready ?? candidates[0] ?? null
}
