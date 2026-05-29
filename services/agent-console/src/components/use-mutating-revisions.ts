/**
 * `useMutatingRevisions` — subscribes to the per-app `revisions:<id>`
 * entity revision and re-reads via mockApi's overlay whenever a
 * revision-spec mutation lands. Mirrors `useMutatingBundle` for the
 * other half of the agent-detail data.
 */

'use client'

import { useEffect, useState } from 'react'

import type { AgentRevisionFixture } from '@posthog/agent-chat/fixtures'

import { getMutationRecord, listRevisionsSync, subscribeMutation } from '@/lib/mockApi'

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

    useEffect(() => {
        return subscribeMutation(entityKey, (rec) => {
            setState({
                revisions: listRevisionsSync(applicationId),
                revision: rec.revision,
                lastMutationId: rec.mutationId,
            })
        })
    }, [applicationId, entityKey])

    return state
}
