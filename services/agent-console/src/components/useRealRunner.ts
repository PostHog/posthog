/**
 * `useRealRunner` — drop-in replacement for `useFakeRunner` that talks
 * to a real agent via agent-ingress.
 *
 * Same return shape as the fake runner (`{ session, send, reset, playing }`)
 * so swapping it in the dock is a one-liner. Internals:
 *
 *   - First `send()` issues `POST /run` to start a session, captures
 *     the returned `session_id`, opens the SSE listen stream.
 *   - Subsequent `send()`s use `POST /send` with the same session id.
 *   - SSE events reduce into the `ChatSession` via `applyEvent`.
 *   - `reset()` cancels the upstream session (best-effort), closes
 *     the SSE stream, and clears local state.
 *
 * Auth is handled by the Next.js catch-all proxy — the browser hits
 * same-origin and the proxy attaches the OAuth bearer token before
 * forwarding to agent-ingress.
 */

'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import type { AgentApplicationRef, ChatSession, ClientToolHandler, SessionPrincipal } from '@posthog/agent-chat'

import {
    cancelSession,
    IngressError,
    listen,
    postClientToolResult,
    type PreviewOpts,
    sendMessage,
    startRun,
    type SessionEvent,
} from '@/lib/agentIngressClient'
import { ApiError, getPreviewToken, getSession } from '@/lib/apiClient'
import { applyEvent } from '@/lib/runnerReducer'

export interface UseRealRunnerOpts {
    /** Slug of the agent this runner talks to. */
    agentSlug: string
    /** The agent shape referenced by the session header, etc. */
    agentRef: AgentApplicationRef
    /** Principal shown in the chat header. v0.1 — derive from the
     *  authenticated user; for now caller supplies. */
    principal: SessionPrincipal
    /**
     * Team the agent belongs to. Used to call the Django API for session
     * resume on reload. When absent (e.g. dock mounted before the
     * session resolves) resume is skipped — the user just gets a fresh
     * empty chat.
     */
    teamId?: number
    /**
     * When set, all runner calls route to the named non-live revision
     * via the ingress's `<slug>-<revHex>` prefix, carrying a JWT
     * minted by Django. The hook fetches and refreshes the token
     * internally — callers only pass the (teamId, revisionId) tuple.
     */
    preview?: { teamId: number; revisionId: string }
    /**
     * Client-fulfilled tool handlers. When the SSE stream delivers a
     * `client_tool_call` event whose `tool_id` matches an entry's `id`,
     * the runner invokes the handler and POSTs the result back to
     * `/client_tool_result`. Unmatched ids → an error is posted so the
     * runner-side awaiter unblocks cleanly with `unhandled` instead of
     * waiting for the timeout.
     */
    handlers?: ClientToolHandler[]
}

export interface RealRunnerControls {
    session: ChatSession
    send: (text: string) => Promise<void>
    reset: () => Promise<void>
    /**
     * Stop the in-flight turn locally. Closes the SSE listener and
     * marks any streaming assistant turn as finalized so the UI stops
     * updating. The session id is preserved — the next `send()` keeps
     * the conversation going. Does NOT call the server's `/cancel`
     * endpoint because that's terminal (the session becomes
     * `cancelled` and rejects further `/send`s).
     *
     * Trade-off: the server-side turn continues running until the
     * model naturally finishes (we just stop showing it). A proper
     * server-side per-turn cancel would solve the cost-waste angle
     * but needs a backend change.
     */
    stop: () => void
    playing: boolean
    /** Surfaces transport errors (network, 4xx, 5xx) to the UI. */
    error: Error | null
    /** Clear the latest transport error — used by dismiss buttons in the UI. */
    clearError: () => void
    /**
     * Attempt number while the SSE stream is reconnecting after a
     * transient drop. 0 = not reconnecting. Resets to 0 on next
     * successful open or on terminal failure (the latter surfaces via
     * `error` instead).
     */
    reconnectAttempt: number
}

function emptySession(agentRef: AgentApplicationRef, principal: SessionPrincipal): ChatSession {
    return {
        id: 'pending',
        application: agentRef,
        principal,
        state: 'idle',
        trigger: { kind: 'chat' },
        started_at: undefined,
        ended_at: undefined,
        usage: { inputTokens: 0, outputTokens: 0, costUsd: 0 },
        turns: [],
        pendingApprovals: [],
    }
}

