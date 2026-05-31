/**
 * Adapter: dock-context → `<AgentChat />`.
 *
 * Two runners, picked by mode:
 *   - **Playground** → `useRealRunner` against `context.agent.slug`,
 *     talking to agent-ingress over SSE.
 *   - **Concierge** → `useRealRunner` against the slug declared by
 *     the route layout via `useSetDockConciergeAgent({ slug })`. If
 *     the agent isn't deployed (yet) or the slug doesn't resolve
 *     against the project, we fall back to `useFakeRunner` with
 *     the canned concierge scripts so the dock still has something
 *     to show.
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
import { ApiError, getAgent } from '@/lib/apiClient'
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
            id: 'focus',
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
            id: 'toast',
            handle: (args) => {
                // eslint-disable-next-line no-console
                console.info('[dock toast]', args)
                return { shown: true }
            },
        }),
        []
    )
    // get_context returns the host's current view info — same shape as the
    // Phase A envelope plus follow-mode + client kind so the agent can
    // resolve "this agent" / "this session" mid-conversation. Built fresh
    // on each call (reads from the dock store + URL each time), so a user
    // navigating between agents won't get stale answers.
    const focusEnabled = useFocusStore().enabled
    const getContextHandler = useMemo<ClientToolHandler>(
        () => ({
            id: 'get_context',
            handle: () => {
                const page = context.mode === 'concierge' ? context.page : { kind: 'unknown' as const }
                const agent =
                    'agent' in page ? { slug: page.agent.slug, id: page.agent.id, name: page.agent.name } : undefined
                const sessionId = page.kind === 'agent-session' ? page.sessionId : undefined
                const url = typeof window !== 'undefined' ? window.location.pathname : undefined
                return {
                    page: page.kind,
                    agent,
                    session_id: sessionId ?? null,
                    url,
                    follow_enabled: focusEnabled,
                    client: { kind: 'agent-console', version: '1' },
                }
            },
        }),
        [context, focusEnabled]
    )
    return useMemo<ClientToolHandler[]>(
        () => [focusHandler, toastHandler, getContextHandler] as unknown as ClientToolHandler[],
        [focusHandler, toastHandler, getContextHandler]
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
    const router = useRouter()

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
        handlers,
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
            onStop={runner.stop}
            onOpenSession={(sessionId) => router.push(`/agents/${agentRef.slug}/sessions/${sessionId}`)}
            transportError={transportError}
            onDismissTransportError={runner.clearError}
            reconnectAttempt={runner.reconnectAttempt}
            renderMarkdown={renderMarkdown}
            onRenderMarkdownChange={setRenderMarkdown}
        />
    )
}

/**
 * Resolves the configured concierge slug to a real agent ref, then
 * renders either the real-runner variant (when resolved) or the
 * fixture variant (when the slug isn't deployed in this project).
 *
 * We use a mount-key on the real variant so the runner hooks tear
 * down cleanly when the slug or team changes — same trick the
 * top-level `Dock` uses for mode/agent swaps.
 */
function ConciergeDock(): React.ReactElement {
    const { conciergeAgent } = useDockStore()
    const { info } = useSession()
    const teamId = info?.teamId ?? null
    const slug = conciergeAgent?.slug ?? null
    const [resolved, setResolved] = useState<AgentApplicationRef | null>(null)
    const [resolveError, setResolveError] = useState<boolean>(false)

    useEffect(() => {
        if (!slug || teamId == null) {
            setResolved(null)
            setResolveError(false)
            return
        }
        let cancelled = false
        setResolveError(false)
        getAgent(teamId, slug).then(
            (agent) => {
                if (!cancelled) {
                    setResolved({ id: agent.id, slug: agent.slug, name: agent.name })
                }
            },
            (err) => {
                if (cancelled) {
                    return
                }
                // 404 means the slug isn't deployed in this project —
                // expected for areas whose concierge isn't shipped yet
                // (e.g. `/billing` referencing `billing-bot`). Fall back
                // to the fixture runner silently.
                const is404 = err instanceof ApiError && err.status === 404
                if (!is404) {
                    // eslint-disable-next-line no-console
                    console.warn('[concierge] failed to resolve agent', slug, err)
                }
                setResolved(null)
                setResolveError(true)
            }
        )
        return () => {
            cancelled = true
        }
    }, [slug, teamId])

    if (resolved && teamId != null) {
        return <RealConciergeDock key={`${teamId}:${resolved.slug}`} agentRef={resolved} teamId={teamId} />
    }
    // While resolving (resolved == null AND no error), or when the
    // slug genuinely doesn't exist in this project (resolveError), we
    // show the fixture dock so the surface always has something useful.
    void resolveError
    return <FixtureConciergeDock />
}

