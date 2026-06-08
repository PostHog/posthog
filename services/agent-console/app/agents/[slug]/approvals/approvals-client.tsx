'use client'

import { useMemo, useState } from 'react'

import { useAgent } from '@/components/agent-context'
import { ApprovalDetail } from '@/components/ApprovalDetail'
import { type AgentLookup, ApprovalsList } from '@/components/ApprovalsList'
import { useSetDockPage } from '@/components/dock-context'
import { useSessionTeamId } from '@/components/session-context'
import { ApiError, listAgentApprovals } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'

const POLL_MS = 10_000

export function ApprovalsSegment(): React.ReactElement {
    const agent = useAgent()
    const teamId = useSessionTeamId()!
    const [selectedId, setSelectedId] = useState<string | null>(null)

    useSetDockPage({ kind: 'agent', agent: { id: agent.id, name: agent.name, slug: agent.slug } })

    const approvals = useResource(() => listAgentApprovals(teamId, agent.slug), [teamId, agent.slug], {
        pollMs: POLL_MS,
    })

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

    const agentsById = useMemo<AgentLookup>(
        () => new Map([[agent.id, { id: agent.id, name: agent.name, slug: agent.slug }]]),
        [agent.id, agent.name, agent.slug]
    )

    const rows = approvals.data ?? []

    return (
        <div className="mx-auto flex h-full w-full max-w-5xl flex-col gap-4 px-6 pb-6 pt-4">
            {errorMessage ? (
                <div className="rounded-md border border-destructive-foreground/30 bg-destructive/10 px-3 py-2 text-xs text-destructive-foreground">
                    {errorMessage}
                </div>
            ) : null}
            {approvals.loading && rows.length === 0 ? (
                <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                    Loading approvals…
                </div>
            ) : (
                <ApprovalsList
                    approvals={rows}
                    agentsById={agentsById}
                    showAgentColumn={false}
                    selectedApprovalId={selectedId}
                    onOpenApproval={setSelectedId}
                />
            )}
            <ApprovalDetail
                approvalId={selectedId}
                agentSlug={agent.slug}
                agentName={agent.name}
                onClose={() => setSelectedId(null)}
                onDecided={() => {
                    setSelectedId(null)
                    approvals.reload()
                }}
            />
        </div>
    )
}
