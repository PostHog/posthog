/**
 * Agent detail — read panel for one agent.
 *
 * The chat dock lives in the app shell; its `@posthog/ui/focus` handler
 * navigates by pushing URL changes — this page reads its entire view
 * state from `?tab=...` and friends so deep-linking, browser back/forward,
 * and agent-driven navigation all share the same surface.
 *
 * Four tabs:
 *   - **Overview** — landing summary (stats + recent activity + trigger synopsis).
 *   - **Configuration** — app-level settings + revisions browser (master-detail).
 *   - **Sessions** — per-agent session list with filter chips.
 *   - **Memory** — file explorer over the agent's S3-backed memory store.
 *
 * URL params honored:
 *   `?tab=overview|configuration|sessions|memory`
 *   `?revision=<id>`          (configuration tab — selected revision)
 *   `?section=<spec section>` (configuration tab — highlighted spec row)
 *   `?file=<path>`            (configuration tab — selected bundle file)
 */

'use client'

import { AlertTriangleIcon, ChevronRightIcon, PlayIcon } from 'lucide-react'
import { useMemo } from 'react'

import type { ChatSession } from '@posthog/agent-chat'
import type { AgentApplicationFixture, AgentRevisionFixture, AgentStats } from '@posthog/agent-chat/fixtures'
import { Tabs, TabsContent, TabsList, TabsTrigger, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { AgentDescription } from '@/components/AgentDescription'
import { AgentOverview } from '@/components/AgentOverview'
import { ApplicationSettings } from '@/components/ApplicationSettings'
import { ConnectionsTab } from '@/components/ConnectionsTab'
import { MemoryClassic } from '@/components/MemoryClassic'
import { RevisionsBrowser } from '@/components/RevisionsBrowser'
import { SessionsList } from '@/components/SessionsList'

type TabKey = 'overview' | 'configuration' | 'connections' | 'sessions' | 'memory'

const TABS: TabKey[] = ['overview', 'configuration', 'connections', 'sessions', 'memory']

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
    onChangeUrlState: (next: Partial<AgentDetailUrlState>) => void
    onTryAgent?: (opts?: { revisionId?: string }) => void
    onOpenSession?: (sessionId: string) => void
    onBackToList?: () => void
    onRevisionsMutated?: () => void
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
    onRevisionsMutated,
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

    const liveRevisionHasChatTrigger = liveRevision ? hasChatTrigger(liveRevision.spec) : false
    const canPlayground = !!liveRevision && liveRevisionHasChatTrigger
    const playgroundDisabledReason = !liveRevision
        ? 'Promote a draft to live to enable the playground.'
        : !liveRevisionHasChatTrigger
          ? 'The live revision has no chat trigger.'
          : null

    return (
        <div className="mx-auto max-w-5xl px-6 py-6">
            <Breadcrumb name={agent.name} onBackToList={onBackToList} />

            <header className="mt-3 flex items-start justify-between gap-4">
                <div className="min-w-0 space-y-1">
                    <h1 className="text-xl font-medium tracking-tight">{agent.name}</h1>
                    <AgentDescription description={agent.description} />
                </div>
                <TryInPlaygroundButton
                    enabled={canPlayground}
                    disabledReason={playgroundDisabledReason}
                    onClick={() => onTryAgent?.()}
                />
            </header>

            {!liveRevision ? (
                <NoLiveRevisionBanner
                    hasDrafts={sortedRevisions.length > 0}
                    onOpenConfiguration={() => onChangeUrlState({ tab: 'configuration' })}
                />
            ) : !liveRevisionHasChatTrigger ? (
                <NoChatTriggerBanner onOpenConfiguration={() => onChangeUrlState({ tab: 'configuration' })} />
            ) : null}

            <Tabs value={tab} onValueChange={(v) => onChangeUrlState({ tab: v as TabKey })} className="mt-5">
                <TabsList variant="line">
                    <TabsTrigger value="overview">Overview</TabsTrigger>
                    <TabsTrigger value="configuration">Configuration</TabsTrigger>
                    <TabsTrigger value="connections">Connections</TabsTrigger>
                    <TabsTrigger value="sessions">
                        Sessions
                        {sessions.length > 0 ? (
                            <span className="ml-1.5 text-[0.6875rem] text-muted-foreground">{sessions.length}</span>
                        ) : null}
                    </TabsTrigger>
                    <TabsTrigger value="memory">Memory</TabsTrigger>
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

                <TabsContent value="configuration" className="mt-4 space-y-4">
                    <ApplicationSettings agent={agent} referenceRevision={referenceRevision} />
                    <RevisionsBrowser
                        agent={agent}
                        revisions={revisions}
                        selectedRevisionId={selectedRevId}
                        onSelectRevision={(id) => onChangeUrlState({ revisionId: id })}
                        highlightedSection={urlState.section}
                        focusedBundlePath={urlState.filePath}
                        onSelectBundleFile={(path) => onChangeUrlState({ filePath: path })}
                        onMutated={onRevisionsMutated}
                        onTryDraft={(revisionId) => onTryAgent?.({ revisionId })}
                    />
                </TabsContent>

                <TabsContent value="connections" className="mt-4">
                    <ConnectionsTab agent={agent} revisions={revisions} />
                </TabsContent>

                <TabsContent value="sessions" className="mt-4">
                    <SessionsList sessions={sessions} onOpenSession={onOpenSession} />
                </TabsContent>

                <TabsContent value="memory" className="mt-4">
                    <MemoryClassic slug={agent.slug} />
                </TabsContent>
            </Tabs>
        </div>
    )
}

/* ── Sub-components ─────────────────────────────────────────────── */

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
    onOpenConfiguration,
}: {
    hasDrafts: boolean
    onOpenConfiguration: () => void
}): React.ReactElement {
    return (
        <div className="mt-4 flex items-start gap-2 rounded-md border border-warning-foreground/30 bg-warning/40 px-3 py-2 text-xs">
            <AlertTriangleIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning-foreground" />
            <div className="space-y-0.5">
                <p className="font-medium text-foreground">No live revision yet</p>
                <p className="text-muted-foreground">
                    The playground stays disabled until a revision is promoted to live.{' '}
                    {hasDrafts ? (
                        <button
                            type="button"
                            onClick={onOpenConfiguration}
                            className="cursor-pointer text-foreground underline-offset-2 hover:underline"
                        >
                            Promote a revision
                        </button>
                    ) : (
                        <span>Push a bundle from the agent runner to create a draft.</span>
                    )}
                </p>
            </div>
        </div>
    )
}

function NoChatTriggerBanner({ onOpenConfiguration }: { onOpenConfiguration: () => void }): React.ReactElement {
    return (
        <div className="mt-4 flex items-start gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs">
            <AlertTriangleIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <div className="space-y-0.5">
                <p className="font-medium text-foreground">No chat trigger on live revision</p>
                <p className="text-muted-foreground">
                    This agent runs without an interactive surface — the playground can't reach it.{' '}
                    <button
                        type="button"
                        onClick={onOpenConfiguration}
                        className="cursor-pointer text-foreground underline-offset-2 hover:underline"
                    >
                        View configuration
                    </button>
                </p>
            </div>
        </div>
    )
}

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
