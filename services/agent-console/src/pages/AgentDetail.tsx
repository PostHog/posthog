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
 *   - **Sessions** — master-detail; list on the left, selected session on the
 *     right (driven by `?session=<id>`), pinned to viewport height.
 *   - **Memory** — file explorer over the agent's S3-backed memory store.
 *
 * URL params honored:
 *   `?tab=overview|configuration|connections|sessions|memory`
 *   `?revision=<id>`          (configuration tab — selected revision)
 *   `?section=<spec section>` (configuration tab — highlighted spec row)
 *   `?file=<path>`            (configuration tab — selected bundle file)
 *   `?edit_secret=<KEY>`      (connections tab — open the editor for a key)
 *   `?callback_session=<id>`  (connections tab — notify this chat session
 *                              via a window event after a save / clear; the
 *                              dock's runner picks it up and resumes the agent)
 *   `?session=<id>`           (sessions tab — selected session)
 */

'use client'

import { AlertTriangleIcon, ChevronRightIcon, PlayIcon } from 'lucide-react'
import { useMemo } from 'react'

import type { ChatSession } from '@posthog/agent-chat'
import type { AgentApplicationFixture, AgentRevisionFixture, AgentStats, LogEntry } from '@posthog/agent-chat/fixtures'
import { Tabs, TabsContent, TabsList, TabsTrigger, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { AgentDescription } from '@/components/AgentDescription'
import { AgentOverview } from '@/components/AgentOverview'
import { ConnectionsTab } from '@/components/ConnectionsTab'
import { MemoryClassic } from '@/components/MemoryClassic'
import { RevisionsBrowser } from '@/components/RevisionsBrowser'
import { SessionsList } from '@/components/SessionsList'
import { SessionDetail } from '@/pages/SessionDetail'

type TabKey = 'overview' | 'configuration' | 'connections' | 'sessions' | 'memory'

const TABS: TabKey[] = ['overview', 'configuration', 'connections', 'sessions', 'memory']

export type AgentDetailUrlState = {
    tab: TabKey
    revisionId: string | null
    section: 'triggers' | 'tools' | 'skills' | 'secrets' | 'limits' | null
    filePath: string | null
    /**
     * Name of a secret to open the editor for. Lives on the connections
     * tab. When set without `tab=connections` we still snap the tab — a
     * deep link is allowed to be terse.
     */
    editSecret: string | null
    /**
     * Optional chat session id to notify on save / clear. Pure
     * carry-through param — `parseUrlState` doesn't validate the id
     * shape because the dock owns session lookups.
     */
    callbackSessionId: string | null
    /**
     * Selected session for the master-detail view on the sessions tab.
     * When set we snap to `tab=sessions` so a deep link like `?session=…`
     * lands somewhere useful.
     */
    selectedSessionId: string | null
}

export function parseUrlState(searchParams: URLSearchParams, defaultRevisionId: string | null): AgentDetailUrlState {
    const tabParam = searchParams.get('tab')
    const editSecret = searchParams.get('edit_secret')
    const callbackSessionId = searchParams.get('callback_session')
    const selectedSessionId = searchParams.get('session')
    // edit_secret implies the connections tab; ?session= implies the
    // sessions tab — the URL contracts for the concierge's deep links
    // are just `?edit_secret=KEY` and `?session=<id>`.
    const tab: TabKey = editSecret
        ? 'connections'
        : selectedSessionId
          ? 'sessions'
          : TABS.includes(tabParam as TabKey)
            ? (tabParam as TabKey)
            : 'overview'
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
    return { tab, revisionId, section, filePath, editSecret, callbackSessionId, selectedSessionId }
}

export interface AgentDetailProps {
    agent: AgentApplicationFixture
    revisions: AgentRevisionFixture[]
    stats: AgentStats
    sessions: ChatSession[]
    /** Fetched detail for `urlState.selectedSessionId`. `null` while loading or unset. */
    selectedSession: ChatSession | null
    /** Logs for the selected session — best-effort, may be empty. */
    selectedSessionLogs: LogEntry[]
    /** Loading state for the selected-session fetch — drives the right pane's skeleton. */
    selectedSessionLoading: boolean
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
    selectedSession,
    selectedSessionLogs,
    selectedSessionLoading,
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
        <div className="flex h-full min-h-0 flex-col">
            <div className="mx-auto w-full max-w-5xl shrink-0 px-6 pt-6">
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
            </div>

            <Tabs
                value={tab}
                onValueChange={(v) => onChangeUrlState({ tab: v as TabKey })}
                className="mt-5 flex min-h-0 flex-1 flex-col"
            >
                <div className="mx-auto w-full max-w-5xl shrink-0 px-6">
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
                </div>

                <TabsContent value="overview" className="min-h-0 flex-1 overflow-y-auto">
                    <div className="mx-auto max-w-5xl px-6 pb-6 pt-4">
                        <AgentOverview
                            agent={agent}
                            liveRevision={liveRevision}
                            stats={stats}
                            recentSessions={recentSessions}
                            onOpenSession={onOpenSession}
                            onOpenConfiguration={() => onChangeUrlState({ tab: 'configuration' })}
                            onOpenSessions={() => onChangeUrlState({ tab: 'sessions' })}
                        />
                    </div>
                </TabsContent>

                <TabsContent value="configuration" className="min-h-0 flex-1 overflow-y-auto">
                    <div className="mx-auto max-w-5xl space-y-4 px-6 pb-6 pt-4">
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
                    </div>
                </TabsContent>

                <TabsContent value="connections" className="min-h-0 flex-1 overflow-y-auto">
                    <div className="mx-auto max-w-5xl px-6 pb-6 pt-4">
                        <ConnectionsTab
                            agent={agent}
                            revisions={revisions}
                            editingSecret={urlState.editSecret}
                            callbackSessionId={urlState.callbackSessionId}
                            onChangeEditingSecret={(key) =>
                                onChangeUrlState(
                                    key ? { editSecret: key } : { editSecret: null, callbackSessionId: null }
                                )
                            }
                        />
                    </div>
                </TabsContent>

                <TabsContent value="sessions" className="min-h-0 flex-1 overflow-hidden">
                    <SessionsTabBody
                        sessions={sessions}
                        selectedSessionId={urlState.selectedSessionId}
                        selectedSession={selectedSession}
                        selectedSessionLogs={selectedSessionLogs}
                        selectedSessionLoading={selectedSessionLoading}
                        onSelectSession={(id) => onChangeUrlState({ selectedSessionId: id })}
                    />
                </TabsContent>

                <TabsContent value="memory" className="min-h-0 flex-1 overflow-hidden">
                    <div className="h-full px-6 pb-6 pt-4">
                        <MemoryClassic slug={agent.slug} />
                    </div>
                </TabsContent>
            </Tabs>
        </div>
    )
}

/* ── Sessions tab body ──────────────────────────────────────────── */

function SessionsTabBody({
    sessions,
    selectedSessionId,
    selectedSession,
    selectedSessionLogs,
    selectedSessionLoading,
    onSelectSession,
}: {
    sessions: ChatSession[]
    selectedSessionId: string | null
    selectedSession: ChatSession | null
    selectedSessionLogs: LogEntry[]
    selectedSessionLoading: boolean
    onSelectSession: (id: string | null) => void
}): React.ReactElement {
    // No selection → list takes the whole tab (centered + capped) so the
    // common "browse" path keeps the familiar full-width feel.
    if (!selectedSessionId) {
        return (
            <div className="mx-auto h-full w-full max-w-5xl overflow-y-auto px-6 pb-6 pt-4">
                <SessionsList
                    sessions={sessions}
                    selectedSessionId={null}
                    onOpenSession={(id) => onSelectSession(id)}
                />
            </div>
        )
    }
    // Master-detail. Full bleed so playback + logs get room on the right.
    return (
        <div className="grid h-full grid-cols-[minmax(280px,360px)_minmax(0,1fr)] divide-x divide-border">
            <aside className="flex min-h-0 flex-col overflow-hidden">
                <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
                    <SessionsList
                        sessions={sessions}
                        selectedSessionId={selectedSessionId}
                        onOpenSession={(id) => onSelectSession(id)}
                    />
                </div>
            </aside>
            <main className="min-h-0 overflow-hidden">
                {selectedSession ? (
                    <SessionDetail
                        session={selectedSession}
                        logs={selectedSessionLogs}
                        onClose={() => onSelectSession(null)}
                    />
                ) : selectedSessionLoading ? (
                    <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                        Loading session…
                    </div>
                ) : (
                    <div className="flex h-full items-center justify-center px-4 text-center text-sm text-muted-foreground">
                        Couldn't load that session.
                    </div>
                )}
            </main>
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
