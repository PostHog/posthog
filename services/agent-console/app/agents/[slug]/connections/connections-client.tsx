'use client'

import { useRouter, useSearchParams } from 'next/navigation'
import { useCallback } from 'react'

import { useAgent, useRevisions } from '@/components/agent-context'
import { ConnectionsTab } from '@/components/ConnectionsTab'

export function ConnectionsSegment(): React.ReactElement {
    const agent = useAgent()
    const revisions = useRevisions()
    const router = useRouter()
    const searchParams = useSearchParams()
    const editSecret = searchParams?.get('edit_secret') ?? null
    const callbackSessionId = searchParams?.get('callback_session') ?? null

    // Writer scoped to this segment — only touches edit_secret + the
    // callback. Anything else in the query string is preserved (today
    // there's nothing else on this route, but the merge keeps that
    // future-proof).
    const setEditingSecret = useCallback(
        (key: string | null) => {
            const params = new URLSearchParams(searchParams?.toString() ?? '')
            if (key) {
                params.set('edit_secret', key)
            } else {
                params.delete('edit_secret')
                // When the editor closes, the callback target is no
                // longer relevant.
                params.delete('callback_session')
            }
            const qs = params.toString()
            router.push(`/agents/${agent.slug}/connections${qs ? `?${qs}` : ''}`, { scroll: false })
        },
        [agent.slug, router, searchParams]
    )

    return (
        <div className="mx-auto h-full max-w-5xl overflow-y-auto px-6 pb-6 pt-4">
            <ConnectionsTab
                agent={agent}
                revisions={revisions}
                editingSecret={editSecret}
                callbackSessionId={callbackSessionId}
                onChangeEditingSecret={setEditingSecret}
            />
        </div>
    )
}
