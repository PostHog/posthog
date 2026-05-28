/**
 * `useMutationFlair` — subscribes a component to the mockApi mutation
 * registry for a single entity. When the entity's revision moves AND
 * focus mode is on, returns `flair: true` for the duration of the
 * animation so consumers can apply the `flair-pulse` class.
 *
 * Focus mode off → revision still bumps, consumers still rerender, but
 * `flair` stays false. This is the *quiet refresh* path: data updates
 * land in the UI without visual fanfare.
 *
 * Returns `{ revision, lastMutationId, flair }`:
 *   - revision: monotonic counter — use as a dependency to refetch.
 *   - lastMutationId: latest correlation token; consumers can compare
 *     against an incoming focus-event mutationId to dedupe.
 *   - flair: true for `FLAIR_MS` ms after the revision moves.
 */

'use client'

import { useEffect, useRef, useState } from 'react'

import { getMutationRecord, subscribeMutation, type EntityKey } from '@/lib/mockApi'

import { useFocusStore } from './focus-context'

const FLAIR_MS = 1700

interface MutationFlairState {
    revision: number
    lastMutationId: string | null
    flair: boolean
}

export function useMutationFlair(entityKey: EntityKey | null): MutationFlairState {
    const { enabled } = useFocusStore()
    const [state, setState] = useState<MutationFlairState>(() => {
        if (!entityKey) {
            return { revision: 0, lastMutationId: null, flair: false }
        }
        const rec = getMutationRecord(entityKey)
        // If the entity was bumped recently (e.g. the focus call mounted us
        // *after* the mutation that triggered it landed), treat it as if a
        // notification just arrived — otherwise we'd silently miss the flair.
        const recent = rec ? Date.now() - rec.at < FLAIR_MS : false
        return {
            revision: rec?.revision ?? 0,
            lastMutationId: rec?.mutationId ?? null,
            flair: recent && enabled,
        }
    })
    const flairTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const enabledRef = useRef(enabled)
    enabledRef.current = enabled

    // If we mounted into a fresh-but-not-yet-faded mutation, schedule the
    // cleanup so flair clears at the same wall-clock moment it would have
    // if we'd been subscribed at the time.
    useEffect(() => {
        if (!entityKey) {
            return
        }
        const rec = getMutationRecord(entityKey)
        if (!rec) {
            return
        }
        const remaining = FLAIR_MS - (Date.now() - rec.at)
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
        // Mount-only — subsequent updates handled by the subscription effect.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    useEffect(() => {
        if (!entityKey) {
            return
        }
        return subscribeMutation(entityKey, (rec) => {
            setState({
                revision: rec.revision,
                lastMutationId: rec.mutationId,
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
    }, [entityKey])

    useEffect(() => {
        return () => {
            if (flairTimerRef.current) {
                clearTimeout(flairTimerRef.current)
            }
        }
    }, [])

    return state
}
