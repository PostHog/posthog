'use client'

import { useMemo } from 'react'

import { useSetDockPage } from '@/components/dock-context'
import { useSessionTeamId } from '@/components/session-context'
import { ApiError, listAgents, listFleetApprovals } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'
import { Approvals } from '@/screens/Approvals'

const POLL_MS = 10_000

export function ApprovalsClient(): React.ReactElement {
    const teamId = useSessionTeamId()!

    useSetDockPage({ kind: 'agent-list' })

    const approvals = useResource(() => listFleetApprovals(teamId).catch(toApiError), [teamId], { pollMs: POLL_MS })
    const agents = useResource(() => listAgents(teamId).catch(() => []), [teamId])

    const errorMessage = useMemo(() => {
        const e = approvals.error
        if (!e) {
            return null
        }
        if (e instanceof ApiError && e.status === 404) {
            return "Approvals are admin-only — your account doesn't have admin scope on this project."
        }
        return e.message
    }, [approvals.error])

    return (
        <Approvals
            approvals={approvals.data ?? []}
            agents={agents.data ?? []}
            loading={approvals.loading}
            error={errorMessage}
            onReload={approvals.reload}
        />
    )
}

/** Re-throw so `useResource` surfaces the structured error. */
function toApiError(err: unknown): never {
    throw err instanceof Error ? err : new Error(String(err))
}