/**
 * Per-(agent + preview revision) localStorage slot for the active session
 * id. Keeps a reload from dropping you out of a long conversation — on
 * mount the hook reads this back, fetches the full conversation via
 * Django's session detail endpoint, and re-opens the SSE listener.
 */
const SESSION_STORAGE_PREFIX = 'agent-console:active-session'

function sessionStorageKey(agentSlug: string, previewRevisionId: string | undefined): string {
    return `${SESSION_STORAGE_PREFIX}:${agentSlug}:${previewRevisionId ?? 'live'}`
}

function readStoredSessionId(agentSlug: string, previewRevisionId: string | undefined): string | null {
    if (typeof window === 'undefined') {
        return null
    }
    return window.localStorage.getItem(sessionStorageKey(agentSlug, previewRevisionId))
}

function writeStoredSessionId(agentSlug: string, previewRevisionId: string | undefined, sessionId: string): void {
    if (typeof window === 'undefined') {
        return
    }
    window.localStorage.setItem(sessionStorageKey(agentSlug, previewRevisionId), sessionId)
}

function clearStoredSessionId(agentSlug: string, previewRevisionId: string | undefined): void {
    if (typeof window === 'undefined') {
        return
    }
    window.localStorage.removeItem(sessionStorageKey(agentSlug, previewRevisionId))
}

