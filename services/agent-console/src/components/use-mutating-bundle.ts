/**
 * `useMutatingBundle` — subscribes to the bundle-level entity revision
 * for an application and re-reads the bundle (with mockApi's overlay
 * applied) whenever any file in it mutates. Returns the current
 * `BundleFile[]` plus the bundle's `lastMutationId` for correlation
 * with focus events.
 *
 * Server-rendered initial state is passed in via `initialBundle` so the
 * first paint matches what Next.js streamed; subsequent updates come
 * from the client-side overlay.
 *
 * **Artificial refetch delay** (`REFETCH_DELAY_MS`): the registry bump
 * fires `useMutationFlair` immediately so the flair animation can start,
 * then the data swap waits a beat so the new value visibly lands
 * *inside* the pulse rather than at the same instant. Mirrors what
 * real-world latency between "mutation acknowledged" and "GET returns
 * new state" would look like.
 */

'use client'

import { useEffect, useRef, useState } from 'react'

import type { BundleFile } from '@posthog/agent-chat/fixtures'

import { getBundleForApplicationSync, getMutationRecord, subscribeMutation } from '@/lib/mockApi'

const REFETCH_DELAY_MS = 500

interface MutatingBundle {
    bundle: BundleFile[]
    revision: number
    lastMutationId: string | null
}

export function useMutatingBundle(applicationId: string, initialBundle: BundleFile[]): MutatingBundle {
    const entityKey = `bundle:${applicationId}`
    const [state, setState] = useState<MutatingBundle>(() => {
        const rec = getMutationRecord(entityKey)
        // If the registry already knows about a mutation (e.g. user navigated
        // away and back), prefer the overlay-merged read over the server
        // snapshot to avoid showing stale content. On-mount path is never
        // delayed — only live notifications get the artificial latency.
        if (rec) {
            return {
                bundle: getBundleForApplicationSync(applicationId),
                revision: rec.revision,
                lastMutationId: rec.mutationId,
            }
        }
        return { bundle: initialBundle, revision: 0, lastMutationId: null }
    })
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    useEffect(() => {
        return subscribeMutation(entityKey, (rec) => {
            if (timerRef.current) {
                clearTimeout(timerRef.current)
            }
            timerRef.current = setTimeout(() => {
                setState({
                    bundle: getBundleForApplicationSync(applicationId),
                    revision: rec.revision,
                    lastMutationId: rec.mutationId,
                })
            }, REFETCH_DELAY_MS)
        })
    }, [applicationId, entityKey])

    useEffect(() => {
        return () => {
            if (timerRef.current) {
                clearTimeout(timerRef.current)
            }
        }
    }, [])

    return state
}
