/**
 * Focus mode — a user-controlled toggle gating whether the dock's
 * `@posthog/ui/focus` handler actually drives URL navigation. When
 * off, the handler returns `{ focused: false, reason: 'user_paused_follow' }`
 * so the agent gracefully narrates instead of expecting the page to
 * follow along.
 *
 * Persisted to localStorage so the choice survives reloads. Default: on.
 */

'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

const LS_KEY = 'posthog-agent-console:focus-mode-enabled'

interface FocusModeStore {
    enabled: boolean
    setEnabled: (next: boolean) => void
}

const FocusModeCtx = createContext<FocusModeStore | null>(null)

function loadPersisted(fallback: boolean): boolean {
    if (typeof window === 'undefined') {
        return fallback
    }
    try {
        const raw = window.localStorage.getItem(LS_KEY)
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

function savePersisted(next: boolean): void {
    if (typeof window === 'undefined') {
        return
    }
    try {
        window.localStorage.setItem(LS_KEY, next ? '1' : '0')
    } catch {
        // ignore — private mode / disabled storage
    }
}

export function FocusContextProvider({
    children,
    defaultEnabled = true,
}: {
    children: React.ReactNode
    defaultEnabled?: boolean
}): React.ReactElement {
    // SSR-safe: start with the prop default; hydrate from localStorage on mount.
    const [enabled, setEnabledState] = useState<boolean>(defaultEnabled)

    useEffect(() => {
        const persisted = loadPersisted(defaultEnabled)
        if (persisted !== enabled) {
            setEnabledState(persisted)
        }
        // Run once on mount.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const setEnabled = useCallback((next: boolean) => {
        setEnabledState(next)
        savePersisted(next)
    }, [])

    const value = useMemo<FocusModeStore>(() => ({ enabled, setEnabled }), [enabled, setEnabled])
    return <FocusModeCtx.Provider value={value}>{children}</FocusModeCtx.Provider>
}

export function useFocusStore(): FocusModeStore {
    const store = useContext(FocusModeCtx)
    if (!store) {
        // Stub for stories that render leaves in isolation.
        return { enabled: true, setEnabled: () => {} }
    }
    return store
}
