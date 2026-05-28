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
 */

'use client'

import { useEffect, useState } from 'react'

import type { BundleFile } from '@posthog/agent-chat/fixtures'

import { getBundleForApplicationSync, getMutationRecord, subscribeMutation } from '@/lib/mockApi'

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
        // snapshot to avoid showing stale content.
        if (rec) {
            return {
                bundle: getBundleForApplicationSync(applicationId),
                revision: rec.revision,
                lastMutationId: rec.mutationId,
            }
        }
        return { bundle: initialBundle, revision: 0, lastMutationId: null }
    })

    useEffect(() => {
        return subscribeMutation(entityKey, (rec) => {
            setState({
                bundle: getBundleForApplicationSync(applicationId),
                revision: rec.revision,
                lastMutationId: rec.mutationId,
            })
        })
    }, [applicationId, entityKey])

    return state
}
