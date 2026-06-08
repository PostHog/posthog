/**
 * Adapter: dock-context → `<AgentChat />`.
 *
 * Always real-runner-only — the dock talks to agent-ingress over SSE
 * for both playground and concierge modes. Fixture scripts only ship
 * in Storybook (`packages/agent-chat/src/fixtures/`); they are never
 * imported from production paths.
 *
 * Owns the `@posthog/ui/focus` handler — pure URL mapper. The agent
 * calls focus, the handler pushes the matching route, and the
 * console refetches via `bumpReload()` so pages already on the
 * target URL still see fresh data.
 */

'use client'

import { ArrowRightIcon } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { AgentChat, type ClientToolHandler, type TransportError } from '@posthog/agent-chat'
import type {
    AgentApplicationRef,
    AssistantTurnPart,
    ChatContext,
    FocusArgs,
    FocusResult,
    SessionPrincipal,
    ToastArgs,
    ToastResult,
} from '@posthog/agent-chat'

import { IngressError } from '@/lib/agentIngressClient'
import { ApiError, getAgent, setEnvKey } from '@/lib/apiClient'
import { bumpReload } from '@/lib/reloadSignal'
import { DOCK_TOGGLE_KEY_HINT, DOCK_TOGGLE_KEY_HINT_PC, useDockLayout } from '@/lib/useDockLayout'

import { ConciergeSeedDialog } from './ConciergeSeedDialog'
import { useDockStore } from './dock-context'
import { DockHeader } from './DockHeader'
import { useFocusStore } from './focus-context'
import { SecretInline } from './SecretInline'
import { useSession } from './session-context'
import { useRealRunner } from './useRealRunner'

/** Platform-aware shortcut hint passed to every DockHeader. Computed at
 *  module load — runs client-side because this file is 'use client'. */
const DOCK_HIDE_HINT =
    typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
        ? DOCK_TOGGLE_KEY_HINT
        : DOCK_TOGGLE_KEY_HINT_PC

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
 *
 * Routes are **path-segment per tab** — each tab is its own Next.js
 * route under `app/agents/[slug]/`:
 *
 *     overview      → `/agents/<slug>`
 *     configuration → `/agents/<slug>/configuration`
 *     connections   → `/agents/<slug>/connections`
 *     sessions      → `/agents/<slug>/sessions`
 *     memory        → `/agents/<slug>/memory`
 *
 * Sub-state for the segment (selected revision, file path, session id,
 * etc.) lives in `?…` query params on the matching segment — defined
 * by each segment's page comment, see e.g. configuration/page.tsx.
 */
function urlForFocus(args: FocusArgs): string | null {
    // `args.slug` is required by the type but defensive — the spec's
    // args_schema may not enforce non-empty strings depending on the
    // provider, and an empty slug would build `/agents//configuration`.
    if (!args.slug) {
        return null
    }
    const base = `/agents/${args.slug}`
    switch (args.kind) {
        case 'tab':
            // Overview is the root segment of `[slug]`, the other tabs
            // are their own child segments.
            return args.tab === 'overview' ? base : `${base}/${args.tab}`
        case 'revision':
            return `${base}/configuration?revision=${encodeURIComponent(args.revisionId)}`
        case 'spec_section':
            return `${base}/configuration?section=${args.section}`
        case 'file':
            return `${base}/configuration?file=${encodeURIComponent(args.path)}`
        case 'session':
            return `${base}/sessions?session=${encodeURIComponent(args.sessionId)}`
        default:
            return null
    }
}

