/**
 * Whole-shell stories — the "what does the console actually look like"
 * review surface. Each story renders the AppShell with story-local
 * navigation so list → detail → playground all work in Storybook
 * without a real Next.js router.
 *
 * The dock here uses the same `useFakeRunner` + focus-context wiring
 * as the real `Dock` component, so the focus-flow demo runs end-to-end
 * inside Storybook. Story-local nav stands in for `next/navigation`.
 */

import type { Meta, StoryObj } from '@storybook/react'
import { BotIcon } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import {
    AgentChat,
    useFakeRunner,
    type ClientToolHandler,
    type FocusArgs,
    type FocusResult,
    type ResolvedMutation,
    type ToastArgs,
    type ToastResult,
} from '@posthog/agent-chat'
import {
    agents as defaultAgents,
    agentsWithArchived,
    conciergeScripts,
    fallbackScript,
    playgroundScripts,
    playgroundSession,
    waitingSession,
    weeklyDigest,
} from '@posthog/agent-chat/fixtures'
import type { AgentApplicationFixture } from '@posthog/agent-chat/fixtures'

import {
    getAgent,
    getAgentStats,
    getFleetStats,
    getSession,
    listLiveSessions,
    listLogsForSession,
    listSessionsForAgent,
    patchRevisionSpec,
    writeBundleFile,
} from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'
import { AgentDetail } from '@/pages/AgentDetail'
import { AgentsList } from '@/pages/AgentsList'
import { SessionDetail } from '@/pages/SessionDetail'

import { DockContextProvider, useDockStore, useSetDockPage } from './dock-context'
import { FocusContextProvider, useFocusStore, type FocusTarget } from './focus-context'
import { FocusModeBanner } from './FocusModeBanner'
import { MutationStreamProvider } from './mutation-stream'
import { PostHogMark } from './PostHogMark'
import { useMutatingBundle } from './use-mutating-bundle'
import { useMutatingRevisions } from './use-mutating-revisions'

const DOCK_WIDTH = 360

type Route = 'list' | { kind: 'detail'; slug: string } | { kind: 'session'; slug: string; sessionId: string }

interface ShellArgs {
    /** Which view the shell starts on. */
    initialRoute?: Route
    /** Force playground on the named agent slug from mount. */
    startInPlaygroundFor?: string
    /** Pool of agents to drive the list. Defaults to the standard fixture. */
    agentPool?: AgentApplicationFixture[]
}

function ShellInner({ initialRoute = 'list', startInPlaygroundFor, agentPool }: ShellArgs): React.ReactElement {
    const agents = agentPool ?? defaultAgents
    const [route, setRoute] = useState<Route>(initialRoute)
    const currentAgent = useMemo(() => {
        if (route === 'list') {
            return null
        }
        return agents.find((a) => a.slug === route.slug) ?? null
    }, [route, agents])

    const goTo = (next: Route): void => setRoute(next)

    return (
        <MutationStreamProvider>
            <DockContextProvider>
                <FocusContextProvider>
                    <PlaygroundBootstrap forSlug={startInPlaygroundFor} agents={agents} />
                    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
                        <Sidebar onGoHome={() => goTo('list')} />
                        <main className="flex flex-1 flex-col overflow-hidden">
                            <FocusModeBanner />
                            <div className="min-h-0 flex-1 overflow-y-auto">
                                {route === 'list' ? (
                                    <ListSurface
                                        onOpenAgent={(slug) => goTo({ kind: 'detail', slug })}
                                        onOpenSession={(slug, sessionId) => goTo({ kind: 'session', slug, sessionId })}
                                    />
                                ) : route.kind === 'session' && currentAgent ? (
                                    <SessionSurface
                                        slug={currentAgent.slug}
                                        sessionId={route.sessionId}
                                        onBackToList={() => goTo('list')}
                                        onBackToAgent={(slug) => goTo({ kind: 'detail', slug })}
                                    />
                                ) : currentAgent ? (
                                    <DetailSurface
                                        slug={currentAgent.slug}
                                        onBackToList={() => goTo('list')}
                                        onOpenSession={(sessionId) =>
                                            goTo({ kind: 'session', slug: currentAgent.slug, sessionId })
                                        }
                                    />
                                ) : (
                                    <div className="p-6 text-sm text-muted-foreground">No such agent.</div>
                                )}
                            </div>
                        </main>
                        <aside className="shrink-0 border-l border-border" style={{ width: DOCK_WIDTH }}>
                            <DockSurface
                                onRouteToAgent={(slug) => goTo({ kind: 'detail', slug })}
                                onRouteToSession={(slug, sessionId) => goTo({ kind: 'session', slug, sessionId })}
                            />
                        </aside>
                    </div>
                </FocusContextProvider>
            </DockContextProvider>
        </MutationStreamProvider>
    )
}

