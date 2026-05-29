/**
 * `useMutationFlair` — subscribes a component to the mutation stream
 * for a single entity. When the entity's revision moves AND focus mode
 * is on, returns `flair: true` for the duration of the animation so
 * consumers can apply the `flair-pulse` class.
 *
 * Focus mode off → events still arrive, consumers still get the latest
 * mutationId, but `flair` stays false. This is the *quiet refresh*
 * path: data updates land in the UI without visual fanfare.
 */

'use client'

import { useEffect, useRef, useState } from 'react'

import { useFocusStore } from './focus-context'
import { useMutationStream } from './mutation-stream'

const FLAIR_MS = 2500

interface MutationFlairState {
    revision: number
    lastMutationId: string | null
    flair: boolean
}

export function useMutationFlair(entityKey: string | null): MutationFlairState {
    const { enabled } = useFocusStore()
    const stream = useMutationStream()
    const [state, setState] = useState<MutationFlairState>(() => {
        if (!entityKey) {
            return { revision: 0, lastMutationId: null, flair: false }
        }
        const last = stream.getLast(entityKey)
        // If we mounted into a fresh-but-not-yet-faded mutation (e.g. the
        // focus call switched the tab *after* the bump), treat it as if
        // a notification just arrived — otherwise we'd silently miss it.
        const recent = last ? Date.now() - last.at < FLAIR_MS : false
        return {
            revision: last?.revision ?? 0,
            lastMutationId: last?.mutationId ?? null,
            flair: recent && enabled,
        }
    })
    const flairTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const enabledRef = useRef(enabled)
    enabledRef.current = enabled

    // Mount-time: schedule the flair cleanup for fresh-on-mount cases.
    useEffect(() => {
        if (!entityKey) {
            return
        }
        const last = stream.getLast(entityKey)
        if (!last) {
            return
        }
        const remaining = FLAIR_MS - (Date.now() - last.at)
        if (remaining <= 0 || !enabledRef.current) {
            return
        }
        flairTimerRef.current = setTimeout(() => {
            setState((prev) => ({ ...prev, flair: false }))
        }, remaining)
        return () => {
            if (flairTimerRef.current) {
                clearTimeout(flairTimerRef.current)
                flairTimerRef.current = null
            }
        }
        // Mount-only — live updates handled by the subscription below.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    // Live subscription.
    useEffect(() => {
        if (!entityKey) {
            return
        }
        return stream.subscribe(entityKey, (event) => {
            setState({
                revision: event.revision,
                lastMutationId: event.mutationId,
                flair: enabledRef.current,
            })
            if (flairTimerRef.current) {
                clearTimeout(flairTimerRef.current)
            }
            if (enabledRef.current) {
                flairTimerRef.current = setTimeout(() => {
                    setState((prev) => ({ ...prev, flair: false }))
                }, FLAIR_MS)
            }
        })
    }, [entityKey, stream])

    useEffect(() => {
        return () => {
            if (flairTimerRef.current) {
                clearTimeout(flairTimerRef.current)
            }
        }
    }, [])

    return state
}
