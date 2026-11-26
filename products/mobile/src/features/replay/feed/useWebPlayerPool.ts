import { useEffect, useRef, useState } from 'react'

import { demoReplaySnapshots } from '@/demo/replays'

import { WebReplayPlayer } from '../web/WebReplayPlayer'
import type { FeedCardEntry } from './feedCards'
import { FEED_DEBUG } from './feedPerf'
import type { PoolPlayer } from './feedPlayer'

const NO_PLAYERS: ReadonlyMap<string, PoolPlayer> = new Map()

/**
 * Up to three WebView players for the current, next and previous cards, keyed by card key. Two moments of one
 * recording are two cards, and each has its own page. The key, not the index, finds a card's player, so a card that
 * moves in the list (a tab switch, or moments that load above it) keeps its page. A card that leaves the window loses
 * its player, and its WebView unmounts with it, so at most three pages hold a rebuilt recording.
 */
export function useWebPlayerPool(
    cards: readonly FeedCardEntry[] | null,
    current: number,
    enabled: boolean,
    demo: boolean
): ReadonlyMap<string, PoolPlayer> {
    const players = useRef(new Map<string, WebReplayPlayer>())
    const [assigned, setAssigned] = useState<ReadonlyMap<string, PoolPlayer>>(NO_PLAYERS)

    useEffect(() => {
        const keep = new Map<string, WebReplayPlayer>()
        const next = new Map<string, PoolPlayer>()
        if (enabled && cards) {
            for (const index of [current, current + 1, current - 1]) {
                const card = cards[index]
                const recording = card?.item.recording
                const startMs = recording?.startedAt ? Date.parse(recording.startedAt) : Number.NaN
                if (!card || !recording || Number.isNaN(startMs)) {
                    continue
                }
                let player = players.current.get(card.key)
                if (!player) {
                    const snapshots = demo ? demoReplaySnapshots(recording.sessionId, startMs) : undefined
                    if (demo && !snapshots) {
                        continue
                    }
                    player = new WebReplayPlayer(recording.sessionId, startMs, snapshots)
                }
                keep.set(card.key, player)
                next.set(card.key, { kind: 'web', player, key: `web:${card.key}`, loaded: true })
            }
        }
        for (const [key, player] of players.current) {
            if (!keep.has(key)) {
                player.destroy()
            }
        }
        players.current = keep
        if (FEED_DEBUG) {
            ;(globalThis as { __replayWebPlayers?: Map<string, WebReplayPlayer> }).__replayWebPlayers = keep
        }
        setAssigned((previous) => {
            const same =
                previous.size === next.size &&
                [...next].every(([key, entry]) => previous.get(key)?.player === entry.player)
            return same ? previous : next
        })
    }, [cards, current, enabled, demo])

    useEffect(
        () => () => {
            for (const player of players.current.values()) {
                player.destroy()
            }
            players.current = new Map()
        },
        []
    )

    return assigned
}
