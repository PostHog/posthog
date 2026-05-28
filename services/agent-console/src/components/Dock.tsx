/**
 * Adapter: dock-context → `<AgentChat />`, driven by `useFakeRunner`.
 *
 * Owns:
 *   - the in-flight `ChatSession` (via the fake runner)
 *   - the registered `@posthog/ui/*` handlers — the `focus` handler
 *     pushes a target into `focus-context` and navigates the route
 *     when needed, so the dock actually drives the read panel
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

import { useDockStore } from './dock-context'
import { useFocusStore, type FocusTarget } from './focus-context'

export function Dock(): React.ReactElement {
    const { context, exitPlayground } = useDockStore()
    const focus = useFocusStore()
    const router = useRouter()

    /**
     * `@posthog/ui/focus` — pushes a target into focus-context so the
     * agent-detail page (or whichever surface is mounted) can react.
     * Also routes the URL when navigation across pages is required.
     *
     * When focus mode is paused, returns `{ focused: false }` so the
     * agent's prompt — which is written defensively — falls back to
     * narrating in text instead of expecting the UI to follow.
     */
    const focusHandler: ClientToolHandler<FocusArgs, FocusResult> = useMemo(
        () => ({
            id: '@posthog/ui/focus',
            handle: (args) => {
                if (!focus.enabled) {
                    return { focused: false, reason: 'user_paused_follow' }
                }

                // Resolve the agent slug — explicit on the args, falling back to
                // the current context's agent if any.
                const contextSlug =
                    context.mode === 'concierge' && 'agent' in context.page
                        ? context.page.agent.slug
                        : context.mode === 'playground'
                          ? context.agent.slug
                          : undefined

                let target: FocusTarget
                let routeTarget: string | null = null

                if (args.kind === 'file') {
                    target = { kind: 'file', agentSlug: contextSlug, path: args.path }
                    if (contextSlug) {
                        routeTarget = `/agents/${contextSlug}`
                    }
                } else if (args.kind === 'revision') {
                    target = { kind: 'revision', agentSlug: contextSlug, revisionId: args.revisionId }
                    if (contextSlug) {
                        routeTarget = `/agents/${contextSlug}`
                    }
                } else if (args.kind === 'session') {
                    target = { kind: 'session', agentSlug: contextSlug, sessionId: args.sessionId }
                    if (contextSlug) {
                        routeTarget = `/agents/${contextSlug}`
                    }
                } else if (args.kind === 'spec_section') {
                    target = { kind: 'spec_section', agentSlug: contextSlug, section: args.section }
                    if (contextSlug) {
                        routeTarget = `/agents/${contextSlug}`
                    }
                } else {
                    // Exhaustive — but defensive.
                    return { focused: false, reason: 'unknown_focus_kind' }
                }

                focus.setTarget(target)
                if (routeTarget) {
                    router.push(routeTarget)
                }

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

    const handlers = useMemo(() => [focusHandler, toastHandler], [focusHandler, toastHandler])

    // Mode-aware script set + starting session.
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
