/**
 * Agent detail — read panel for one agent. The chat dock lives in the
 * app shell; its `@posthog/ui/focus` handler navigates by pushing URL
 * changes — this page reads its entire view state from `?tab=...` and
 * friends so deep-linking, browser back/forward, and agent-driven
 * navigation all share the same surface.
 *
 * Three tabs:
 *   - **Overview** — landing summary (stats + recent activity + trigger synopsis).
 *   - **Configuration** — app-level settings + revisions browser (master-detail).
 *   - **Sessions** — per-agent session list with filter chips.
 *
 * URL params honored:
 *   `?tab=overview|configuration|sessions`
 *   `?revision=<id>`          (configuration tab — selected revision)
 *   `?section=<spec section>` (configuration tab — highlighted spec row)
 *   `?file=<path>`            (configuration tab — selected bundle file)
 */

'use client'

import { ChevronRightIcon, PlayIcon } from 'lucide-react'
import { useMemo } from 'react'

import type { ChatSession } from '@posthog/agent-chat'
import type { AgentApplicationFixture, AgentRevisionFixture, AgentStats } from '@posthog/agent-chat/fixtures'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@posthog/quill'

import { AgentOverview } from '@/components/AgentOverview'
import { ApplicationSettings } from '@/components/ApplicationSettings'
import { RevisionsBrowser } from '@/components/RevisionsBrowser'
import { SessionsList } from '@/components/SessionsList'

type TabKey = 'overview' | 'configuration' | 'sessions'

const TABS: TabKey[] = ['overview', 'configuration', 'sessions']

export type AgentDetailUrlState = {
    tab: TabKey
    revisionId: string | null
    section: 'triggers' | 'tools' | 'skills' | 'secrets' | 'limits' | null
    filePath: string | null
}

export function parseUrlState(searchParams: URLSearchParams, defaultRevisionId: string | null): AgentDetailUrlState {
    const tabParam = searchParams.get('tab')
    const tab: TabKey = TABS.includes(tabParam as TabKey) ? (tabParam as TabKey) : 'overview'
    const revisionId = searchParams.get('revision') ?? defaultRevisionId
    const sectionParam = searchParams.get('section')
    const section =
        sectionParam === 'triggers' ||
        sectionParam === 'tools' ||
        sectionParam === 'skills' ||
        sectionParam === 'secrets' ||
        sectionParam === 'limits'
            ? sectionParam
            : null
    const filePath = searchParams.get('file')
    return { tab, revisionId, section, filePath }
}

export interface AgentDetailProps {
    agent: AgentApplicationFixture
    revisions: AgentRevisionFixture[]
    stats: AgentStats
    sessions: ChatSession[]
    urlState: AgentDetailUrlState
    /**
     * Push a URL-state change. Implementations wrap `router.push(...)`
     * but the page doesn't know about Next.js — the wrapper handles
     * serializing the partial state onto whichever route owns the agent.
     */
    onChangeUrlState: (next: Partial<AgentDetailUrlState>) => void
    onTryAgent?: () => void
    onOpenSession?: (sessionId: string) => void
    onBackToList?: () => void
}

export function AgentDetail({
    agent,
    revisions,
    stats,
    sessions,
    urlState,
    onChangeUrlState,
    onTryAgent,
    onOpenSession,
    onBackToList,
}: AgentDetailProps): React.ReactElement {
    const sortedRevisions = useMemo(
        () => [...revisions].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()),
        [revisions]
    )
    const defaultRevisionId = agent.live_revision ?? sortedRevisions[0]?.id ?? null
    const liveRevision = revisions.find((r) => r.id === agent.live_revision) ?? null
    const referenceRevision = liveRevision ?? sortedRevisions[0] ?? null
    const recentSessions = useMemo(() => sessions.slice(0, 5), [sessions])

    const tab = urlState.tab
    const selectedRevId = urlState.revisionId ?? defaultRevisionId

    return (
        <div className="mx-auto max-w-5xl px-6 py-6">
            <Breadcrumb name={agent.name} onBackToList={onBackToList} />

            <header className="mt-3 flex items-start justify-between gap-4">
                <div className="min-w-0 space-y-1">
                    <h1 className="text-xl font-medium tracking-tight">{agent.name}</h1>
                    <p className="text-sm text-muted-foreground">{agent.description}</p>
                </div>
                <button
                    type="button"
                    onClick={() => onTryAgent?.()}
                    className="inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-md border border-border bg-background px-3 text-xs font-medium transition-colors hover:bg-accent"
                >
                    <PlayIcon className="h-3 w-3" />
                    Try in playground
                </button>
            </header>

            <Tabs value={tab} onValueChange={(v) => onChangeUrlState({ tab: v as TabKey })} className="mt-5">
                <TabsList variant="line">
                    <TabsTrigger value="overview">Overview</TabsTrigger>
                    <TabsTrigger value="configuration">Configuration</TabsTrigger>
                    <TabsTrigger value="sessions">
                        Sessions
                        {sessions.length > 0 ? (
                            <span className="ml-1.5 text-[0.6875rem] text-muted-foreground">{sessions.length}</span>
                        ) : null}
                    </TabsTrigger>
                </TabsList>

                <TabsContent value="overview" className="mt-4">
                    <AgentOverview
                        agent={agent}
                        liveRevision={liveRevision}
                        stats={stats}
                        recentSessions={recentSessions}
                        onOpenSession={onOpenSession}
                        onOpenConfiguration={() => onChangeUrlState({ tab: 'configuration' })}
                        onOpenSessions={() => onChangeUrlState({ tab: 'sessions' })}
                    />
                </TabsContent>

                <TabsContent value="configuration" className="mt-4 space-y-6">
                    <Section title="Settings">
                        <ApplicationSettings agent={agent} referenceRevision={referenceRevision} />
                    </Section>

                    <Section
                        title="Revisions"
                        right={
                            revisions.length > 0 ? (
                                <span className="text-[0.6875rem] text-muted-foreground">{revisions.length} total</span>
                            ) : null
                        }
                    >
                        <RevisionsBrowser
                            agent={agent}
                            revisions={revisions}
                            selectedRevisionId={selectedRevId}
                            onSelectRevision={(id) => onChangeUrlState({ revisionId: id })}
                            highlightedSection={urlState.section}
                            focusedBundlePath={urlState.filePath}
                            onSelectBundleFile={(path) => onChangeUrlState({ filePath: path })}
                        />
                    </Section>
                </TabsContent>

                <TabsContent value="sessions" className="mt-4">
                    <SessionsList sessions={sessions} onOpenSession={onOpenSession} />
                </TabsContent>
            </Tabs>
        </div>
    )
}

/* ── Sub-components ─────────────────────────────────────────────── */

function Breadcrumb({ name, onBackToList }: { name: string; onBackToList?: () => void }): React.ReactElement {
    return (
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
            {onBackToList ? (
                <button type="button" onClick={onBackToList} className="cursor-pointer hover:text-foreground">
                    Agents
                </button>
            ) : (
                <span>Agents</span>
            )}
            <ChevronRightIcon className="h-3 w-3" />
            <span className="text-foreground">{name}</span>
        </div>
    )
}

function Section({
    title,
    right,
    children,
}: {
    title: string
    right?: React.ReactNode
    children: React.ReactNode
}): React.ReactElement {
    return (
        <section className="space-y-3">
            <div className="flex h-7 items-end justify-between">
                <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h2>
                {right ? <div>{right}</div> : null}
            </div>
            {children}
        </section>
    )
}
