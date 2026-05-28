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
    type ToastArgs,
    type ToastResult,
} from '@posthog/agent-chat'
import {
    agents as defaultAgents,
    agentsWithArchived,
    conciergeScripts,
    fallbackScript,
    fleetLiveSessions,
    fleetStats,
    getAgentStatsFixture,
    listSessionsForAgentFixture,
    liveSessionCountsByAgent,
    playgroundScripts,
    playgroundSession,
    waitingSession,
    weeklyDigest,
    weeklyDigestBundle,
    weeklyDigestRevisions,
} from '@posthog/agent-chat/fixtures'
import type { AgentApplicationFixture, AgentRevisionFixture, BundleFile } from '@posthog/agent-chat/fixtures'

import { AgentDetail } from '@/pages/AgentDetail'
import { AgentsList } from '@/pages/AgentsList'

import { DockContextProvider, useDockStore, useSetDockPage } from './dock-context'
import { FocusContextProvider, useFocusStore, type FocusTarget } from './focus-context'
import { FocusModeBanner } from './FocusModeBanner'
import { PostHogMark } from './PostHogMark'

const DOCK_WIDTH = 360

interface ShellArgs {
    /** Which view the shell starts on. */
    initialRoute?: 'list' | { kind: 'detail'; slug: string }
    /** Force playground on the named agent slug from mount. */
    startInPlaygroundFor?: string
    /** Pool of agents to drive the list. Defaults to the standard fixture. */
    agentPool?: AgentApplicationFixture[]
}

function ShellInner({ initialRoute = 'list', startInPlaygroundFor, agentPool }: ShellArgs): React.ReactElement {
    const agents = agentPool ?? defaultAgents
    const [route, setRoute] = useState<'list' | { kind: 'detail'; slug: string }>(initialRoute)
    const currentAgent = useMemo(() => {
        if (route === 'list') {
            return null
        }
        return agents.find((a) => a.slug === route.slug) ?? null
    }, [route, agents])

    const goTo = (next: 'list' | { kind: 'detail'; slug: string }): void => setRoute(next)

    return (
        <DockContextProvider>
            <FocusContextProvider>
                <PlaygroundBootstrap forSlug={startInPlaygroundFor} agents={agents} />
                <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
                    <Sidebar onGoHome={() => goTo('list')} />
                    <main className="flex-1 overflow-y-auto">
                        <FocusModeBanner />
                        {route === 'list' ? (
                            <ListSurface agents={agents} onOpenAgent={(slug) => goTo({ kind: 'detail', slug })} />
                        ) : currentAgent ? (
                            <DetailSurface
                                agent={currentAgent}
                                revisions={weeklyDigestRevisions}
                                bundle={weeklyDigestBundle}
                                onBackToList={() => goTo('list')}
                            />
                        ) : (
                            <div className="p-6 text-sm text-muted-foreground">No such agent.</div>
                        )}
                    </main>
                    <aside className="shrink-0 border-l border-border" style={{ width: DOCK_WIDTH }}>
                        <DockSurface onRouteToAgent={(slug) => goTo({ kind: 'detail', slug })} />
                    </aside>
                </div>
            </FocusContextProvider>
        </DockContextProvider>
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
    agents,
    onOpenAgent,
}: {
    agents: AgentApplicationFixture[]
    onOpenAgent: (slug: string) => void
}): React.ReactElement {
    useSetDockPage({ kind: 'agent-list' })
    return (
        <AgentsList
            agents={agents}
            fleetStats={fleetStats}
            liveSessions={fleetLiveSessions}
            liveCountByAgent={liveSessionCountsByAgent}
            onOpenAgent={onOpenAgent}
            onCreateAgent={() => console.info('[shell story] createAgent — would route to concierge')}
            onOpenSession={(id) => console.info('[shell story] openSession', id)}
            onViewAllSessions={() => console.info('[shell story] viewAllSessions')}
        />
    )
}

function DetailSurface({
    agent,
    revisions,
    bundle,
    onBackToList,
}: {
    agent: AgentApplicationFixture
    revisions: AgentRevisionFixture[]
    bundle: BundleFile[]
    onBackToList: () => void
}): React.ReactElement {
    const agentRef = { id: agent.id, slug: agent.slug, name: agent.name }
    useSetDockPage({ kind: 'agent', agent: agentRef })
    const { enterPlayground } = useDockStore()
    const stats = getAgentStatsFixture(agent.id)
    const sessions = listSessionsForAgentFixture(agent.id)
    return (
        <AgentDetail
            agent={agent}
            revisions={revisions}
            bundle={bundle}
            stats={stats}
            sessions={sessions}
            onTryAgent={() => enterPlayground(agentRef)}
            onBackToList={onBackToList}
            onOpenSession={(id) => console.info('[shell story] openSession', id)}
        />
    )
}

function DockSurface({ onRouteToAgent }: { onRouteToAgent: (slug: string) => void }): React.ReactElement {
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
                if (args.kind === 'file') {
                    target = { kind: 'file', agentSlug: contextSlug, path: args.path }
                } else if (args.kind === 'revision') {
                    target = { kind: 'revision', agentSlug: contextSlug, revisionId: args.revisionId }
                } else if (args.kind === 'session') {
                    target = { kind: 'session', agentSlug: contextSlug, sessionId: args.sessionId }
                } else if (args.kind === 'spec_section') {
                    target = { kind: 'spec_section', agentSlug: contextSlug, section: args.section }
                } else {
                    return { focused: false, reason: 'unknown_focus_kind' }
                }

                focus.setTarget(target)
                if (contextSlug) {
                    onRouteToAgent(contextSlug)
                }
                return { focused: true, kind: args.kind }
            },
        }),
        [context, focus, onRouteToAgent]
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

    const handlers = useMemo(() => [focusHandler, toastHandler], [focusHandler, toastHandler])

    const initialSession = context.mode === 'playground' ? playgroundSession : waitingSession
    const scripts = context.mode === 'playground' ? playgroundScripts : conciergeScripts

    const runner = useFakeRunner({
        initialSession,
        scripts,
        fallbackScript,
        handlers,
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
            onSend={runner.send}
        />
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

const meta: Meta<typeof ShellInner> = {
    title: 'Console/Shell (full surface)',
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
