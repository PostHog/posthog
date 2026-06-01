/**
 * Agents list — the landing page.
 *
 * Layout (wide screens):
 *
 *   ┌────────────────────────────────────────────────────┐
 *   │ Header                  [ ✨ New agent with AI ]    │
 *   │ StatStrip ── 4 fleet KPIs across the top            │
 *   │ ┌──────────────────────────┐ ┌──────────────────┐  │
 *   │ │ FilterChips              │ │ Live now panel    │  │
 *   │ │ Agents list (rows)       │ │ (recent active    │  │
 *   │ │                          │ │  sessions across   │  │
 *   │ │                          │ │  the fleet)        │  │
 *   │ └──────────────────────────┘ └──────────────────┘  │
 *   └────────────────────────────────────────────────────┘
 *
 * Narrow screens stack vertically.
 *
 * Each agent row shows the same status dot/label we had before plus a
 * `N live` indicator when there are running sessions against the agent —
 * cheap real-time signal without a separate "fleet health" view.
 */

import { ChevronRightIcon } from 'lucide-react'
import { useMemo, useState } from 'react'

import type { ChatSession } from '@posthog/agent-chat'
import type { AgentApplicationFixture, FleetStats } from '@posthog/agent-chat/fixtures'

import { EditWithAIButton } from '@/components/EditWithAIButton'
import { FilterChips } from '@/components/FilterChips'
import { LiveNowPanel } from '@/components/LiveNowPanel'
import { StatStrip, type StatTile } from '@/components/StatStrip'

const FILTERS = ['all', 'live', 'drafts', 'archived'] as const
type Filter = (typeof FILTERS)[number]

export interface AgentsListProps {
    agents: AgentApplicationFixture[]
    /** Fleet rollup for the top StatStrip. */
    fleetStats: FleetStats
    /** Currently-running sessions across the fleet, newest first. */
    liveSessions: ChatSession[]
    /** Live session count per agent id — used to badge rows. */
    liveCountByAgent?: Record<string, number>
    onOpenAgent?: (slug: string) => void
    onOpenSession?: (sessionId: string) => void
    /** Hooked once the cross-agent /sessions page exists. */
    onViewAllSessions?: () => void
}

