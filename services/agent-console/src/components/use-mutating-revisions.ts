/**
 * `useMutatingRevisions` — subscribes to the per-app `revisions:<id>`
 * entity revision and re-reads via mockApi's overlay whenever a
 * revision-spec mutation lands. Mirrors `useMutatingBundle` for the
 * other half of the agent-detail data.
 *
 * Live notifications are debounced through a short refetch delay so the
 * registry bump fires the flair animation first, then the new value
 * lands visibly inside the pulse. On-mount reads are immediate.
 */

'use client'

import { useEffect, useRef, useState } from 'react'

import type { AgentRevisionFixture } from '@posthog/agent-chat/fixtures'

import { getMutationRecord, listRevisionsSync, subscribeMutation } from '@/lib/mockApi'

const REFETCH_DELAY_MS = 500

interface MutatingRevisions {
    revisions: AgentRevisionFixture[]
    revision: number
    lastMutationId: string | null
}

export function useMutatingRevisions(
    applicationId: string,
    initialRevisions: AgentRevisionFixture[]
): MutatingRevisions {
    const entityKey = `revisions:${applicationId}`
    const [state, setState] = useState<MutatingRevisions>(() => {
        const rec = getMutationRecord(entityKey)
        if (rec) {
            return {
                revisions: listRevisionsSync(applicationId),
                revision: rec.revision,
                lastMutationId: rec.mutationId,
            }
        }
        return { revisions: initialRevisions, revision: 0, lastMutationId: null }
    })
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    useEffect(() => {
        return subscribeMutation(entityKey, (rec) => {
            if (timerRef.current) {
                clearTimeout(timerRef.current)
            }
            timerRef.current = setTimeout(() => {
                setState({
                    revisions: listRevisionsSync(applicationId),
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
