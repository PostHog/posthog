/**
 * `<AgentLayout>` — shared chrome for the `/agents/[slug]/*` segments.
 *
 * Renders the breadcrumb, agent header, "Try in playground" button,
 * any global banners (no live revision, no chat trigger), and the tab
 * strip. The tab strip is `<Link>`-based: clicking a tab is a Next.js
 * soft navigation to the segment, no setState, no full reload.
 *
 * Children are the active segment's content. The component itself is
 * mounted by `[slug]/layout.tsx` and stays alive across tab changes —
 * only `{children}` swaps.
 */

'use client'

import { AlertTriangleIcon, ChevronRightIcon, PlayIcon } from 'lucide-react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect, useMemo } from 'react'

import { Tabs, TabsList, TabsTrigger, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { useAgent, useRevisions } from '@/components/agent-context'
import { AgentDescription } from '@/components/AgentDescription'
import { useDockStore } from '@/components/dock-context'
import { EditWithAIButton } from '@/components/EditWithAIButton'
import { useSessionTeamId } from '@/components/session-context'
import { listAgentApprovals, listMemoryFiles, listSessionsForAgent } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'

const TABS = ['overview', 'configuration', 'connections', 'sessions', 'approvals', 'memory'] as const
type TabKey = (typeof TABS)[number]

interface TabDef {
    key: TabKey
    label: string
    /** Path relative to `/agents/<slug>` — empty string for the index. */
    path: string
}

const TAB_DEFS: TabDef[] = [
    { key: 'overview', label: 'Overview', path: '' },
    { key: 'configuration', label: 'Configuration', path: '/configuration' },
    { key: 'connections', label: 'Connections', path: '/connections' },
    { key: 'sessions', label: 'Sessions', path: '/sessions' },
    { key: 'approvals', label: 'Approvals', path: '/approvals' },
    { key: 'memory', label: 'Memory', path: '/memory' },
]

const TAB_COUNT_POLL_MS = 30_000

export function AgentLayout({ children }: { children: React.ReactNode }): React.ReactElement {
    const agent = useAgent()
    const revisions = useRevisions()
    const router = useRouter()
    const pathname = usePathname() ?? ''
    const { enterPlayground } = useDockStore()
    const teamId = useSessionTeamId()
    const tabCounts = useTabCounts(teamId, agent)

    const sortedRevisions = useMemo(
        () => [...revisions].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()),
        [revisions]
    )
    const liveRevision = revisions.find((r) => r.id === agent.live_revision) ?? null
    const liveRevisionHasChatTrigger = liveRevision ? hasChatTrigger(liveRevision.spec) : false
    const canPlayground = !!liveRevision && liveRevisionHasChatTrigger
    const playgroundDisabledReason = !liveRevision
        ? 'Promote a draft to live to enable the playground.'
        : !liveRevisionHasChatTrigger
          ? 'The live revision has no chat trigger.'
          : null

    const activeTab = activeTabFor(pathname, agent.slug)
    const agentRef = { id: agent.id, slug: agent.slug, name: agent.name }

    // Warm the route cache for every tab on mount so a click is a
    // pre-loaded soft navigation (matches the perf of `<Link>` which
    // prefetches automatically). The Tabs trigger is a Button, not a
    // link, so we have to prefetch explicitly.
    useEffect(() => {
        for (const t of TAB_DEFS) {
            router.prefetch(`/agents/${agent.slug}${t.path}`)
        }
    }, [agent.slug, router])

    return (
        <div className="flex h-full min-h-0 flex-col">
            <div className="mx-auto w-full max-w-5xl shrink-0 px-6 pt-6">
                <Breadcrumb name={agent.name} onBack={() => router.push('/agents')} />

                <header className="mt-3 flex items-start justify-between gap-4">
                    <div className="min-w-0 space-y-1">
                        <h1 className="text-xl font-medium tracking-tight">{agent.name}</h1>
                        <AgentDescription description={agent.description} />
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                        <EditWithAIButton prompt={`Help me edit the \`${agent.slug}\` agent.`} agentSlug={agent.slug} />
                        <TryInPlaygroundButton
                            enabled={canPlayground}
                            disabledReason={playgroundDisabledReason}
                            onClick={() => enterPlayground(agentRef)}
                        />
                    </div>
                </header>

                {!liveRevision ? (
                    <NoLiveRevisionBanner
                        hasDrafts={sortedRevisions.length > 0}
                        configurationHref={`/agents/${agent.slug}/configuration`}
                    />
                ) : !liveRevisionHasChatTrigger ? (
                    <NoChatTriggerBanner configurationHref={`/agents/${agent.slug}/configuration`} />
                ) : null}
            </div>

            <Tabs
                value={activeTab}
                onValueChange={(v) => {
                    const next = TAB_DEFS.find((t) => t.key === v)
                    if (!next) {
                        return
                    }
                    router.push(`/agents/${agent.slug}${next.path}`, { scroll: false })
                }}
                className="mt-5 flex min-h-0 flex-1 flex-col"
            >
                <div className="shrink-0 border-b border-border">
                    <div className="mx-auto w-full max-w-5xl px-6">
                        <TabsList variant="line">
                            {TAB_DEFS.map((t) => {
                                const count = tabCounts[t.key]
                                return (
                                    <TabsTrigger key={t.key} value={t.key}>
                                        <span className="inline-flex items-center gap-1.5">
                                            {t.label}
                                            {count != null && count > 0 ? (
                                                <span
                                                    className="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-muted px-1 font-mono text-[0.625rem] font-medium text-muted-foreground"
                                                    aria-label={`${count} ${t.label.toLowerCase()}`}
                                                >
                                                    {count > 99 ? '99+' : count}
                                                </span>
                                            ) : null}
                                        </span>
                                    </TabsTrigger>
                                )
                            })}
                        </TabsList>
                    </div>
                </div>
                <div className="min-h-0 flex-1">{children}</div>
            </Tabs>
        </div>
    )
}