/**
 * Build a small JSON envelope describing the user's current view. Sent as
 * a prefix on the FIRST user message of each new session so the concierge
 * knows which agent / session / page the user is referring to ("this agent"
 * → resolves to the slug), without having to ask. The envelope uses a
 * `[console-context]` delimiter so the agent.md can teach the model to
 * extract + suppress it in its own output.
 *
 * Phase A: zero platform changes — the envelope rides as part of the user
 * message text. Phase B (client-tool dispatch) replaces this with a proper
 * `@posthog/ui/get_context` tool call the model can re-fire at any time.
 */
function buildContextEnvelope(context: ChatContext, currentUrl: string | null): string | null {
    if (context.mode !== 'concierge') {
        return null
    }
    const page = context.page
    const data: Record<string, unknown> = { page: page.kind, url: currentUrl ?? undefined }
    if ('agent' in page) {
        data.agent = { slug: page.agent.slug, name: page.agent.name, id: page.agent.id }
    }
    if (page.kind === 'agent-session') {
        data.session_id = page.sessionId
    }
    if (page.kind === 'agent-bundle' && page.revisionLabel) {
        data.revision_label = page.revisionLabel
    }
    return `[console-context]\n${JSON.stringify(data)}\n[/console-context]\n\n`
}

function RealConciergeDock({
    agentRef,
    teamId,
}: {
    agentRef: AgentApplicationRef
    teamId: number
}): React.ReactElement {
    const { context } = useDockStore()
    const focus = useFocusStore()
    const { info } = useSession()
    const handlers = useDockHandlers(context)
    const router = useRouter()

    const principal: SessionPrincipal = useMemo(() => {
        const profile = (info?.profile ?? null) as { email?: string; first_name?: string; uuid?: string } | null
        const displayName = profile?.first_name || profile?.email || 'You'
        return { kind: 'human', userId: profile?.uuid ?? 'you', displayName }
    }, [info])

    const runner = useRealRunner({
        agentSlug: agentRef.slug,
        agentRef,
        principal,
        teamId,
        handlers,
    })
    const transportError = useMemo(() => asTransportError(runner.error), [runner.error])
    const [renderMarkdown, setRenderMarkdown] = useRenderMarkdownPreference()

    // Wrap send to prepend the context envelope on the first user message
    // of each session. Subsequent messages don't repeat it — the model
    // carries the context through conversation history, and bloating
    // every turn with the envelope distorts the transcript.
    const send = useCallback(
        (text: string) => {
            const isFirstTurn = runner.session.turns.length === 0
            if (!isFirstTurn) {
                void runner.send(text)
                return
            }
            const url = typeof window !== 'undefined' ? window.location.pathname : null
            const envelope = buildContextEnvelope(context, url)
            void runner.send(envelope ? envelope + text : text)
        },
        [context, runner]
    )

    return (
        <AgentChat
            context={context}
            session={runner.session}
            handlers={handlers}
            followingEnabled={focus.enabled}
            onFollowingChange={focus.setEnabled}
            onNewSession={() => void runner.reset()}
            onSend={send}
            onStop={runner.stop}
            onOpenSession={(sessionId) => router.push(`/agents/${agentRef.slug}/sessions/${sessionId}`)}
            transportError={transportError}
            onDismissTransportError={runner.clearError}
            reconnectAttempt={runner.reconnectAttempt}
            renderMarkdown={renderMarkdown}
            onRenderMarkdownChange={setRenderMarkdown}
        />
    )
}

function FixtureConciergeDock(): React.ReactElement {
    const { context } = useDockStore()
    const focus = useFocusStore()
    const handlers = useDockHandlers(context)
    const [renderMarkdown, setRenderMarkdown] = useRenderMarkdownPreference()

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