function Sidebar({ onGoHome }: { onGoHome: () => void }): React.ReactElement {
    return (
        <nav className="flex h-full w-14 shrink-0 flex-col items-center gap-2 border-r border-border py-3">
            <span
                aria-label="PostHog agent console"
                className="inline-flex h-9 w-9 items-center justify-center"
                title="PostHog agent console"
            >
                <PostHogMark className="h-6 w-6" />
            </span>
            <div className="my-1 h-px w-6 bg-border" aria-hidden />
            <button
                type="button"
                onClick={onGoHome}
                aria-label="Agents"
                className="inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-md bg-accent text-foreground transition-colors hover:bg-accent"
            >
                <BotIcon className="h-4 w-4" />
            </button>
        </nav>
    )
}

function ListSurface({
    onOpenAgent,
    onOpenSession,
}: {
    onOpenAgent: (slug: string) => void
    onOpenSession: (agentSlug: string, sessionId: string) => void
}): React.ReactElement {
    useSetDockPage({ kind: 'agent-list' })
    const agents = useResource(() =>
        // Local helper to keep the import surface tight at the top.
        import('@/lib/apiClient').then((m) => m.listAgents())
    )
    const fleet = useResource(() => getFleetStats())
    const live = useResource(() => listLiveSessions())

    const error = agents.error ?? fleet.error ?? live.error
    if (error) {
        return <div className="p-6 text-sm text-destructive">Failed to load: {error.message}</div>
    }
    if (!agents.data || !fleet.data || !live.data) {
        return <div className="p-6 text-sm text-muted-foreground">Loading…</div>
    }

    const liveSessions = live.data
    const liveCountByAgent = liveSessions.reduce<Record<string, number>>((acc, s) => {
        acc[s.application.id] = (acc[s.application.id] ?? 0) + 1
        return acc
    }, {})

    return (
        <AgentsList
            agents={agents.data}
            fleetStats={fleet.data}
            liveSessions={liveSessions}
            liveCountByAgent={liveCountByAgent}
            onOpenAgent={onOpenAgent}
            onCreateAgent={() => console.info('[shell story] createAgent — would route to concierge')}
            onOpenSession={(sessionId) => {
                const session = liveSessions.find((s) => s.id === sessionId)
                if (session) {
                    onOpenSession(session.application.slug, sessionId)
                }
            }}
            onViewAllSessions={() => console.info('[shell story] viewAllSessions')}
        />
    )
}

function DetailSurface({
    slug,
    onBackToList,
    onOpenSession,
}: {
    slug: string
    onBackToList: () => void
    onOpenSession: (sessionId: string) => void
}): React.ReactElement {
    const agent = useResource(() => getAgent(slug), [slug])
    if (agent.error) {
        return <div className="p-6 text-sm text-destructive">Failed to load: {agent.error.message}</div>
    }
    if (!agent.data) {
        return <div className="p-6 text-sm text-muted-foreground">Loading…</div>
    }
    return (
        <DetailSurfaceInner slug={slug} agent={agent.data} onBackToList={onBackToList} onOpenSession={onOpenSession} />
    )
}

function DetailSurfaceInner({
    slug,
    agent,
    onBackToList,
    onOpenSession,
}: {
    slug: string
    agent: AgentApplicationFixture
    onBackToList: () => void
    onOpenSession: (sessionId: string) => void
}): React.ReactElement {
    const agentRef = { id: agent.id, slug: agent.slug, name: agent.name }
    useSetDockPage({ kind: 'agent', agent: agentRef })
    const { enterPlayground } = useDockStore()

    const stats = useResource(() => getAgentStats(slug), [slug])
    const sessions = useResource(() => listSessionsForAgent(slug), [slug])
    const { revisions, loading: revisionsLoading } = useMutatingRevisions(slug, agent.id)
    const { bundle, loading: bundleLoading } = useMutatingBundle(slug, agent.id)

    if (stats.error ?? sessions.error) {
        const message = (stats.error ?? sessions.error)?.message ?? 'Unknown error'
        return <div className="p-6 text-sm text-destructive">Failed to load: {message}</div>
    }
    if (stats.loading || sessions.loading || revisionsLoading || bundleLoading || !stats.data || !sessions.data) {
        return <div className="p-6 text-sm text-muted-foreground">Loading…</div>
    }

    return (
        <AgentDetail
            agent={agent}
            revisions={revisions}
            bundle={bundle}
            stats={stats.data}
            sessions={sessions.data}
            onTryAgent={() => enterPlayground(agentRef)}
            onBackToList={onBackToList}
            onOpenSession={onOpenSession}
        />
    )
}

