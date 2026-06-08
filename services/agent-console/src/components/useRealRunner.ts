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

import type {
    AgentApplicationRef,
    ChatSession,
    ClientToolHandler,
    ClientToolOutcome,
    SessionPrincipal,
} from '@posthog/agent-chat'
import { isRenderHandler } from '@posthog/agent-chat'

import {
    cancelSession,
    IngressError,
    listen,
    postClientToolResult,
    type PreviewOpts,
    sendClientToolResult,
    sendMessage,
    startRun,
    type SessionEvent,
} from '@/lib/agentIngressClient'
import { ApiError, getPreviewToken, getSession } from '@/lib/apiClient'
import { applyEvent } from '@/lib/runnerReducer'
import { describeSecretCallback, SECRET_SET_EVENT, type SecretSetEventDetail } from '@/lib/secretLinks'

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
    /**
     * Resolve a still-pending client tool call. Used by render-style
     * client tools whose inline UI submits an outcome; the runner
     * forwards via `postClientToolResult` so the runner-side awaiter
     * unblocks. Same wire path as the sync handler flow.
     */
    resolveClientTool: (callId: string, outcome: ClientToolOutcome) => void
    /**
     * Recent sessions started from this browser, most-recent first.
     * Backed by localStorage (`agent-console:session-history:<slug>:<rev>`).
     * The dock surfaces this as a history menu so the user can resume
     * a past conversation without going to the team-wide sessions list
     * (which spans all principals and isn't safe to drop a continue
     * button onto). Excludes terminal sessions — they're pruned on
     * `failed` / `closed` SSE events.
     */
    sessionHistory: SessionHistoryEntry[]
    /**
     * Resume a session from history (or any id the caller hands us).
     * Closes the current SSE, fetches the conversation via Django,
     * re-opens listen. On 404 / hard-terminal state the entry is
     * dropped from history and the dock falls back to an empty chat.
     * No-op when the id is already the active session.
     */
    switchToSession: (id: string) => Promise<void>
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

/**
 * Per-(agent + preview revision) localStorage list of recently-used sessions.
 *
 * Distinct from the active-session slot above: that's "what was I last
 * looking at"; this is "what threads has this browser ever started with
 * this agent". The dock surfaces it as a ChatGPT-style history menu so the
 * user can pick a previous conversation to resume without going to the
 * server-side sessions list (which spans all principals on the team and
 * isn't safe to drop a "continue chatting" button onto).
 *
 * Implicit principal scoping: only sessions started from this browser
 * land here, so the entries are by construction conversations the
 * viewer initiated. Cross-device drift is acceptable — same UX shape as
 * Claude / ChatGPT, where each browser has its own thread list.
 *
 * Entries are capped at SESSION_HISTORY_LIMIT, FIFO eviction by
 * `lastTouchedAt`. Terminal sessions (`failed` / `closed`) are pruned on
 * SSE event; sessions the server has forgotten are pruned lazily on
 * click (the `switchToSession` 404 path drops the entry).
 */
const SESSION_HISTORY_PREFIX = 'agent-console:session-history'
const SESSION_HISTORY_LIMIT = 20
const FIRST_MESSAGE_PREVIEW_LIMIT = 80

export interface SessionHistoryEntry {
    id: string
    /** ms since epoch. */
    createdAt: number
    /** ms since epoch. Bumped on every `send` to this session. */
    lastTouchedAt: number
    /**
     * Short slice of the first user message in the session, used as a
     * human label in the history menu. Truncated to
     * `FIRST_MESSAGE_PREVIEW_LIMIT` chars at write time.
     */
    firstMessage?: string
    /**
     * True once the session reaches a state that rejects further
     * `/send`s — `failed`, `closed`, or a 410 from ingress. The entry
     * stays in history so the user can still open the transcript in
     * playback; the UI just routes the click to the session-view page
     * instead of attempting an in-dock resume. Entries that the server
     * has fully forgotten (404 on resume) ARE dropped — there's no
     * transcript to view either.
     */
    terminal?: boolean
}

function sessionHistoryKey(agentSlug: string, previewRevisionId: string | undefined): string {
    return `${SESSION_HISTORY_PREFIX}:${agentSlug}:${previewRevisionId ?? 'live'}`
}

function readSessionHistory(agentSlug: string, previewRevisionId: string | undefined): SessionHistoryEntry[] {
    if (typeof window === 'undefined') {
        return []
    }
    const raw = window.localStorage.getItem(sessionHistoryKey(agentSlug, previewRevisionId))
    if (!raw) {
        return []
    }
    try {
        const parsed = JSON.parse(raw) as unknown
        if (!Array.isArray(parsed)) {
            return []
        }
        // Defensive filter — bad shapes from older versions are dropped
        // silently rather than crashing the dock.
        return parsed.filter(
            (e): e is SessionHistoryEntry =>
                typeof e === 'object' &&
                e !== null &&
                typeof (e as SessionHistoryEntry).id === 'string' &&
                typeof (e as SessionHistoryEntry).createdAt === 'number' &&
                typeof (e as SessionHistoryEntry).lastTouchedAt === 'number'
        )
    } catch {
        return []
    }
}