function useFocusHandlers(): ClientToolHandler<FocusArgs, FocusResult>[] {
    const focus = useFocusStore()
    const router = useRouter()
    return useMemo(() => {
        const dispatch = (args: FocusArgs): FocusResult => {
            if (!focus.enabled) {
                return { focused: false, reason: 'user_paused_follow' }
            }
            // `slug` is required on every variant — see comment on
            // `FocusArgs` in `@posthog/agent-chat/types`. Each branch
            // returns a distinct `reason` so the agent gets an
            // actionable message instead of a generic "unresolved".
            if (!args.slug) {
                return {
                    focused: false,
                    reason: 'missing_slug — every focus_* call must include the target agent slug',
                }
            }
            const url = urlForFocus(args)
            if (!url) {
                return { focused: false, reason: `unsupported_focus_kind:${args.kind}` }
            }
            try {
                router.push(url)
            } catch (e) {
                const msg = e instanceof Error ? e.message || e.name : String(e)
                return { focused: false, reason: `router_push_failed:${msg || 'unknown'}` }
            }
            bumpReload()
            return { focused: true, kind: args.kind }
        }
        return [
            {
                id: 'focus_tab',
                handle: (a: {
                    tab: 'overview' | 'configuration' | 'connections' | 'sessions' | 'memory'
                    slug: string
                }) => dispatch({ kind: 'tab', ...a }),
            },
            { id: 'focus_file', handle: (a: { path: string; slug: string }) => dispatch({ kind: 'file', ...a }) },
            {
                id: 'focus_revision',
                handle: (a: { revisionId: string; slug: string }) => dispatch({ kind: 'revision', ...a }),
            },
            {
                id: 'focus_session',
                handle: (a: { sessionId: string; slug: string }) => dispatch({ kind: 'session', ...a }),
            },
            {
                id: 'focus_spec_section',
                handle: (a: { section: 'triggers' | 'tools' | 'skills' | 'secrets' | 'limits'; slug: string }) =>
                    dispatch({ kind: 'spec_section', ...a }),
            },
        ] as unknown as ClientToolHandler<FocusArgs, FocusResult>[]
    }, [focus, router])
}

/**
 * Per-tool summary renderer the dock passes into `<AgentChat>` — turns
 * focus_* tool calls into a one-line "Open X →" link plus an inline
 * error reason on failure, so the user never has to expand the JSON
 * drawer to know what the agent tried to do or why it didn't work.
 *
 * Non-focus tools return null and fall back to the bare collapsed card.
 */
function useToolSummaryRenderer(): (part: Extract<AssistantTurnPart, { kind: 'tool_call' }>) => React.ReactNode | null {
    return useMemo(() => {
        return (part) => {
            if (!part.toolId.startsWith('focus_')) {
                return null
            }
            const target = describeFocusTarget(part.toolId, part.args)
            if (!target) {
                return null
            }
            // `slug` is required on every focus_* call — read it
            // straight from args. If the agent omitted it the call
            // failed at the dispatcher, which we'll surface as the
            // error text below.
            const slug = typeof part.args.slug === 'string' ? part.args.slug : null
            const url = slug ? urlForFocusToolId(part.toolId, part.args, slug) : null
            const failed = part.result !== undefined && !part.result.ok
            const errorText = failed && part.result && !part.result.ok ? part.result.error : null

            return (
                <div className="flex items-center gap-2 text-xs">
                    {errorText ? (
                        <span className="font-medium text-destructive-foreground">
                            Couldn't focus · <span className="font-mono normal-case opacity-80">{errorText}</span>
                        </span>
                    ) : null}
                    {url ? (
                        <Link
                            href={url}
                            className="ml-auto inline-flex shrink-0 items-center gap-1 text-foreground/80 underline decoration-foreground/40 underline-offset-2 hover:text-foreground hover:decoration-foreground"
                        >
                            Open {target} <ArrowRightIcon className="h-3 w-3" />
                        </Link>
                    ) : (
                        <span className="ml-auto text-muted-foreground">{target}</span>
                    )}
                </div>
            )
        }
    }, [])
}

/**
 * Pretty label for the focus target — what the user sees in the
 * inline link / fallback text. Mirrors the kinds in `FocusArgs`.
 */
function describeFocusTarget(toolId: string, args: Record<string, unknown>): string | null {
    switch (toolId) {
        case 'focus_tab':
            return typeof args.tab === 'string' ? `${args.tab} tab` : null
        case 'focus_revision':
            return typeof args.revisionId === 'string' ? `revision ${shortRevisionId(args.revisionId)}` : null
        case 'focus_session':
            return typeof args.sessionId === 'string' ? `session ${shortRevisionId(args.sessionId)}` : null
        case 'focus_spec_section':
            return typeof args.section === 'string' ? `${args.section} section` : null
        case 'focus_file':
            return typeof args.path === 'string' ? args.path : null
        default:
            return null
    }
}