export function useRealRunner({
    agentSlug,
    agentRef,
    principal,
    teamId,
    preview,
    handlers,
}: UseRealRunnerOpts): RealRunnerControls {
    const [session, setSession] = useState<ChatSession>(() => emptySession(agentRef, principal))
    const [playing, setPlaying] = useState(false)
    const [error, setError] = useState<Error | null>(null)
    const [reconnectAttempt, setReconnectAttempt] = useState(0)
    const sessionIdRef = useRef<string | null>(null)
    const closeListenRef = useRef<(() => void) | null>(null)
    const previewRevisionId = preview?.revisionId
    // Cached preview JWT + when it goes stale. Tokens TTL ~60s; we
    // refresh proactively a few seconds before expiry so an in-flight
    // turn doesn't trip a mid-stream 401.
    const previewTokenRef = useRef<{ opts: PreviewOpts; expiresAt: number } | null>(null)

    // Tear down the listen stream on unmount.
    useEffect(() => {
        return () => {
            closeListenRef.current?.()
        }
    }, [])

    // Reset the cached token if the targeted revision changes.
    const previewKey = preview ? `${preview.teamId}:${preview.revisionId}` : ''
    useEffect(() => {
        previewTokenRef.current = null
    }, [previewKey])

    // Resume an in-flight session on mount: read the stored sessionId
    // for (agent, preview-rev), pull the conversation back via Django's
    // session detail endpoint, and re-open the SSE listener so any
    // events that landed during the reload window arrive. Skipped when
    // we have no teamId (the dock can mount before SessionGate
    // resolves), when there's no stored id, or for hard-terminal
    // sessions.
    //
    // Note on `completed`: under the session-restart redesign,
    // `completed` is the OPEN end-of-turn state — the user can keep
    // chatting and we should resume. The apiClient unfortunately maps
    // both raw `completed` (open) and raw `closed` (terminal) to
    // ChatSession state `completed`, so we can't distinguish them
    // here. Resume anyway and rely on the 410 fall-through in `send`
    // to clear stored ids that turn out to be sealed.
    useEffect(() => {
        if (teamId == null) {
            return
        }
        const stored = readStoredSessionId(agentSlug, previewRevisionId)
        if (!stored) {
            return
        }
        let cancelled = false
        void (async () => {
            try {
                const restored = await getSession(teamId, agentSlug, stored, agentRef)
                if (cancelled) {
                    return
                }
                // Hard-terminal: never resume. `closed` is ambiguous
                // (the API can't tell us whether `allow_restart` is set
                // on the chat trigger) so we let the user try.
                if (restored.state === 'failed' || restored.state === 'cancelled') {
                    clearStoredSessionId(agentSlug, previewRevisionId)
                    return
                }
                sessionIdRef.current = restored.id
                setSession({ ...restored, principal })
                await openListenRef.current?.(restored.id)
            } catch (err) {
                if (cancelled) {
                    return
                }
                // 404 → the stored id no longer exists on the server (purged
                // or wrong project). Anything else → leave the id alone so a
                // future retry can succeed.
                if (err instanceof ApiError && err.status === 404) {
                    clearStoredSessionId(agentSlug, previewRevisionId)
                }
            }
        })()
        return () => {
            cancelled = true
        }
        // openListen is captured via ref to break the dep cycle (openListen
        // depends on ensurePreview which depends on `preview`, but we want
        // this effect to fire once per (teamId, agentSlug, previewRev)).
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [teamId, agentSlug, previewRevisionId])

    const ensurePreview = useCallback(async (): Promise<PreviewOpts | undefined> => {
        if (!preview) {
            return undefined
        }
        const cached = previewTokenRef.current
        // 5s safety margin so a refresh fired mid-turn doesn't race the
        // server-side clock and land an "already expired" token.
        if (cached && cached.expiresAt - 5000 > Date.now()) {
            return cached.opts
        }
        const fresh = await getPreviewToken(preview.teamId, agentSlug, preview.revisionId)
        const opts: PreviewOpts = { ingressSlug: fresh.ingressSlug, token: fresh.token }
        previewTokenRef.current = { opts, expiresAt: Date.now() + fresh.expiresIn * 1000 }
        return opts
    }, [preview, agentSlug])

    // Handlers go through a ref so onEvent doesn't re-bind every time the
    // dock rebuilds them (dependencies of useCallback would otherwise
    // tear the SSE subscription down + back up on every render).
    const handlersRef = useRef<ClientToolHandler[]>(handlers ?? [])
    useEffect(() => {
        handlersRef.current = handlers ?? []
    }, [handlers])

    const dispatchClientToolCall = useCallback(
        async (event: SessionEvent) => {
            const data = event.data as { call_id?: string; tool_id?: string; args?: Record<string, unknown> }
            const sessionId = sessionIdRef.current
            if (!data.call_id || !data.tool_id || !sessionId) {
                return
            }
            const handler = handlersRef.current.find((h) => h.id === data.tool_id)
            if (!handler) {
                // Unhandled id — POST an error so the runner unblocks
                // immediately instead of waiting for the per-tool timeout.
                await postClientToolResult(agentSlug, sessionId, data.call_id, {
                    error: `unhandled_client_tool: ${data.tool_id}`,
                }).catch(() => undefined)
                return
            }
            try {
                const result = await handler.handle(data.args ?? {})
                await postClientToolResult(agentSlug, sessionId, data.call_id, { result })
            } catch (err) {
                const msg = err instanceof Error ? err.message : String(err)
                await postClientToolResult(agentSlug, sessionId, data.call_id, { error: msg }).catch(() => undefined)
            }
        },
        [agentSlug]
    )

    const onEvent = useCallback(
        (event: SessionEvent) => {
            // Any event means the stream is healthy — clear the
            // "Reconnecting…" indicator if it was up.
            setReconnectAttempt(0)
            // client_tool_call short-circuits the session reducer: we run
            // the local handler + POST a result back to ingress (which
            // publishes a client_tool_result on the bus → runner unblocks).
            if (event.kind === 'client_tool_call') {
                void dispatchClientToolCall(event)
                return
            }
            setSession((prev) => applyEvent(prev, event))
            if (event.kind === 'completed' || event.kind === 'failed') {
                setPlaying(false)
            }
            // Terminal upstream states → drop the persisted id so a
            // reload doesn't try to resume a dead session. `completed`
            // is open (the user can keep /send-ing), so we leave it.
            if (event.kind === 'failed' || event.kind === 'closed') {
                sessionIdRef.current = null
                clearStoredSessionId(agentSlug, previewRevisionId)
            }
        },
        [agentSlug, previewRevisionId, dispatchClientToolCall]
    )

    // Held in a ref so the resume effect can call the latest closure
    // without forcing itself to re-run on every preview-token refresh.
    const openListenRef = useRef<((sessionId: string) => Promise<void>) | null>(null)

    const openListen = useCallback(
        async (sessionId: string) => {
            const previewOpts = await ensurePreview()
            closeListenRef.current?.()
            closeListenRef.current = listen(
                agentSlug,
                sessionId,
                {
                    onEvent,
                    onReconnecting: (attempt) => setReconnectAttempt(attempt),
                    onError: () => {
                        // listen() already retries with backoff — this fires
                        // only when retries are exhausted (or the very first
                        // open failed terminally). EventSource doesn't expose
                        // status, just readyState; if we never reached a
                        // terminal `completed`/`failed` event the stream
                        // dropped mid-turn, surface as `stream:dropped`.
                        setPlaying(false)
                        setReconnectAttempt(0)
                        setSession((prev) => {
                            if (prev.state === 'streaming') {
                                setError(new Error('stream:dropped'))
                            }
                            return prev
                        })
                    },
                },
                { preview: previewOpts }
            )
        },
        [agentSlug, ensurePreview, onEvent]
    )

    // Keep the ref in sync — the resume effect uses it.
    useEffect(() => {
        openListenRef.current = openListen
    }, [openListen])

    const send = useCallback(
        async (text: string): Promise<void> => {
            const trimmed = text.trim()
            if (!trimmed) {
                return
            }
            setError(null)
            // Optimistic: append the user turn locally so the UI feels
            // instant. The runner doesn't echo user input back over SSE.
            // While a turn is in flight, mark the new turn as `pending`
            // — `/send` queues it into `pending_inputs` server-side and
            // the runner only drains it on the next turn boundary. We
            // clear the flag on the next `turn_started` event.
            setSession((prev) => {
                const queued = prev.state === 'streaming' || prev.state === 'awaiting_client_tool'
                return {
                    ...prev,
                    // Preserve the live state when queuing; only flip to
                    // `streaming` for the first message of a fresh turn.
                    state: queued ? prev.state : 'streaming',
                    turns: [
                        ...prev.turns,
                        {
                            kind: 'user',
                            id: `user-${Date.now()}`,
                            timestamp: new Date().toISOString(),
                            text: trimmed,
                            pending: queued,
                        },
                    ],
                }
            })
            setPlaying(true)
            try {
                const previewOpts = await ensurePreview()
                if (sessionIdRef.current) {
                    await sendMessage(agentSlug, sessionIdRef.current, trimmed, { preview: previewOpts })
                } else {
                    const res = await startRun(agentSlug, trimmed, { preview: previewOpts })
                    sessionIdRef.current = res.session_id
                    writeStoredSessionId(agentSlug, previewRevisionId, res.session_id)
                    setSession((prev) => ({ ...prev, id: res.session_id, started_at: new Date().toISOString() }))
                    await openListen(res.session_id)
                }
            } catch (err) {
                setPlaying(false)
                setError(err instanceof Error ? err : new Error(String(err)))
                // 410 → the session has gone terminal upstream (cancelled
                // / closed). Drop the stored id so the next /send opens a
                // fresh session instead of looping into the same 410.
                if (err instanceof IngressError && err.status === 410) {
                    sessionIdRef.current = null
                    clearStoredSessionId(agentSlug, previewRevisionId)
                }
            }
        },
        [agentSlug, ensurePreview, openListen, previewRevisionId]
    )

    const reset = useCallback(async (): Promise<void> => {
        const id = sessionIdRef.current
        closeListenRef.current?.()
        closeListenRef.current = null
        sessionIdRef.current = null
        clearStoredSessionId(agentSlug, previewRevisionId)
        setSession(emptySession(agentRef, principal))
        setPlaying(false)
        setError(null)
        setReconnectAttempt(0)
        if (id) {
            try {
                const previewOpts = await ensurePreview()
                await cancelSession(agentSlug, id, { preview: previewOpts })
            } catch {
                // Best-effort — server may already be done.
            }
        }
    }, [agentSlug, agentRef, principal, ensurePreview, previewRevisionId])

    const stop = useCallback((): void => {
        closeListenRef.current?.()
        closeListenRef.current = null
        setPlaying(false)
        setReconnectAttempt(0)
        setSession((prev) => {
            // Finalize any streaming assistant turn so the streaming
            // dots stop animating; transition state back to idle so the
            // composer's "streaming · Enter to queue" hint flips back
            // to the normal send copy.
            const turns = prev.turns.map((t) =>
                t.kind === 'assistant' && t.streaming ? { ...t, streaming: false } : t
            )
            return { ...prev, state: 'idle', turns }
        })
    }, [])

    const clearError = useCallback(() => setError(null), [])

    return { session, send, reset, stop, playing, error, clearError, reconnectAttempt }
}