function writeSessionHistory(
    agentSlug: string,
    previewRevisionId: string | undefined,
    history: SessionHistoryEntry[]
): void {
    if (typeof window === 'undefined') {
        return
    }
    window.localStorage.setItem(sessionHistoryKey(agentSlug, previewRevisionId), JSON.stringify(history))
}

/**
 * Insert or update an entry, bump it to the front (most recent), and
 * trim to SESSION_HISTORY_LIMIT. Pure — caller writes the result back.
 *
 * If `entry.firstMessage` is provided and the existing entry lacks one,
 * we adopt it. If both have one, the existing wins — we never overwrite
 * a real first message with a later one.
 */
export function upsertSessionHistoryEntry(
    prev: SessionHistoryEntry[],
    entry: { id: string; firstMessage?: string },
    now: number = Date.now()
): SessionHistoryEntry[] {
    const existing = prev.find((e) => e.id === entry.id)
    const others = prev.filter((e) => e.id !== entry.id)
    const next: SessionHistoryEntry = existing
        ? {
              ...existing,
              lastTouchedAt: now,
              firstMessage: existing.firstMessage ?? entry.firstMessage,
          }
        : {
              id: entry.id,
              createdAt: now,
              lastTouchedAt: now,
              firstMessage: entry.firstMessage,
          }
    return [next, ...others].slice(0, SESSION_HISTORY_LIMIT)
}

/**
 * Mark an entry as terminal in-place — order preserved. The session
 * stays in history so the user can still open it for playback; the
 * UI uses the flag to route the click to the read-only session view
 * instead of attempting an in-dock resume that would 410.
 *
 * No-op when the id isn't in history (e.g. terminal event fired for
 * a session that was started server-side, not from this browser).
 */
export function markSessionHistoryTerminal(prev: SessionHistoryEntry[], id: string): SessionHistoryEntry[] {
    let changed = false
    const next = prev.map((e) => {
        if (e.id === id && !e.terminal) {
            changed = true
            return { ...e, terminal: true }
        }
        return e
    })
    return changed ? next : prev
}

export function removeSessionHistoryEntry(prev: SessionHistoryEntry[], id: string): SessionHistoryEntry[] {
    return prev.filter((e) => e.id !== id)
}

function truncateFirstMessage(text: string): string {
    const trimmed = text.trim()
    if (trimmed.length <= FIRST_MESSAGE_PREVIEW_LIMIT) {
        return trimmed
    }
    return trimmed.slice(0, FIRST_MESSAGE_PREVIEW_LIMIT - 1).trimEnd() + '…'
}

/**
 * Extract the first user-authored message from a restored session, used
 * to backfill `firstMessage` on history entries we picked up via resume
 * rather than first /run. Returns undefined if the session has no user
 * turns yet (which shouldn't happen for a session you can resume, but
 * defensive).
 */