export function AgentsList({
    agents,
    fleetStats,
    liveSessions,
    liveCountByAgent = {},
    onOpenAgent,
    onOpenSession,
    onViewAllSessions,
}: AgentsListProps): React.ReactElement {
    const [filter, setFilter] = useState<Filter>('all')

    const tiles = useMemo<StatTile[]>(
        () => [
            { label: 'Agents', value: agents.length, hint: 'in this project' },
            { label: 'Live now', value: fleetStats.liveSessionCount, hint: 'sessions in flight' },
            { label: 'Sessions · 24h', value: fleetStats.sessions24hCount.toLocaleString(), hint: 'across all agents' },
            {
                label: 'Spend · 24h',
                value: `$${fleetStats.spend24hUsd.toFixed(2)}`,
                hint:
                    fleetStats.approvalsPendingCount > 0
                        ? `${fleetStats.approvalsPendingCount} approval${fleetStats.approvalsPendingCount === 1 ? '' : 's'} pending`
                        : 'rolling',
                tone: fleetStats.approvalsPendingCount > 0 ? 'attention' : 'default',
            },
        ],
        [agents.length, fleetStats]
    )

    const filteredAgents = useMemo(() => {
        switch (filter) {
            case 'live':
                return agents.filter((a) => !a.archived && (liveCountByAgent[a.id] ?? 0) > 0)
            case 'drafts':
                return agents.filter((a) => !a.archived && !a.live_revision)
            case 'archived':
                return agents.filter((a) => a.archived)
            case 'all':
            default:
                return agents.filter((a) => !a.archived)
        }
    }, [agents, filter, liveCountByAgent])

    return (
        <div className="mx-auto max-w-6xl px-6 py-6">
            <header className="mb-4 flex items-end justify-between">
                <div>
                    <h1 className="text-xl font-medium tracking-tight">Agents</h1>
                    <p className="text-sm text-muted-foreground">
                        {agents.length === 0 ? 'None yet.' : `${agents.length} in this project.`}
                    </p>
                </div>
                <EditWithAIButton prompt="Help me create a new agent." label="New agent with AI" />
            </header>

            <StatStrip tiles={tiles} className="mb-4" />

            {agents.length === 0 ? (
                <EmptyState />
            ) : (
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
                    <div className="min-w-0">
                        {/* h-8 keeps this row aligned with the LiveNow header on the right. */}
                        <div className="mb-3 flex h-8 items-center justify-between">
                            <FilterChips
                                options={FILTERS}
                                value={filter}
                                onChange={setFilter}
                                labels={{
                                    all: 'All',
                                    live: 'Live',
                                    drafts: 'Drafts',
                                    archived: 'Archived',
                                }}
                            />
                            <span className="text-[0.6875rem] text-muted-foreground">
                                {filteredAgents.length} of {agents.length}
                            </span>
                        </div>

                        {filteredAgents.length === 0 ? (
                            <NoMatches filter={filter} />
                        ) : (
                            <ul className="divide-y divide-border rounded-md border border-border bg-card">
                                {filteredAgents.map((agent) => (
                                    <li key={agent.id}>
                                        <AgentRow
                                            agent={agent}
                                            liveCount={liveCountByAgent[agent.id] ?? 0}
                                            onOpenAgent={onOpenAgent}
                                        />
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>

                    <aside className="min-w-0 lg:h-[420px]">
                        <LiveNowPanel
                            sessions={liveSessions}
                            onOpenSession={onOpenSession}
                            onOpenAgent={onOpenAgent}
                            onViewAll={onViewAllSessions}
                        />
                    </aside>
                </div>
            )}
        </div>
    )
}

function AgentRow({
    agent,
    liveCount,
    onOpenAgent,
}: {
    agent: AgentApplicationFixture
    liveCount: number
    onOpenAgent?: (slug: string) => void
}): React.ReactElement {
    const status = statusOf(agent)
    return (
        <button
            type="button"
            onClick={() => onOpenAgent?.(agent.slug)}
            className="group flex w-full cursor-pointer items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
        >
            <span className={`mt-1.5 inline-flex h-1.5 w-1.5 shrink-0 rounded-full ${status.dotClass}`} aria-hidden />
            <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                    <span className="truncate text-sm font-medium group-hover:text-foreground">{agent.name}</span>
                    <code className="truncate text-[0.6875rem] text-muted-foreground">{agent.slug}</code>
                </div>
                <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">{agent.description}</p>
            </div>
            <div className="flex shrink-0 items-center gap-3 text-[0.6875rem] text-muted-foreground">
                {liveCount > 0 ? (
                    <span className="inline-flex items-center gap-1 rounded-md bg-info/10 px-1.5 py-0.5 font-mono text-info-foreground">
                        <span
                            className="inline-flex h-1 w-1 animate-pulse rounded-full bg-info-foreground"
                            aria-hidden
                        />
                        {liveCount} live
                    </span>
                ) : null}
                <span>{status.label}</span>
                <span>·</span>
                <span>{formatRelative(agent.updated_at)}</span>
                <ChevronRightIcon className="h-3.5 w-3.5 text-muted-foreground/60 transition-all group-hover:translate-x-0.5 group-hover:text-foreground" />
            </div>
        </button>
    )
}

function EmptyState(): React.ReactElement {
    return (
        <div className="rounded-md border border-dashed border-border p-8 text-center">
            <p className="text-sm font-medium">No agents yet</p>
            <p className="mt-1 text-xs text-muted-foreground">
                Agents run on triggers and act on your data. The concierge will walk you through your first one.
            </p>
            <div className="mt-4 flex justify-center">
                <EditWithAIButton prompt="Help me create a new agent." label="New agent with AI" />
            </div>
        </div>
    )
}

function NoMatches({ filter }: { filter: Filter }): React.ReactElement {
    const message =
        filter === 'live'
            ? 'No agents have running sessions right now.'
            : filter === 'drafts'
              ? 'No drafts pending promotion.'
              : filter === 'archived'
                ? 'No archived agents.'
                : 'No matching agents.'
    return (
        <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
            {message}
        </div>
    )
}

function statusOf(agent: AgentApplicationFixture): { dotClass: string; label: string } {
    // Saturated `-foreground` variants — see notes in SessionsList.stateTone.
    if (agent.archived) {
        return { dotClass: 'bg-muted-foreground/40', label: 'Archived' }
    }
    if (agent.live_revision) {
        return { dotClass: 'bg-success-foreground', label: 'Live' }
    }
    return { dotClass: 'bg-warning-foreground', label: 'Draft' }
}

function formatRelative(iso: string): string {
    const now = Date.now()
    const then = new Date(iso).getTime()
    const diff = Math.max(0, now - then)
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
