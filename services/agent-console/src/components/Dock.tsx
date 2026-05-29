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
import { useCallback, useEffect, useMemo, useState } from 'react'

import { AgentChat, useFakeRunner, type ClientToolHandler, type TransportError } from '@posthog/agent-chat'
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

import { IngressError } from '@/lib/agentIngressClient'
import { bumpReload } from '@/lib/reloadSignal'

import { useDockStore } from './dock-context'
import { useFocusStore } from './focus-context'
import { useSession } from './session-context'
import { useRealRunner } from './useRealRunner'

/**
 * Translate the runner's `Error` into the wire-aware shape AgentChat
 * uses to render its `TransportErrorBanner`. We keep this in the dock
 * (not inside `useRealRunner`) because the agent-chat package is the
 * boundary: agent-chat should never import the IngressError class.
 *
 * Special-cases:
 *   - `stream:dropped` — synthetic message we set when the SSE stream
 *     ends without a terminal `completed`/`failed` event. status=-1
 *     so the banner copy explains it as a connection drop.
 */
/**
 * Persisted "render assistant text as markdown" preference. Lives in
 * localStorage so it survives reloads and is shared between the
 * playground and concierge docks (a single user preference for the
 * whole console).
 */
const MARKDOWN_STORAGE_KEY = 'agent-console:render-markdown'

function useRenderMarkdownPreference(): [boolean, (next: boolean) => void] {
    const [value, setValue] = useState<boolean>(true)
    useEffect(() => {
        if (typeof window === 'undefined') {
            return
        }
        const raw = window.localStorage.getItem(MARKDOWN_STORAGE_KEY)
        if (raw === 'false') {
            setValue(false)
        }
    }, [])
    const update = useCallback((next: boolean) => {
        setValue(next)
        if (typeof window !== 'undefined') {
            window.localStorage.setItem(MARKDOWN_STORAGE_KEY, next ? 'true' : 'false')
        }
    }, [])
    return [value, update]
}

function asTransportError(err: Error | null): TransportError | null {
    if (!err) {
        return null
    }
    if (err.message === 'stream:dropped') {
        return { status: -1, code: 'stream_dropped', detail: 'The event stream closed before the turn finished.' }
    }
    if (err instanceof IngressError) {
        return { status: err.status, code: err.body?.error, detail: err.body?.detail }
    }
    return { status: -1, detail: err.message }
}

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
    // Re-mount the dock when switching mode/agent/revision so the
    // runner hooks tear down cleanly. Cheaper + safer than trying to
    // thread state across runner swaps.
    const key =
        context.mode === 'playground'
            ? `playground:${context.agent.slug}:${context.previewRevisionId ?? 'live'}`
            : 'concierge'
    return context.mode === 'playground' ? (
        <PlaygroundDock key={key} agentRef={context.agent} previewRevisionId={context.previewRevisionId} />
    ) : (
        <ConciergeDock key={key} />
    )
}

function PlaygroundDock({
    agentRef,
    previewRevisionId,
}: {
    agentRef: AgentApplicationRef
    previewRevisionId?: string
}): React.ReactElement {
    const { context, exitPlayground } = useDockStore()
    const focus = useFocusStore()
    const { info } = useSession()
    const handlers = useDockHandlers(context)

    const principal: SessionPrincipal = useMemo(() => {
        const profile = (info?.profile ?? null) as { email?: string; first_name?: string; uuid?: string } | null
        const displayName = profile?.first_name || profile?.email || 'You'
        return { kind: 'human', userId: profile?.uuid ?? 'you', displayName }
    }, [info])

    // The runner fetches `getPreviewToken(teamId, slug, revisionId)`
    // internally and threads the resulting JWT into every ingress call;
    // we just hand it the inputs (teamId + revisionId). When not
    // previewing, the runner uses the public ingress URL — no token,
    // no team needed.
    const preview = useMemo(
        () =>
            previewRevisionId && info?.teamId != null
                ? { teamId: info.teamId, revisionId: previewRevisionId }
                : undefined,
        [previewRevisionId, info?.teamId]
    )

    const runner = useRealRunner({
        agentSlug: agentRef.slug,
        agentRef,
        principal,
        teamId: info?.teamId ?? undefined,
        preview,
    })
    const transportError = useMemo(() => asTransportError(runner.error), [runner.error])
    const [renderMarkdown, setRenderMarkdown] = useRenderMarkdownPreference()

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
            transportError={transportError}
            onDismissTransportError={runner.clearError}
            reconnectAttempt={runner.reconnectAttempt}
            renderMarkdown={renderMarkdown}
            onRenderMarkdownChange={setRenderMarkdown}
        />
    )
}

function ConciergeDock(): React.ReactElement {
    const { context } = useDockStore()
    const focus = useFocusStore()
    const handlers = useDockHandlers(context)
    const [renderMarkdown, setRenderMarkdown] = useRenderMarkdownPreference()

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
            renderMarkdown={renderMarkdown}
            onRenderMarkdownChange={setRenderMarkdown}
        />
    )
}