function firstUserText(session: ChatSession): string | undefined {
    for (const turn of session.turns) {
        if (turn.kind === 'user' && typeof turn.text === 'string' && turn.text.trim()) {
            return truncateFirstMessage(turn.text)
        }
    }
    return undefined
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
    const [sessionHistory, setSessionHistory] = useState<SessionHistoryEntry[]>(() =>
        readSessionHistory(agentSlug, previewRevisionId)
    )

    // Reload the persisted history when the (agent, preview-rev) tuple
    // changes — keeps the menu in sync if the dock swaps agents without
    // unmounting (rare but supported).
    useEffect(() => {
        setSessionHistory(readSessionHistory(agentSlug, previewRevisionId))
    }, [agentSlug, previewRevisionId])

    // Single mutator that updates the React state AND writes through to
    // localStorage in one step. Every callsite goes through this so the
    // two stay in lockstep — divergence would mean the menu shows entries
    // the next reload won't find (or vice versa).
    const mutateHistory = useCallback(
        (mutator: (prev: SessionHistoryEntry[]) => SessionHistoryEntry[]) => {
            setSessionHistory((prev) => {
                const next = mutator(prev)
                writeSessionHistory(agentSlug, previewRevisionId, next)
                return next
            })
        },
        [agentSlug, previewRevisionId]
    )
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
                // Resume-on-reload also touches history so the menu shows
                // the resumed thread at the top, with a firstMessage
                // recovered from the restored conversation when present.
                mutateHistory((prev) =>
                    upsertSessionHistoryEntry(prev, {
                        id: restored.id,
                        firstMessage: firstUserText(restored),
                    })
                )
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
            // Render-style handlers are resolved by the chat surface
            // when the user submits the inline UI — see
            // `resolveClientTool` below. We leave the call pending and
            // do nothing here; the runner-side awaiter is already
            // waiting on a /client_tool_result event.
            if (isRenderHandler(handler)) {
                return
            }
            try {
                const result = await handler.handle(data.args ?? {})
                await postClientToolResult(agentSlug, sessionId, data.call_id, { result })
            } catch (err) {
                // Empty error messages turn into silent failures upstream
                // (the runner's bus reducer treats falsy errors as success
                // → tool resolves with undefined → pi-ai flags malformed
                // content → model gets `ok: false, error: ""`). Always
                // post a non-empty error and log the original so the
                // browser console keeps the diagnostic.
                // eslint-disable-next-line no-console
                console.error(`[client tool] ${data.tool_id} threw`, err)
                const raw = err instanceof Error ? err.message : String(err)
                const msg = raw || (err instanceof Error ? err.name : null) || 'client_handler_threw_no_message'
                await postClientToolResult(agentSlug, sessionId, data.call_id, { error: msg }).catch(() => undefined)
            }
        },
        [agentSlug]
    )

    // Render-style resolves go via /send so the session can park.
    const resolveClientTool = useCallback(
        (callId: string, outcome: ClientToolOutcome): void => {
            const sessionId = sessionIdRef.current
            if (!sessionId) {
                return
            }
            const payload = outcome.ok ? { result: outcome.body } : { error: outcome.error }
            void sendClientToolResult(agentSlug, sessionId, callId, payload).catch(() => undefined)
        },
        [agentSlug]
    )

    // mutateHistory is invoked from onEvent — keep it in a ref so a
    // dependency change in mutateHistory doesn't tear down the SSE
    // subscription (`openListen` depends on `onEvent`).
    const mutateHistoryRef = useRef(mutateHistory)
    useEffect(() => {
        mutateHistoryRef.current = mutateHistory
    }, [mutateHistory])

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
            // reload doesn't try to resume a dead session, and mark
            // the entry terminal in history. Entry stays so the user
            // can still open the transcript in playback. `completed`
            // is open (the user can keep /send-ing), so we leave it.
            if (event.kind === 'failed' || event.kind === 'closed') {
                const terminalId = sessionIdRef.current
                sessionIdRef.current = null
                clearStoredSessionId(agentSlug, previewRevisionId)
                if (terminalId) {
                    mutateHistoryRef.current((prev) => markSessionHistoryTerminal(prev, terminalId))
                }
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
            // Optimistic: append a pending user turn locally so the UI
            // feels instant. Always marked `pending` — the runner echoes
            // the message back via `user_message` SSE the moment it's
            // drained from `pending_inputs`, and the reducer swaps the
            // pending entry for the server-confirmed one. `turn_started`
            // also clears pending as a safety net against a missed echo.
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
                            pending: true,
                        },
                    ],
                }
            })
            setPlaying(true)
            try {
                const previewOpts = await ensurePreview()
                if (sessionIdRef.current) {
                    await sendMessage(agentSlug, sessionIdRef.current, trimmed, { preview: previewOpts })
                    // Touch the existing entry so the history menu shows
                    // active threads at the top — no firstMessage update
                    // here, the first one wins (see upsert helper).
                    mutateHistory((prev) => upsertSessionHistoryEntry(prev, { id: sessionIdRef.current! }))
                } else {
                    const res = await startRun(agentSlug, trimmed, { preview: previewOpts })
                    sessionIdRef.current = res.session_id
                    writeStoredSessionId(agentSlug, previewRevisionId, res.session_id)
                    setSession((prev) => ({ ...prev, id: res.session_id, started_at: new Date().toISOString() }))
                    // First /send of a new session — record the entry
                    // with the trimmed first message as a label.
                    mutateHistory((prev) =>
                        upsertSessionHistoryEntry(prev, {
                            id: res.session_id,
                            firstMessage: truncateFirstMessage(trimmed),
                        })
                    )
                    await openListen(res.session_id)
                }
            } catch (err) {
                setPlaying(false)
                setError(err instanceof Error ? err : new Error(String(err)))
                // 410 → the session has gone terminal upstream (cancelled
                // / closed). Drop the stored id so the next /send opens a
                // fresh session instead of looping into the same 410.
                if (err instanceof IngressError && err.status === 410) {
                    // 410 = session is terminal upstream (cancelled / closed).
                    // Same treatment as the SSE terminal events: clear the
                    // active id, mark history terminal so the entry sticks
                    // around for playback but doesn't pretend to be resumable.
                    const goneId = sessionIdRef.current
                    sessionIdRef.current = null
                    clearStoredSessionId(agentSlug, previewRevisionId)
                    if (goneId) {
                        mutateHistory((prev) => markSessionHistoryTerminal(prev, goneId))
                    }
                }
            }
        },
        [agentSlug, ensurePreview, openListen, previewRevisionId, mutateHistory]
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
            // Active session is being cancelled. Mark its history entry
            // terminal — the session is no longer resumable but its
            // transcript is still on the server, so the user can pick
            // it from the history menu for playback. We don't wait for
            // the cancel POST; the mark is the correct local state
            // regardless of whether the server responds before the
            // tab navigates away.
            mutateHistory((prev) => markSessionHistoryTerminal(prev, id))
            try {
                const previewOpts = await ensurePreview()
                await cancelSession(agentSlug, id, { preview: previewOpts })
            } catch {
                // Best-effort — server may already be done.
            }
        }
    }, [agentSlug, agentRef, principal, ensurePreview, previewRevisionId, mutateHistory])

    const switchToSession = useCallback(
        async (id: string): Promise<void> => {
            if (!id || id === sessionIdRef.current) {
                return
            }
            // Tear down the current SSE first — we're switching threads, the
            // existing stream is no longer relevant. Don't /cancel the
            // outgoing session: switching != ending, the user might come
            // back to it later via the same menu.
            closeListenRef.current?.()
            closeListenRef.current = null
            sessionIdRef.current = null
            setError(null)
            setPlaying(false)
            setReconnectAttempt(0)
            if (teamId == null) {
                setError(new Error('cannot switch session: team id unavailable'))
                return
            }
            try {
                const restored = await getSession(teamId, agentSlug, id, agentRef)
                // Hard-terminal — mark in history so the menu still
                // shows it for playback, but don't try to attach the dock.
                if (restored.state === 'failed' || restored.state === 'cancelled') {
                    mutateHistory((prev) => markSessionHistoryTerminal(prev, id))
                    setSession({ ...restored, principal })
                    setError(new Error(`session is ${restored.state}; open the session view to read its transcript`))
                    return
                }
                sessionIdRef.current = id
                setSession({ ...restored, principal })
                writeStoredSessionId(agentSlug, previewRevisionId, id)
                // Touch + backfill firstMessage if missing — picks up
                // older entries that were added before the firstMessage
                // field existed.
                mutateHistory((prev) => upsertSessionHistoryEntry(prev, { id, firstMessage: firstUserText(restored) }))
                await openListen(id)
            } catch (err) {
                if (err instanceof ApiError && err.status === 404) {
                    // Server has forgotten this session — there's no
                    // transcript to view either, so drop the entry.
                    mutateHistory((prev) => removeSessionHistoryEntry(prev, id))
                    setError(new Error('session not found'))
                    return
                }
                setError(err instanceof Error ? err : new Error(String(err)))
            }
        },
        [teamId, agentSlug, agentRef, principal, openListen, previewRevisionId, mutateHistory]
    )

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

    // Concierge callback: when the user finishes setting a secret in a
    // page surface (e.g. `<SecretEditDialog>`), the surface dispatches
    // `SECRET_SET_EVENT` carrying `{ sessionId, secret, action }`. If
    // that sessionId matches the runner's active session, we post a
    // synthetic system-style message so the agent receives a turn it
    // can react to ("user set the key — try again now"). Without this
    // the agent would be stuck waiting for the user to manually type.
    //
    // We keep `send` in a ref so re-mounts of the effect don't have to
    // wait for the next render to see the latest closure — important
    // for the case where the session id changes mid-effect.
    const sendRef = useRef(send)
    useEffect(() => {
        sendRef.current = send
    }, [send])
    useEffect(() => {
        if (typeof window === 'undefined') {
            return
        }
        const onSecretSet = (e: Event): void => {
            const detail = (e as CustomEvent<SecretSetEventDetail>).detail
            if (!detail || !detail.sessionId) {
                return
            }
            const activeId = sessionIdRef.current
            if (!activeId || activeId !== detail.sessionId) {
                return
            }
            void sendRef.current(describeSecretCallback(detail))
        }
        window.addEventListener(SECRET_SET_EVENT, onSecretSet)
        return () => window.removeEventListener(SECRET_SET_EVENT, onSecretSet)
    }, [])

    return {
        session,
        send,
        reset,
        stop,
        playing,
        error,
        clearError,
        reconnectAttempt,
        resolveClientTool,
        sessionHistory,
        switchToSession,
    }
}
