/**
 * Focus context — bidirectional state that the dock's
 * `@posthog/ui/focus` handler writes to and the agent-detail page
 * reads to switch tabs / open files / jump to revisions.
 *
 * Conceptually it's the "what the dock most recently asked us to
 * show" signal. When the runner protocol lands in v0.3 the same
 * signal will come from the `client_tool_call` SSE event; for v0 the
 * fake runner pushes it directly.
 *
 * Also owns **focus mode** — a user-controlled toggle that gates
 * whether incoming focus calls actually drive navigation. When off,
 * the handler returns `{ focused: false, reason: 'user_paused_follow' }`
 * so the agent can gracefully spell out what it was about to show.
 * Default: on.
 */

'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

const LS_KEY_ENABLED = 'posthog-agent-console:focus-mode-enabled'

function loadPersistedEnabled(fallback: boolean): boolean {
    if (typeof window === 'undefined') {
        return fallback
    }
    try {
        const raw = window.localStorage.getItem(LS_KEY_ENABLED)
        if (raw === '0') {
            return false
        }
        if (raw === '1') {
            return true
        }
    } catch {
        // ignore — private mode / disabled storage
    }
    return fallback
}

function savePersistedEnabled(next: boolean): void {
    if (typeof window === 'undefined') {
        return
    }
    try {
        window.localStorage.setItem(LS_KEY_ENABLED, next ? '1' : '0')
    } catch {
        // ignore — private mode / disabled storage
    }
}

export type FocusTarget =
    | { kind: 'tab'; tab: 'overview' | 'configuration' | 'sessions' }
    | { kind: 'file'; agentSlug?: string; path: string }
    | { kind: 'revision'; agentSlug?: string; revisionId: string }
    | { kind: 'session'; agentSlug?: string; sessionId: string }
    | { kind: 'spec_section'; agentSlug?: string; section: 'triggers' | 'tools' | 'skills' | 'secrets' | 'limits' }

interface FocusStore {
    target: FocusTarget | null
    /** Tick increments every set, so consumers can re-apply even if the same target fires twice. */
    tick: number
    /** When false, the dock's focus handler refuses to drive navigation. */
    enabled: boolean
    setEnabled: (next: boolean) => void
    setTarget: (t: FocusTarget) => void
    clear: () => void
}

const FocusCtx = createContext<FocusStore | null>(null)

export function FocusContextProvider({
    children,
    defaultEnabled = true,
}: {
    children: React.ReactNode
    defaultEnabled?: boolean
}): React.ReactElement {
    // SSR-safe: start with the prop default; hydrate from localStorage on mount.
    const [enabled, setEnabledState] = useState<boolean>(defaultEnabled)
    const [state, setState] = useState<{ target: FocusTarget | null; tick: number }>({ target: null, tick: 0 })

    useEffect(() => {
        const persisted = loadPersistedEnabled(defaultEnabled)
        if (persisted !== enabled) {
            setEnabledState(persisted)
        }
        // Run once on mount.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const setTarget = useCallback((t: FocusTarget) => {
        setState((prev) => ({ target: t, tick: prev.tick + 1 }))
    }, [])

    const clear = useCallback(() => {
        setState({ target: null, tick: 0 })
    }, [])

    const setEnabled = useCallback((next: boolean) => {
        setEnabledState(next)
        savePersistedEnabled(next)
    }, [])

    const value = useMemo<FocusStore>(
        () => ({ target: state.target, tick: state.tick, enabled, setEnabled, setTarget, clear }),
        [state, enabled, setEnabled, setTarget, clear]
    )

    return <FocusCtx.Provider value={value}>{children}</FocusCtx.Provider>
}

export function useFocusStore(): FocusStore {
    const store = useContext(FocusCtx)
    if (!store) {
        // Stub for stories that render leaves in isolation.
        return { target: null, tick: 0, enabled: true, setEnabled: () => {}, setTarget: () => {}, clear: () => {} }
    }
    return store
}
