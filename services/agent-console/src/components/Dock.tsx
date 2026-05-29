/**
 * Adapter: dock-context → `<AgentChat />`, driven by `useFakeRunner`.
 *
 * Owns:
 *   - the in-flight `ChatSession` (via the fake runner)
 *   - the `@posthog/ui/focus` handler — pure URL mapper. The agent
 *     calls focus, the handler pushes the matching route, and the
 *     console refetches via `bumpReload()` so pages already on the
 *     target URL still see fresh data.
 *
 * Throwaway scaffolding flagged by `useFakeRunner` — when v0.2 ships
 * real session transport, this component swaps the hook for a real
 * runner client and keeps the same prop surface.
 */

'use client'

import { useRouter } from 'next/navigation'
import { useMemo } from 'react'

import { AgentChat, useFakeRunner, type ClientToolHandler } from '@posthog/agent-chat'
import type { FocusArgs, FocusResult, ToastArgs, ToastResult } from '@posthog/agent-chat'
import {
    conciergeScripts,
    fallbackScript,
    playgroundScripts,
    playgroundSession,
    waitingSession,
} from '@posthog/agent-chat/fixtures'

import { bumpReload } from '@/lib/reloadSignal'

import { useDockStore } from './dock-context'
import { useFocusStore } from './focus-context'

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

export function Dock(): React.ReactElement {
    const { context, exitPlayground } = useDockStore()
    const focus = useFocusStore()
    const router = useRouter()

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

                const url = urlForFocus(args, contextSlug)
                if (!url) {
                    return { focused: false, reason: 'unresolved_target' }
                }

                router.push(url)
                // Bump the global reload signal so pages already on the
                // target URL refetch (focus = "look at this with fresh data").
                bumpReload()

                return { focused: true, kind: args.kind }
            },
        }),
        [context, focus, router]
    )

    const toastHandler: ClientToolHandler<ToastArgs, ToastResult> = useMemo(
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

    const handlers = useMemo<ClientToolHandler[]>(
        () => [focusHandler, toastHandler] as unknown as ClientToolHandler[],
        [focusHandler, toastHandler]
    )

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
            }}
            onNewSession={() => runner.reset()}
            onSend={runner.send}
        />
    )
}