function SessionSurface({
    slug,
    sessionId,
    onBackToList,
    onBackToAgent,
}: {
    slug: string
    sessionId: string
    onBackToList: () => void
    onBackToAgent: (slug: string) => void
}): React.ReactElement {
    const agent = useResource(() => getAgent(slug), [slug])
    const session = useResource(() => getSession(sessionId), [sessionId])
    const logs = useResource(() => listLogsForSession(sessionId), [sessionId])

    const error = agent.error ?? session.error ?? logs.error
    if (error) {
        return <div className="p-6 text-sm text-destructive">Failed to load: {error.message}</div>
    }
    if (!agent.data || !session.data || !logs.data) {
        return <div className="p-6 text-sm text-muted-foreground">Loading…</div>
    }
    return (
        <SessionSurfaceInner
            agent={agent.data}
            session={session.data}
            logs={logs.data}
            onBackToList={onBackToList}
            onBackToAgent={onBackToAgent}
        />
    )
}

function SessionSurfaceInner({
    agent,
    session,
    logs,
    onBackToList,
    onBackToAgent,
}: {
    agent: AgentApplicationFixture
    session: Awaited<ReturnType<typeof getSession>>
    logs: Awaited<ReturnType<typeof listLogsForSession>>
    onBackToList: () => void
    onBackToAgent: (slug: string) => void
}): React.ReactElement {
    const agentRef = { id: agent.id, slug: agent.slug, name: agent.name }
    useSetDockPage({ kind: 'agent-session', agent: agentRef, sessionId: session.id })
    return (
        <SessionDetail
            agent={agent}
            session={session}
            logs={logs}
            onBackToList={onBackToList}
            onBackToAgent={() => onBackToAgent(agent.slug)}
        />
    )
}

function DockSurface({
    onRouteToAgent,
    onRouteToSession,
}: {
    onRouteToAgent: (slug: string) => void
    onRouteToSession: (slug: string, sessionId: string) => void
}): React.ReactElement {
    const { context, exitPlayground } = useDockStore()
    const focus = useFocusStore()

    // Same shape as the real `Dock`, but routing goes through the story-
    // local navigator rather than `next/navigation`.
    const focusHandler: ClientToolHandler<FocusArgs, FocusResult> = useMemo(
        () => ({
            id: '@posthog/ui/focus',
            handle: (args) => {
                if (!focus.enabled) {
                    return { focused: false, reason: 'user_paused_follow' }
                }
                const contextSlug =
                    context.mode === 'concierge' && 'agent' in context.page
                        ? context.page.agent.slug
                        : context.mode === 'playground'
                          ? context.agent.slug
                          : undefined

                let target: FocusTarget
                const mutationId = args.mutationId
                if (args.kind === 'file') {
                    target = { kind: 'file', agentSlug: contextSlug, path: args.path, mutationId }
                } else if (args.kind === 'revision') {
                    target = { kind: 'revision', agentSlug: contextSlug, revisionId: args.revisionId, mutationId }
                } else if (args.kind === 'session') {
                    target = { kind: 'session', agentSlug: contextSlug, sessionId: args.sessionId, mutationId }
                } else if (args.kind === 'spec_section') {
                    target = { kind: 'spec_section', agentSlug: contextSlug, section: args.section, mutationId }
                } else {
                    return { focused: false, reason: 'unknown_focus_kind' }
                }

                focus.setTarget(target)
                if (contextSlug) {
                    if (args.kind === 'session') {
                        onRouteToSession(contextSlug, args.sessionId)
                    } else {
                        onRouteToAgent(contextSlug)
                    }
                }
                return { focused: true, kind: args.kind, mutationId }
            },
        }),
        [context, focus, onRouteToAgent, onRouteToSession]
    )

    const toastHandler: ClientToolHandler<ToastArgs, ToastResult> = useMemo(
        () => ({
            id: '@posthog/ui/toast',
            handle: (args) => {
                // eslint-disable-next-line no-console
                console.info('[shell story toast]', args)
                return { shown: true }
            },
        }),
        []
    )

    const handlers = useMemo<ClientToolHandler[]>(
        () => [focusHandler, toastHandler] as unknown as ClientToolHandler[],
        [focusHandler, toastHandler]
    )

    const initialSession = context.mode === 'playground' ? playgroundSession : waitingSession
    const scripts = context.mode === 'playground' ? playgroundScripts : conciergeScripts

    const handleToolMutate = useMemo(
        () =>
            (mutations: ResolvedMutation[]): void => {
                for (const m of mutations) {
                    if (m.entityKey.startsWith('bundle-file:') && isBundleFilePayload(m.payload)) {
                        const [, slug, ...rest] = m.entityKey.split(':')
                        void writeBundleFile(slug, rest.join(':'), {
                            newContent: m.payload.newContent,
                            mutationId: m.mutationId,
                        }).catch((err) => console.error('[shell story] writeBundleFile', err))
                    } else if (m.entityKey.startsWith('revision-spec:') && isSpecPatchPayload(m.payload)) {
                        const [, slug, revisionId] = m.entityKey.split(':')
                        void patchRevisionSpec(revisionId, {
                            applicationSlug: slug,
                            patch: m.payload.patch,
                            mutationId: m.mutationId,
                        }).catch((err) => console.error('[shell story] patchRevisionSpec', err))
                    }
                }
            },
        []
    )

    const runner = useFakeRunner({
        initialSession,
        scripts,
        fallbackScript,
        handlers,
        onToolMutate: handleToolMutate,
    })

    return (
        <AgentChat
            context={context}
            session={runner.session}
            handlers={handlers}
            followingEnabled={focus.enabled}
            onFollowingChange={focus.setEnabled}
            onExitPlayground={() => {
                exitPlayground()
                runner.reset()
                focus.clear()
            }}
            onNewSession={() => {
                runner.reset()
                focus.clear()
            }}
            onSend={runner.send}
        />
    )
}

