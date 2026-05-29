/**
 * Revisions tab — timeline list of all revisions for an agent.
 *
 * Live revision is pinned at top with a clear visual marker.
 * Drafts and ready revisions follow, sorted newest-first.
 *
 * Each row links into the Configuration tab, scoped to that revision —
 * so reviewing a draft and promoting it both flow naturally.
 */

import { ChevronRightIcon } from 'lucide-react'
import { useMemo } from 'react'

import type { AgentApplicationFixture, AgentRevisionFixture } from '@posthog/agent-chat/fixtures'

export interface RevisionsListProps {
    agent: AgentApplicationFixture
    revisions: AgentRevisionFixture[]
    onOpenInConfig?: (revisionId: string) => void
}

export function RevisionsList({ agent, revisions, onOpenInConfig }: RevisionsListProps): React.ReactElement {
    const sorted = useMemo(() => {
        const live = revisions.find((r) => r.id === agent.live_revision)
        const others = revisions.filter((r) => r.id !== agent.live_revision)
        others.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
        return live ? [live, ...others] : others
    }, [revisions, agent.live_revision])

    if (sorted.length === 0) {
        return (
            <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                This agent has no revisions yet.
            </div>
        )
    }

    return (
        <div className="space-y-3">
            <div className="flex items-center justify-between text-xs">
                <p className="text-muted-foreground">
                    {sorted.length} revision{sorted.length === 1 ? '' : 's'} — live is pinned at top.
                </p>
            </div>
            <ul className="divide-y divide-border rounded-md border border-border bg-card">
                {sorted.map((r) => {
                    const isLive = r.id === agent.live_revision
                    return (
                        <li key={r.id}>
                            <RevisionRow revision={r} live={isLive} onClick={() => onOpenInConfig?.(r.id)} />
                        </li>
                    )
                })}
            </ul>
        </div>
    )
}

function RevisionRow({
    revision,
    live,
    onClick,
}: {
    revision: AgentRevisionFixture
    live: boolean
    onClick?: () => void
}): React.ReactElement {
    const tone = stateTone(revision.state, live)
    return (
        <button
            type="button"
            onClick={onClick}
            className="group flex w-full cursor-pointer items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
        >
            <span className={`mt-1.5 inline-flex h-1.5 w-1.5 shrink-0 rounded-full ${tone.dotClass}`} aria-hidden />
            <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2 text-sm">
                    <span className="font-medium">{tone.label}</span>
                    <code className="truncate text-[0.6875rem] text-muted-foreground">{short(revision.id)}</code>
                    {revision.bundle_sha256 ? (
                        <code className="truncate text-[0.6875rem] text-muted-foreground/70">
                            {revision.bundle_sha256.split(':').at(-1)?.slice(0, 8)}
                        </code>
                    ) : null}
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-[0.6875rem] text-muted-foreground">
                    <span>by {revision.created_by.first_name}</span>
                    <span>·</span>
                    <span>created {formatRelative(revision.created_at)}</span>
                    {revision.updated_at !== revision.created_at ? (
                        <>
                            <span>·</span>
                            <span>updated {formatRelative(revision.updated_at)}</span>
                        </>
                    ) : null}
                </div>
            </div>
            <span className="shrink-0 text-[0.6875rem] text-muted-foreground transition-colors group-hover:text-foreground">
                Open in config
            </span>
            <ChevronRightIcon className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60 transition-all group-hover:translate-x-0.5 group-hover:text-foreground" />
        </button>
    )
}

function stateTone(state: AgentRevisionFixture['state'], live: boolean): { dotClass: string; label: string } {
    if (live) {
        return { dotClass: 'bg-success', label: 'live' }
    }
    switch (state) {
        case 'draft':
            return { dotClass: 'bg-warning', label: 'draft' }
        case 'ready':
            return { dotClass: 'bg-info', label: 'ready' }
        case 'archived':
            return { dotClass: 'bg-muted-foreground/40', label: 'archived' }
        case 'live':
            return { dotClass: 'bg-success', label: 'live' }
        default:
            return { dotClass: 'bg-muted-foreground/40', label: state }
    }
}

function short(id: string): string {
    return id.split('-').at(-1)?.slice(0, 8) ?? id.slice(0, 8)
}

function formatRelative(iso: string): string {
    const ts = new Date(iso).getTime()
    if (!ts) {
        return '—'
    }
    const diff = Math.max(0, Date.now() - ts)
    const minute = 60 * 1000
    const hour = 60 * minute
    const day = 24 * hour
    if (diff < hour) {
        return `${Math.max(1, Math.floor(diff / minute))}m ago`
    }
    if (diff < day) {
        return `${Math.floor(diff / hour)}h ago`
    }
    return `${Math.floor(diff / day)}d ago`
}
