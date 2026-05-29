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

import { cancelSession, listen, sendMessage, startRun, type SessionEvent } from '@/lib/agentIngressClient'
import { applyEvent } from '@/lib/runnerReducer'

export interface UseRealRunnerOpts {
    /** Slug of the agent this runner talks to. */
    agentSlug: string
    /** The agent shape referenced by the session header, etc. */
    agentRef: AgentApplicationRef
    /** Principal shown in the chat header. v0.1 — derive from the
     *  authenticated user; for now caller supplies. */
    principal: SessionPrincipal
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

export function useRealRunner({ agentSlug, agentRef, principal }: UseRealRunnerOpts): RealRunnerControls {
    const [session, setSession] = useState<ChatSession>(() => emptySession(agentRef, principal))
    const [playing, setPlaying] = useState(false)
    const [error, setError] = useState<Error | null>(null)
    const sessionIdRef = useRef<string | null>(null)
    const closeListenRef = useRef<(() => void) | null>(null)

    // Tear down the listen stream on unmount.
    useEffect(() => {
        return () => {
            closeListenRef.current?.()
        }
    }, [])

    const onEvent = useCallback((event: SessionEvent) => {
        setSession((prev) => applyEvent(prev, event))
        if (event.kind === 'completed' || event.kind === 'failed') {
            setPlaying(false)
        }
    }, [])

    const openListen = useCallback(
        (sessionId: string) => {
            closeListenRef.current?.()
            closeListenRef.current = listen(agentSlug, sessionId, {
                onEvent,
                onError: () => {
                    // SSE error usually means the server closed the stream;
                    // we let `completed` / `failed` events drive state. Surface
                    // only when there's been no completion event yet.
                    setPlaying(false)
                },
            })
        },
        [agentSlug, onEvent]
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
                if (sessionIdRef.current) {
                    await sendMessage(agentSlug, sessionIdRef.current, trimmed)
                } else {
                    const res = await startRun(agentSlug, trimmed)
                    sessionIdRef.current = res.session_id
                    setSession((prev) => ({ ...prev, id: res.session_id, started_at: new Date().toISOString() }))
                    openListen(res.session_id)
                }
            } catch (err) {
                setPlaying(false)
                setError(err instanceof Error ? err : new Error(String(err)))
            }
        },
        [agentSlug, openListen]
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
                await cancelSession(agentSlug, id)
            } catch {
                // Best-effort — server may already be done.
            }
        }
    }, [agentSlug, agentRef, principal])

    return { session, send, reset, playing, error }
}