function isBundleFilePayload(payload: unknown): payload is { newContent: string } {
    return (
        typeof payload === 'object' &&
        payload !== null &&
        'newContent' in payload &&
        typeof (payload as { newContent: unknown }).newContent === 'string'
    )
}

function isSpecPatchPayload(payload: unknown): payload is { patch: Record<string, unknown> } {
    return (
        typeof payload === 'object' &&
        payload !== null &&
        'patch' in payload &&
        typeof (payload as { patch: unknown }).patch === 'object' &&
        (payload as { patch: unknown }).patch !== null
    )
}

function PlaygroundBootstrap({
    forSlug,
    agents,
}: {
    forSlug: string | undefined
    agents: AgentApplicationFixture[]
}): null {
    const { enterPlayground } = useDockStore()
    useEffect(() => {
        if (!forSlug) {
            return
        }
        const target = agents.find((a) => a.slug === forSlug)
        if (target) {
            enterPlayground({ id: target.id, slug: target.slug, name: target.name })
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])
    return null
}

// First in the sidebar — the whole-shell stories are the primary
// review surface; the per-component stories are scaffolding for them.
const meta: Meta<typeof ShellInner> = {
    title: 'Agent console/Shell (full surface)',
    component: ShellInner,
    parameters: { layout: 'fullscreen' },
}

export default meta
type Story = StoryObj<typeof ShellInner>

export const AgentsListWithDock: Story = {
    args: { initialRoute: 'list' },
}

export const AgentsListWithArchivedAndDock: Story = {
    args: { initialRoute: 'list', agentPool: agentsWithArchived },
}

export const AgentsListEmpty: Story = {
    args: { initialRoute: 'list', agentPool: [] },
}

export const AgentDetailConcierge: Story = {
    args: { initialRoute: { kind: 'detail', slug: weeklyDigest.slug } },
}

export const AgentDetailPlayground: Story = {
    args: { initialRoute: { kind: 'detail', slug: weeklyDigest.slug }, startInPlaygroundFor: weeklyDigest.slug },
}

/**
 * Dedicated focus-flow story — starts on the agent-detail page so a
 * starter prompt can immediately drive a real navigation. Try clicking
 * "Explain this agent" or "Make a change" in the dock and watch the
 * tab + bundle file change underneath you.
 */
export const FocusFlowDemo: Story = {
    args: { initialRoute: { kind: 'detail', slug: weeklyDigest.slug } },
}

/**
 * Focus-with-mutation demo — click "Tighten the prompt" in the dock.
 * The concierge calls a server tool that declares a `bundle-file:`
 * mutation, the mock-api overlay absorbs the new content, and the
 * file tree row + viewer flair as the bundle re-reads. Toggle focus
 * mode off via the dock header to confirm the data still refreshes
 * silently — flair is gated on focus mode being on.
 */
export const FocusWithMutationDemo: Story = {
    args: { initialRoute: { kind: 'detail', slug: weeklyDigest.slug } },
}
