/**
 * `<Approvals />` — fleet-wide approval inbox.
 *
 * Pure presentation: receives the list + agent lookup + drawer state from
 * the route client. Renders the page chrome and embeds `<ApprovalsList>`
 * + `<ApprovalDetail>`.
 */

import { useMemo, useState } from 'react'

import type { AgentApplicationFixture } from '@posthog/agent-chat/fixtures'

import { ApprovalDetail } from '@/components/ApprovalDetail'
import { type AgentLookup, ApprovalsList } from '@/components/ApprovalsList'
import type { ApprovalRequest } from '@/lib/apiClient'

export interface ApprovalsProps {
    approvals: ApprovalRequest[]
    agents: AgentApplicationFixture[]
    /** `true` while the first fetch is in flight — skeleton placeholder. */
    loading: boolean
    /** Surface auth / server failures. */
    error: string | null
    /** Caller refetches the list after a successful decision. */
    onReload: () => void
}

export function Approvals({ approvals, agents, loading, error, onReload }: ApprovalsProps): React.ReactElement {
    const [selectedId, setSelectedId] = useState<string | null>(null)

    const agentsById = useMemo<AgentLookup>(() => {
        const m = new Map<string, { id: string; name: string; slug: string }>()
        for (const a of agents) {
            m.set(a.id, { id: a.id, name: a.name, slug: a.slug })
        }
        return m
    }, [agents])

    const selected = useMemo(
        () => (selectedId ? (approvals.find((a) => a.id === selectedId) ?? null) : null),
        [approvals, selectedId]
    )
    const selectedAgent = selected ? (agentsById.get(selected.application_id) ?? null) : null

    return (
        <div className="mx-auto flex h-full w-full max-w-5xl flex-col gap-4 px-6 py-6">
            <header className="flex items-end justify-between">
                <div>
                    <h1 className="text-xl font-medium tracking-tight">Approvals</h1>
                    <p className="text-sm text-muted-foreground">
                        Approval-gated tool calls across every agent in this project. Admin only.
                    </p>
                </div>
            </header>

            {error ? (
                <div className="rounded-md border border-destructive-foreground/30 bg-destructive/10 px-3 py-2 text-xs text-destructive-foreground">
                    {error}
                </div>
            ) : null}

            {loading && approvals.length === 0 ? (
                <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                    Loading approvals…
                </div>
            ) : (
                <ApprovalsList
                    approvals={approvals}
                    agentsById={agentsById}
                    showAgentColumn
                    selectedApprovalId={selectedId}
                    onOpenApproval={setSelectedId}
                />
            )}

            <ApprovalDetail
                approvalId={selectedId}
                agentSlug={selectedAgent?.slug ?? null}
                agentName={selectedAgent?.name ?? null}
                onClose={() => setSelectedId(null)}
                onDecided={() => {
                    setSelectedId(null)
                    onReload()
                }}
            />
        </div>
    )
}
