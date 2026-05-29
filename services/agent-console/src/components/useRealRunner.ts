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

import type { AgentApplicationRef, ChatSession, SessionPrincipal } from '@posthog/agent-chat'

import {
    cancelSession,
    listen,
    type PreviewOpts,
    sendMessage,
    startRun,
    type SessionEvent,
} from '@/lib/agentIngressClient'
import { getPreviewToken } from '@/lib/apiClient'
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
     * When set, all runner calls route to the named non-live revision
     * via the ingress's `<slug>-<revHex>` prefix, carrying a JWT
     * minted by Django. The hook fetches and refreshes the token
     * internally — callers only pass the (teamId, revisionId) tuple.
     */
    preview?: { teamId: number; revisionId: string }
}

export interface RealRunnerControls {
    session: ChatSession
    send: (text: string) => Promise<void>
    reset: () => Promise<void>
    playing: boolean
    /** Surfaces transport errors (network, 4xx, 5xx) to the UI. */
    error: Error | null
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

export function useRealRunner({ agentSlug, agentRef, principal, preview }: UseRealRunnerOpts): RealRunnerControls {
    const [session, setSession] = useState<ChatSession>(() => emptySession(agentRef, principal))
    const [playing, setPlaying] = useState(false)
    const [error, setError] = useState<Error | null>(null)
    const sessionIdRef = useRef<string | null>(null)
    const closeListenRef = useRef<(() => void) | null>(null)
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

    const onEvent = useCallback((event: SessionEvent) => {
        setSession((prev) => applyEvent(prev, event))
        if (event.kind === 'completed' || event.kind === 'failed') {
            setPlaying(false)
        }
    }, [])

    const openListen = useCallback(
        async (sessionId: string) => {
            const previewOpts = await ensurePreview()
            closeListenRef.current?.()
            closeListenRef.current = listen(
                agentSlug,
                sessionId,
                {
                    onEvent,
                    onError: () => {
                        // SSE error usually means the server closed the stream;
                        // we let `completed` / `failed` events drive state. Surface
                        // only when there's been no completion event yet.
                        setPlaying(false)
                    },
                },
                { preview: previewOpts }
            )
        },
        [agentSlug, ensurePreview, onEvent]
    )

    const send = useCallback(
        async (text: string): Promise<void> => {
            const trimmed = text.trim()
            if (!trimmed) {
                return
            }
            setError(null)
            // Optimistic: append the user turn locally so the UI feels
            // instant. The runner doesn't echo user input back over SSE.
            setSession((prev) => ({
                ...prev,
                state: 'streaming',
                turns: [
                    ...prev.turns,
                    { kind: 'user', id: `user-${Date.now()}`, timestamp: new Date().toISOString(), text: trimmed },
                ],
            }))
            setPlaying(true)
            try {
                const previewOpts = await ensurePreview()
                if (sessionIdRef.current) {
                    await sendMessage(agentSlug, sessionIdRef.current, trimmed, { preview: previewOpts })
                } else {
                    const res = await startRun(agentSlug, trimmed, { preview: previewOpts })
                    sessionIdRef.current = res.session_id
                    setSession((prev) => ({ ...prev, id: res.session_id, started_at: new Date().toISOString() }))
                    await openListen(res.session_id)
                }
            } catch (err) {
                setPlaying(false)
                setError(err instanceof Error ? err : new Error(String(err)))
            }
        },
        [agentSlug, ensurePreview, openListen]
    )

    const reset = useCallback(async (): Promise<void> => {
        const id = sessionIdRef.current
        closeListenRef.current?.()
        closeListenRef.current = null
        sessionIdRef.current = null
        setSession(emptySession(agentRef, principal))
        setPlaying(false)
        setError(null)
        if (id) {
            try {
                const previewOpts = await ensurePreview()
                await cancelSession(agentSlug, id, { preview: previewOpts })
            } catch {
                // Best-effort — server may already be done.
            }
        }
    }, [agentSlug, agentRef, principal, ensurePreview])

    return { session, send, reset, playing, error }
}
