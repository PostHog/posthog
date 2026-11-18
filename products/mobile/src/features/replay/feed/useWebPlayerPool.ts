import { useEffect, useRef, useState } from 'react'

import { WebReplayPlayer } from '../web/WebReplayPlayer'
import type { FeedItem } from './feedModel'
import type { PoolPlayer } from './feedPlayer'

const NO_PLAYERS: ReadonlyMap<number, PoolPlayer> = new Map()

/**
 * Up to three WebView players for the current, next and previous cards, keyed by session. A card that leaves the
 * window loses its player, and its WebView unmounts with it, so at most three pages hold a rebuilt recording.
 */
export function useWebPlayerPool(
    items: readonly FeedItem[] | null,
    current: number,
    enabled: boolean
): ReadonlyMap<number, PoolPlayer> {
    const players = useRef(new Map<string, WebReplayPlayer>())
    const [assigned, setAssigned] = useState<ReadonlyMap<number, PoolPlayer>>(NO_PLAYERS)

    useEffect(() => {
        const keep = new Map<string, WebReplayPlayer>()
        const next = new Map<number, PoolPlayer>()
        if (enabled && items) {
            for (const index of [current, current + 1, current - 1]) {
                const recording = items[index]?.recording
                const startMs = recording?.startedAt ? Date.parse(recording.startedAt) : Number.NaN
                if (!recording || Number.isNaN(startMs)) {
                    continue
                }
                const player =
                    players.current.get(recording.sessionId) ?? new WebReplayPlayer(recording.sessionId, startMs)
                keep.set(recording.sessionId, player)
                next.set(index, { kind: 'web', player, key: `web:${recording.sessionId}`, loaded: true })
            }
        }
        for (const [sessionId, player] of players.current) {
            if (!keep.has(sessionId)) {
                player.destroy()
            }
        }
        players.current = keep
        if (__DEV__) {
            ;(globalThis as { __replayWebPlayers?: Map<string, WebReplayPlayer> }).__replayWebPlayers = keep
        }
        setAssigned((previous) => {
            const same =
                previous.size === next.size &&
                [...next].every(([index, entry]) => previous.get(index)?.player === entry.player)
            return same ? previous : next
        })
    }, [items, current, enabled])

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