/** Translate a `focus_*` tool id + args into a destination URL. */
function urlForFocusToolId(toolId: string, args: Record<string, unknown>, slug: string): string | null {
    switch (toolId) {
        case 'focus_tab':
            return typeof args.tab === 'string' ? urlForFocus({ kind: 'tab', tab: args.tab as never, slug }) : null
        case 'focus_revision':
            return typeof args.revisionId === 'string'
                ? urlForFocus({ kind: 'revision', revisionId: args.revisionId, slug })
                : null
        case 'focus_session':
            return typeof args.sessionId === 'string'
                ? urlForFocus({ kind: 'session', sessionId: args.sessionId, slug })
                : null
        case 'focus_spec_section':
            return typeof args.section === 'string'
                ? urlForFocus({ kind: 'spec_section', section: args.section as never, slug })
                : null
        case 'focus_file':
            return typeof args.path === 'string' ? urlForFocus({ kind: 'file', path: args.path, slug }) : null
        default:
            return null
    }
}

function shortRevisionId(id: string): string {
    return id.split('-').at(-1)?.slice(0, 8) ?? id.slice(0, 8)
}

function useDockHandlers(context: ChatContext): ClientToolHandler[] {
    const focusHandlers = useFocusHandlers()
    const { info } = useSession()
    const teamId = info?.teamId ?? null
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
    /**
     * `set_secret` — render-style client tool. The agent invokes it
     * with `{ agent_slug, secret, mode?, purpose? }` and the chat
     * surface mounts an inline form next to the tool-call card. The
     * user submits, the form PUTs `env_keys/<KEY>/`, and the runner
     * posts the success / failure outcome back. Same wire path as a
     * sync handler — the only difference is the UI moment in between.
     *
     * `agent_slug` is required and not inferred from page context.
     * Ambient-state inference (e.g. "the agent the user is looking at
     * right now") goes stale the moment they navigate; explicit
     * targeting keeps the call stable for the lifetime of the form.
     * The concierge already has the slug at hand via `get_context` or
     * the session-start envelope, and it can manage agents other than
     * the one currently on screen.
     */
    const setSecretHandler = useMemo<ClientToolHandler>(
        () => ({
            id: 'set_secret',
            render: (args, callbacks) => {
                const a = args as { agent_slug: string; secret?: string; mode?: 'set' | 'rotate'; purpose?: string }
                if (!a.agent_slug) {
                    callbacks.reject('missing_arg: agent_slug')
                    return null
                }
                if (!a.secret) {
                    callbacks.reject('missing_arg: secret')
                    return null
                }
                if (teamId == null) {
                    callbacks.reject('no_team_in_session')
                    return null
                }
                const slug = a.agent_slug
                return (
                    <SecretInline
                        agentSlug={slug}
                        secret={a.secret}
                        mode={a.mode}
                        purpose={a.purpose}
                        onSetSecret={(key, value) => setEnvKey(teamId, slug, key, value).then(() => undefined)}
                        onResolve={(body) => callbacks.resolve(body)}
                        onReject={(reason) => callbacks.reject(reason)}
                    />
                )
            },
        }),
        [teamId]
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
        () => [...focusHandlers, toastHandler, getContextHandler, setSecretHandler] as unknown as ClientToolHandler[],
        [focusHandlers, toastHandler, getContextHandler, setSecretHandler]
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
    const { layout, setMode, setVisible, embedSlot } = useDockLayout()
    const renderToolSummary = useToolSummaryRenderer()
    // When the dock is hosted by an embed slot (the overview page),
    // rail/floating mode and the hide-dock control don't apply — the
    // chat lives on the page itself, not in a side panel.
    const isEmbedded = embedSlot != null

    const sending = runner.session.state === 'streaming' || runner.session.state === 'awaiting_client_tool'

    return (
        <AgentChat
            context={context}
            session={runner.session}
            handlers={handlers}
            onClientToolResolve={runner.resolveClientTool}
            renderToolSummary={renderToolSummary}
            headerSlot={
                <DockHeader
                    context={context}
                    followingEnabled={focus.enabled}
                    onFollowingChange={focus.setEnabled}
                    onExitPlayground={() => {
                        void runner.reset()
                        exitPlayground()
                    }}
                    onNewSession={() => void runner.reset()}
                    onOpenSession={(sessionId) =>
                        router.push(`/agents/${agentRef.slug}/sessions?session=${encodeURIComponent(sessionId)}`)
                    }
                    busy={sending}
                    reconnectAttempt={runner.reconnectAttempt}
                    renderMarkdown={renderMarkdown}
                    onRenderMarkdownChange={setRenderMarkdown}
                    sessionId={runner.session.id !== 'pending' ? runner.session.id : undefined}
                    dockMode={layout.mode}
                    onChangeDockMode={isEmbedded ? undefined : setMode}
                    onHideDock={isEmbedded ? undefined : () => setVisible(false)}
                    hideShortcutHint={DOCK_HIDE_HINT}
                />
            }
            onSend={(text) => void runner.send(text)}
            onStop={runner.stop}
            transportError={transportError}
            onDismissTransportError={runner.clearError}
            renderMarkdown={renderMarkdown}
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
type ConciergeResolution =
    | { kind: 'pending' }
    | { kind: 'resolved'; agent: AgentApplicationRef }
    | { kind: 'not_deployed' }

function ConciergeDock(): React.ReactElement {
    const { conciergeAgent } = useDockStore()
    const { info } = useSession()
    const teamId = info?.teamId ?? null
    const slug = conciergeAgent?.slug ?? null
    const [resolution, setResolution] = useState<ConciergeResolution>({ kind: 'pending' })

    // Tracks the slug+team pair we've already resolved so we don't refetch
    // on route transitions where the slug temporarily clears and reverts.
    const resolvedKeyRef = useRef<string | null>(null)

    useEffect(() => {
        // Route transitions trigger setConciergeAgent(null) on the outgoing
        // layout's cleanup followed by the incoming layout setting the slug
        // back. Ignore the transient null so we don't unmount the dock and
        // restart a fresh fetch every navigation.
        if (!slug || teamId == null) {
            return
        }
        const key = `${teamId}:${slug}`
        if (resolvedKeyRef.current === key) {
            return
        }
        let cancelled = false
        setResolution((prev) => (prev.kind === 'resolved' && prev.agent.slug === slug ? prev : { kind: 'pending' }))
        getAgent(teamId, slug).then(
            (agent) => {
                if (cancelled) {
                    return
                }
                resolvedKeyRef.current = key
                setResolution({
                    kind: 'resolved',
                    agent: { id: agent.id, slug: agent.slug, name: agent.name },
                })
            },
            (err) => {
                if (cancelled) {
                    return
                }
                if (err instanceof ApiError && err.status === 404) {
                    resolvedKeyRef.current = key
                    setResolution({ kind: 'not_deployed' })
                    return
                }
                // Transient (network, 5xx, auth refresh): leave whatever
                // state we had so the dock isn't stuck on a spinner.
                // eslint-disable-next-line no-console
                console.warn('[concierge] failed to resolve agent', slug, err)
            }
        )
        return () => {
            cancelled = true
        }
    }, [slug, teamId])

    if (resolution.kind === 'resolved' && teamId != null) {
        return (
            <RealConciergeDock key={`${teamId}:${resolution.agent.slug}`} agentRef={resolution.agent} teamId={teamId} />
        )
    }
    if (resolution.kind === 'not_deployed') {
        return <ConciergeStub message={`No concierge deployed for "${slug}" in this project.`} />
    }
    return <ConciergeStub message="Loading concierge…" />
}

function ConciergeStub({ message }: { message: string }): React.ReactElement {
    return <div className="flex h-full items-center justify-center px-4 text-xs text-muted-foreground">{message}</div>
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
    const { context, conciergeSeed, confirmConciergeSeed, consumeConciergeSeed } = useDockStore()
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

    // Seed handling — `<EditWithAIButton>` writes to `conciergeSeed`.
    // Two stages:
    //   - `pending`   → if the runner has no turns, auto-confirm (no
    //     need to ask the user; the seed is the first message either
    //     way). Otherwise the `<ConciergeSeedDialog>` shows and the
    //     user chooses.
    //   - `confirmed` → dispatch. We tear the existing session down
    //     first; "confirmed" only fires when the user explicitly chose
    //     "start fresh", or when there was no session to begin with.
    const hasActiveTurns = runner.session.turns.length > 0
    useEffect(() => {
        if (!conciergeSeed) {
            return
        }
        if (conciergeSeed.stage === 'pending' && !hasActiveTurns) {
            confirmConciergeSeed()
            return
        }
        if (conciergeSeed.stage === 'confirmed') {
            const seq = conciergeSeed.seq
            const prompt = conciergeSeed.prompt
            // Reset first so the prompt lands as the first user turn
            // of a brand-new session — picks up the context envelope
            // and avoids appending to a stale conversation.
            void (async () => {
                if (hasActiveTurns) {
                    await runner.reset()
                }
                send(prompt)
                consumeConciergeSeed(seq)
            })()
        }
        // `send`/`runner` change every render but we want this effect
        // keyed to the seed lifecycle. The `runner.reset` + `send`
        // closures captured here are safe because they're stable
        // identities; if behaviour drifts we'll need refs.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [conciergeSeed, hasActiveTurns])

    const sending = runner.session.state === 'streaming' || runner.session.state === 'awaiting_client_tool'
    const { layout, setMode, setVisible, embedSlot } = useDockLayout()
    const renderToolSummary = useToolSummaryRenderer()
    const isEmbedded = embedSlot != null

    // Dialog handlers — "start fresh" promotes the seed to confirmed
    // (the effect above picks it up); "continue" appends without
    // resetting, then consumes the seed directly.
    const onStartFresh = useCallback(() => {
        confirmConciergeSeed()
    }, [confirmConciergeSeed])
    const onContinueWithSeed = useCallback(() => {
        if (!conciergeSeed) {
            return
        }
        const seq = conciergeSeed.seq
        send(conciergeSeed.prompt)
        consumeConciergeSeed(seq)
    }, [conciergeSeed, consumeConciergeSeed, send])

    return (
        <>
            <AgentChat
                context={context}
                session={runner.session}
                handlers={handlers}
                onClientToolResolve={runner.resolveClientTool}
                renderToolSummary={renderToolSummary}
                headerSlot={
                    <DockHeader
                        context={context}
                        followingEnabled={focus.enabled}
                        onFollowingChange={focus.setEnabled}
                        onNewSession={() => void runner.reset()}
                        onOpenSession={(sessionId) =>
                            router.push(`/agents/${agentRef.slug}/sessions?session=${encodeURIComponent(sessionId)}`)
                        }
                        sessionHistory={runner.sessionHistory}
                        onResumeSession={(id) => void runner.switchToSession(id)}
                        busy={sending}
                        reconnectAttempt={runner.reconnectAttempt}
                        renderMarkdown={renderMarkdown}
                        onRenderMarkdownChange={setRenderMarkdown}
                        sessionId={runner.session.id !== 'pending' ? runner.session.id : undefined}
                        dockMode={layout.mode}
                        onChangeDockMode={isEmbedded ? undefined : setMode}
                        onHideDock={isEmbedded ? undefined : () => setVisible(false)}
                        hideShortcutHint={DOCK_HIDE_HINT}
                    />
                }
                onSend={send}
                onStop={runner.stop}
                transportError={transportError}
                onDismissTransportError={runner.clearError}
                renderMarkdown={renderMarkdown}
            />
            <ConciergeSeedDialog
                hasActiveTurns={hasActiveTurns}
                onStartFresh={onStartFresh}
                onContinue={onContinueWithSeed}
            />
        </>
    )
}
