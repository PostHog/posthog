import { useVideoPlayer, type VideoPlayer, type VideoSource } from 'expo-video'
import { useEffect, useMemo, useRef, useState } from 'react'

import type { ReplayVideoSource } from '@/api/replayVideo'

import type { PoolPlayer } from './feedPlayer'

export interface PoolSource {
    key: string
    source: ReplayVideoSource
}

interface Slot {
    index: number | null
    key: string | null
    /** False from `replaceAsync` until it settles, so a card never seeks the video the player held before. */
    loaded: boolean
}

function setUp(player: VideoPlayer): void {
    player.timeUpdateEventInterval = 0.25
    player.loop = false
    // Replays have no sound. Muted players also leave other apps' audio alone.
    player.muted = true
    player.keepScreenOnWhilePlaying = true
}

function toVideoSource(source: ReplayVideoSource): VideoSource {
    return source.headers ? { uri: source.uri, headers: source.headers } : { uri: source.uri }
}

export function usePlayerPool(
    sources: ReadonlyMap<number, PoolSource>,
    current: number
): ReadonlyMap<number, PoolPlayer> {
    const first = useVideoPlayer(null, setUp)
    const second = useVideoPlayer(null, setUp)
    const third = useVideoPlayer(null, setUp)
    const players = useMemo(() => [first, second, third], [first, second, third])
    const slots = useRef<Slot[]>(players.map(() => ({ index: null, key: null, loaded: false })))
    const [assigned, setAssigned] = useState<ReadonlyMap<number, PoolPlayer>>(() => new Map())
    const [loads, setLoads] = useState(0)

    // biome-ignore lint/correctness/useExhaustiveDependencies: `loads` republishes the map when a source finishes loading.
    useEffect(() => {
        // The card on screen first, then the next one, which auto-advance and the usual swipe go to.
        const wanted = [current, current + 1, current - 1].filter((index) => sources.has(index))
        const next = slots.current.map((slot) =>
            slot.index !== null && wanted.includes(slot.index)
                ? { ...slot }
                : { index: null, key: slot.key, loaded: slot.loaded }
        )
        for (const index of wanted) {
            if (next.some((slot) => slot.index === index)) {
                continue
            }
            const free = next.find((slot) => slot.index === null)
            if (free) {
                free.index = index
            }
        }
        next.forEach((slot, position) => {
            const player = players[position] as VideoPlayer
            const want = slot.index === null ? null : sources.get(slot.index)
            if (!want) {
                player.pause()
                return
            }
            if (want.key !== slot.key) {
                const key = want.key
                slot.key = key
                slot.loaded = false
                player.pause()
                player
                    .replaceAsync(toVideoSource(want.source))
                    .catch(() => undefined)
                    .finally(() => {
                        const latest = slots.current[position]
                        if (latest?.key === key) {
                            latest.loaded = true
                            setLoads((count) => count + 1)
                        }
                    })
            }
        })
        slots.current = next
        setAssigned((previous) => {
            const map = new Map<number, PoolPlayer>()
            next.forEach((slot, position) => {
                if (slot.index !== null && slot.key !== null) {
                    map.set(slot.index, {
                        kind: 'video',
                        player: players[position] as VideoPlayer,
                        key: slot.key,
                        loaded: slot.loaded,
                    })
                }
            })
            const same =
                previous.size === map.size &&
                [...map].every(([index, entry]) => {
                    const old = previous.get(index)
                    return old?.player === entry.player && old.key === entry.key && old.loaded === entry.loaded
                })
            return same ? previous : map
        })
    }, [sources, current, players, loads])

    return assigned
}
