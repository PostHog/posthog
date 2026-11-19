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
    source: ReplayVideoSource | null
    loaded: boolean
    failed: boolean
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
    const slots = useRef<Slot[]>(
        players.map(() => ({ index: null, key: null, source: null, loaded: false, failed: false }))
    )
    const [assigned, setAssigned] = useState<ReadonlyMap<number, PoolPlayer>>(() => new Map())
    const [loads, setLoads] = useState(0)

    useEffect(() => {
        const subscriptions = players.map((player, index) =>
            player.addListener('statusChange', ({ status }) => {
                const slot = slots.current[index]
                if (status === 'error' && slot?.loaded) {
                    slot.loaded = false
                    slot.failed = true
                    setLoads((count) => count + 1)
                }
            })
        )
        return () => {
            for (const subscription of subscriptions) {
                subscription.remove()
            }
        }
    }, [players])

    // biome-ignore lint/correctness/useExhaustiveDependencies: `loads` republishes the map when a source finishes loading.
    useEffect(() => {
        // The card on screen first, then the next one, which auto-advance and the usual swipe go to.
        const wanted = [current, current + 1, current - 1].filter((index) => sources.has(index))
        const next = slots.current.map((slot) =>
            slot.index !== null && wanted.includes(slot.index) ? { ...slot } : { ...slot, index: null }
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
            if (want.key !== slot.key || want.source !== slot.source) {
                const { key, source } = want
                slot.key = key
                slot.source = source
                slot.loaded = false
                slot.failed = false
                player.pause()
                const settle = (loaded: boolean): void => {
                    const latest = slots.current[position]
                    if (latest?.key === key && latest.source === source) {
                        latest.loaded = loaded
                        latest.failed = !loaded
                        setLoads((count) => count + 1)
                    }
                }
                void player.replaceAsync(toVideoSource(source)).then(
                    () => settle(player.status !== 'error'),
                    () => settle(false)
                )
            }
        })
        slots.current = next
        setAssigned((previous) => {
            const map = new Map<number, PoolPlayer>()
            next.forEach((slot, position) => {
                if (slot.index !== null && slot.key !== null && slot.source !== null) {
                    map.set(slot.index, {
                        kind: 'video',
                        player: players[position] as VideoPlayer,
                        key: slot.key,
                        source: slot.source,
                        loaded: slot.loaded,
                        failed: slot.failed,
                    })
                }
            })
            const same =
                previous.size === map.size &&
                [...map].every(([index, entry]) => {
                    const old = previous.get(index)
                    return (
                        old?.kind === 'video' &&
                        entry.kind === 'video' &&
                        old.player === entry.player &&
                        old.key === entry.key &&
                        old.source === entry.source &&
                        old.loaded === entry.loaded &&
                        old.failed === entry.failed
                    )
                })
            return same ? previous : map
        })
    }, [sources, current, players, loads])

    return assigned
}
