/**
 * `useMutatingRevisions` — fetches the revisions for an agent via the
 * API client and refetches when a `revisions:<applicationId>` mutation
 * event arrives. Mirrors `useMutatingBundle` for the other half of the
 * agent-detail data.
 *
 * Live notifications are debounced through `REFETCH_DELAY_MS` so the
 * registry bump fires the flair animation first, then the new value
 * lands visibly inside the pulse.
 */

'use client'

import { useEffect, useRef, useState } from 'react'

import type { AgentRevisionFixture } from '@posthog/agent-chat/fixtures'

import { listRevisions } from '@/lib/apiClient'

import { useMutationStream } from './mutation-stream'

const REFETCH_DELAY_MS = 500

interface MutatingRevisions {
    revisions: AgentRevisionFixture[]
    lastMutationId: string | null
    loading: boolean
    error: Error | null
}

export function useMutatingRevisions(agentSlug: string, applicationId: string): MutatingRevisions {
    const stream = useMutationStream()
    const [state, setState] = useState<MutatingRevisions>({
        revisions: [],
        lastMutationId: null,
        loading: true,
        error: null,
    })
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const reqIdRef = useRef(0)

    const refetch = (mutationId: string | null): void => {
        const myReqId = ++reqIdRef.current
        listRevisions(agentSlug)
            .then((revisions) => {
                if (myReqId !== reqIdRef.current) {
                    return
                }
                setState({ revisions, lastMutationId: mutationId, loading: false, error: null })
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
        const entityKey = `revisions:${applicationId}`
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