type TabCounts = Partial<Record<TabKey, number>>

/**
 * Background-polls the data behind each tab and exposes counts so the
 * tab strip can render small badges. Returns `null` for any tab whose
 * data hasn't loaded yet (badge renders nothing rather than 0).
 *
 * Approvals counts only `queued` + `approving` — terminal states
 * (dispatched / rejected / expired) aren't actionable so they'd be
 * noise on the badge. Sessions/Memory are total counts since both
 * tabs show their full set.
 */
function useTabCounts(teamId: number | null, agent: { id: string; slug: string; name: string }): TabCounts {
    const sessions = useResource(
        () => {
            if (teamId == null) {
                return Promise.resolve(null)
            }
            return listSessionsForAgent(teamId, agent.slug, agent).catch(() => null)
        },
        [teamId, agent.slug, agent.id, agent.name],
        { pollMs: TAB_COUNT_POLL_MS }
    )
    const memory = useResource(
        () => {
            if (teamId == null) {
                return Promise.resolve(null)
            }
            return listMemoryFiles(teamId, agent.slug).catch(() => null)
        },
        [teamId, agent.slug],
        { pollMs: TAB_COUNT_POLL_MS }
    )
    const approvals = useResource(
        () => {
            if (teamId == null) {
                return Promise.resolve(null)
            }
            return listAgentApprovals(teamId, agent.slug, { state: ['queued', 'approving'] }).catch(() => null)
        },
        [teamId, agent.slug],
        { pollMs: TAB_COUNT_POLL_MS }
    )
    return useMemo(
        () => ({
            sessions: sessions.data ? sessions.data.length : undefined,
            memory: memory.data ? memory.data.count : undefined,
            approvals: approvals.data ? approvals.data.length : undefined,
        }),
        [sessions.data, memory.data, approvals.data]
    )
}

/**
 * Map a pathname under `/agents/[slug]` to its active tab. Anything
 * unknown falls back to overview so the indicator never disappears.
 */
function activeTabFor(pathname: string, slug: string): TabKey {
    const base = `/agents/${encodeURIComponent(slug)}`
    const tail = pathname.startsWith(base) ? pathname.slice(base.length) : ''
    const first = tail.split('/').filter(Boolean)[0]
    if (!first) {
        return 'overview'
    }
    return (TABS as readonly string[]).includes(first) ? (first as TabKey) : 'overview'
}

function hasChatTrigger(spec: Record<string, unknown>): boolean {
    const triggers = spec.triggers
    if (!Array.isArray(triggers)) {
        return false
    }
    return triggers.some((t) => typeof t === 'object' && t !== null && (t as { type?: unknown }).type === 'chat')
}

function TryInPlaygroundButton({
    enabled,
    disabledReason,
    onClick,
}: {
    enabled: boolean
    disabledReason: string | null
    onClick: () => void
}): React.ReactElement {
    const button = (
        <button
            type="button"
            onClick={enabled ? onClick : undefined}
            disabled={!enabled}
            className={
                'inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-xs font-medium transition-colors ' +
                (enabled
                    ? 'cursor-pointer hover:bg-accent'
                    : 'cursor-not-allowed text-muted-foreground opacity-60 hover:bg-card')
            }
        >
            <PlayIcon className="h-3 w-3" />
            Try in playground
        </button>
    )
    if (enabled || !disabledReason) {
        return button
    }
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="inline-flex" />}>{button}</TooltipTrigger>
            <TooltipContent side="bottom">{disabledReason}</TooltipContent>
        </Tooltip>
    )
}

function NoLiveRevisionBanner({
    hasDrafts,
    configurationHref,
}: {
    hasDrafts: boolean
    configurationHref: string
}): React.ReactElement {
    return (
        <div className="mt-4 flex items-start gap-2 rounded-md border border-warning-foreground/30 bg-warning/40 px-3 py-2 text-xs">
            <AlertTriangleIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning-foreground" />
            <div className="space-y-0.5">
                <p className="font-medium text-foreground">No live revision yet</p>
                <p className="text-muted-foreground">
                    The playground stays disabled until a revision is promoted to live.{' '}
                    {hasDrafts ? (
                        <Link
                            href={configurationHref}
                            scroll={false}
                            className="cursor-pointer text-foreground underline-offset-2 hover:underline"
                        >
                            Promote a revision
                        </Link>
                    ) : (
                        <span>Push a bundle from the agent runner to create a draft.</span>
                    )}
                </p>
            </div>
        </div>
    )
}

function NoChatTriggerBanner({ configurationHref }: { configurationHref: string }): React.ReactElement {
    return (
        <div className="mt-4 flex items-start gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs">
            <AlertTriangleIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <div className="space-y-0.5">
                <p className="font-medium text-foreground">No chat trigger on live revision</p>
                <p className="text-muted-foreground">
                    This agent runs without an interactive surface — the playground can't reach it.{' '}
                    <Link
                        href={configurationHref}
                        scroll={false}
                        className="cursor-pointer text-foreground underline-offset-2 hover:underline"
                    >
                        View configuration
                    </Link>
                </p>
            </div>
        </div>
    )
}

function Breadcrumb({ name, onBack }: { name: string; onBack: () => void }): React.ReactElement {
    return (
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <button type="button" onClick={onBack} className="cursor-pointer hover:text-foreground">
                Agents
            </button>
            <ChevronRightIcon className="h-3 w-3" />
            <span className="text-foreground">{name}</span>
        </div>
    )
}
