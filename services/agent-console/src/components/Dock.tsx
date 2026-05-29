/**
 * Adapter: dock-context → `<AgentChat />`.
 *
 * Two runners, picked by mode:
 *   - **Playground** → `useRealRunner` against `context.agent.slug`,
 *     talking to agent-ingress over SSE. The dock is now actually
 *     chatting with the real agent.
 *   - **Concierge** → still `useFakeRunner` for now. The concierge
 *     agent isn't deployed in dev yet; once it is, this mode also
 *     switches to `useRealRunner` against a configured slug.
 *
 * Owns the `@posthog/ui/focus` handler — pure URL mapper. The agent
 * calls focus, the handler pushes the matching route, and the
 * console refetches via `bumpReload()` so pages already on the
 * target URL still see fresh data.
 */

'use client'

import { useRouter } from 'next/navigation'
import { useMemo } from 'react'

import { AgentChat, useFakeRunner, type ClientToolHandler } from '@posthog/agent-chat'
import type {
    AgentApplicationRef,
    ChatContext,
    FocusArgs,
    FocusResult,
    SessionPrincipal,
    ToastArgs,
    ToastResult,
} from '@posthog/agent-chat'
import { conciergeScripts, fallbackScript, waitingSession } from '@posthog/agent-chat/fixtures'

import { bumpReload } from '@/lib/reloadSignal'

import { useDockStore } from './dock-context'
import { useFocusStore } from './focus-context'
import { useSession } from './session-context'
import { useRealRunner } from './useRealRunner'

/**
 * Maps a focus call to the URL the console should land on. Returns
 * `null` if the call references an agent we can't resolve (e.g. no
 * agent in context, no slug in args).
 */
function urlForFocus(args: FocusArgs, contextSlug: string | undefined): string | null {
    const slug = contextSlug
    if (!slug) {
        return null
    }
    switch (args.kind) {
        case 'tab':
            return `/agents/${slug}?tab=${args.tab}`
        case 'revision':
            return `/agents/${slug}?tab=configuration&revision=${encodeURIComponent(args.revisionId)}`
        case 'spec_section':
            return `/agents/${slug}?tab=configuration&section=${args.section}`
        case 'file':
            return `/agents/${slug}?tab=configuration&file=${encodeURIComponent(args.path)}`
        case 'session':
            return `/agents/${slug}/sessions/${encodeURIComponent(args.sessionId)}`
        default:
            return null
    }
}

function useFocusHandler(context: ChatContext): ClientToolHandler<FocusArgs, FocusResult> {
    const focus = useFocusStore()
    const router = useRouter()
    return useMemo(
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
                const url = urlForFocus(args, contextSlug)
                if (!url) {
                    return { focused: false, reason: 'unresolved_target' }
                }
                router.push(url)
                bumpReload()
                return { focused: true, kind: args.kind }
            },
        }),
        [context, focus, router]
    )
}

function useDockHandlers(context: ChatContext): ClientToolHandler[] {
    const focusHandler = useFocusHandler(context)
    const toastHandler = useMemo<ClientToolHandler<ToastArgs, ToastResult>>(
        () => ({
            id: '@posthog/ui/toast',
            handle: (args) => {
                // eslint-disable-next-line no-console
                console.info('[dock toast]', args)
                return { shown: true }
            },
        }),
        []
    )
    return useMemo<ClientToolHandler[]>(
        () => [focusHandler, toastHandler] as unknown as ClientToolHandler[],
        [focusHandler, toastHandler]
    )
}

export function Dock(): React.ReactElement {
    const { context } = useDockStore()
    // Re-mount the dock when switching mode/agent so the runner hooks
    // tear down cleanly. Cheaper + safer than trying to thread state
    // across runner swaps.
    const key = context.mode === 'playground' ? `playground:${context.agent.slug}` : 'concierge'
    return context.mode === 'playground' ? (
        <PlaygroundDock key={key} agentRef={context.agent} />
    ) : (
        <ConciergeDock key={key} />
    )
}

function PlaygroundDock({ agentRef }: { agentRef: AgentApplicationRef }): React.ReactElement {
    const { context, exitPlayground } = useDockStore()
    const focus = useFocusStore()
    const { info } = useSession()
    const handlers = useDockHandlers(context)

    const principal: SessionPrincipal = useMemo(() => {
        const profile = (info?.profile ?? null) as { email?: string; first_name?: string; uuid?: string } | null
        const displayName = profile?.first_name || profile?.email || 'You'
        return { kind: 'human', userId: profile?.uuid ?? 'you', displayName }
    }, [info])

    const runner = useRealRunner({ agentSlug: agentRef.slug, agentRef, principal })

    return (
        <AgentChat
            context={context}
            session={runner.session}
            handlers={handlers}
            followingEnabled={focus.enabled}
            onFollowingChange={focus.setEnabled}
            onExitPlayground={() => {
                void runner.reset()
                exitPlayground()
            }}
            onNewSession={() => void runner.reset()}
            onSend={(text) => void runner.send(text)}
        />
    )
}

function ConciergeDock(): React.ReactElement {
    const { context } = useDockStore()
    const focus = useFocusStore()
    const handlers = useDockHandlers(context)

    // v0: concierge agent isn't deployed yet — keep the fake runner
    // for now so the dock has something to show. Swap to useRealRunner
    // once a concierge slug is configured.
    const runner = useFakeRunner({
        initialSession: waitingSession,
        scripts: conciergeScripts,
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
            onNewSession={() => runner.reset()}
            onSend={runner.send}
        />
    )
}
