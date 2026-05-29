/**
 * `useMutatingBundle` — fetches the bundle for an agent via the API
 * client and refetches when a `bundle:<applicationId>` mutation event
 * arrives. Returns the current `BundleFile[]` plus the bundle's
 * `lastMutationId` for correlation with focus events.
 *
 * Artificial refetch delay (`REFETCH_DELAY_MS`): the mutation event
 * fires `useMutationFlair` immediately so the flair animation can
 * start, then the data swap waits a beat so the new value visibly
 * lands *inside* the pulse rather than at the same instant. Mirrors
 * what real-world latency between "mutation acknowledged" and
 * "GET returns new state" would look like.
 */

'use client'

import { useEffect, useRef, useState } from 'react'

import type { BundleFile } from '@posthog/agent-chat/fixtures'

import { getBundle } from '@/lib/apiClient'

import { useMutationStream } from './mutation-stream'

const REFETCH_DELAY_MS = 500

interface MutatingBundle {
    bundle: BundleFile[]
    lastMutationId: string | null
    loading: boolean
    error: Error | null
}

export function useMutatingBundle(agentSlug: string, applicationId: string): MutatingBundle {
    const stream = useMutationStream()
    const [state, setState] = useState<MutatingBundle>({
        bundle: [],
        lastMutationId: null,
        loading: true,
        error: null,
    })
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const reqIdRef = useRef(0)

    const refetch = (mutationId: string | null): void => {
        const myReqId = ++reqIdRef.current
        getBundle(agentSlug)
            .then((bundle) => {
                if (myReqId !== reqIdRef.current) {
                    return
                }
                setState({ bundle, lastMutationId: mutationId, loading: false, error: null })
            })
            .catch((err: unknown) => {
                if (myReqId !== reqIdRef.current) {
                    return
                }
                setState((prev) => ({
                    ...prev,
                    loading: false,
                    error: err instanceof Error ? err : new Error(String(err)),
                }))
            })
    }

    useEffect(() => {
        setState((prev) => ({ ...prev, loading: true }))
        refetch(null)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [agentSlug])

    useEffect(() => {
        const entityKey = `bundle:${applicationId}`
        const unsubscribe = stream.subscribe(entityKey, (event) => {
            if (timerRef.current) {
                clearTimeout(timerRef.current)
            }
            timerRef.current = setTimeout(() => {
                refetch(event.mutationId)
            }, REFETCH_DELAY_MS)
        })
        return () => {
            unsubscribe()
            if (timerRef.current) {
                clearTimeout(timerRef.current)
            }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [applicationId, stream])

    return state
}
