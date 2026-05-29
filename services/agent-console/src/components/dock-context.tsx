/**
 * Client-side store for the ambient dock's context + mode.
 *
 * The dock lives in the app shell; pages mounted *inside* the shell
 * call `useSetDockContext(...)` on mount to tell the dock what they're
 * showing. Playground mode is sticky across navigation — only an
 * explicit exit clears it.
 *
 * Implementation: React context with a setter. Cheap, no extra
 * dependency. v0.1 can swap to Zustand if we want devtools.
 */

'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import type { AgentApplicationRef, ChatContext, ConciergePageContext } from '@posthog/agent-chat'

interface PlaygroundOpts {
    /**
     * Talk to this specific non-live revision via the preview-proxy
     * instead of the live revision. Useful for testing a draft
     * without promoting it.
     */
    previewRevisionId?: string
}

interface DockStore {
    context: ChatContext
    setPage: (page: ConciergePageContext) => void
    enterPlayground: (agent: AgentApplicationRef, opts?: PlaygroundOpts) => void
    exitPlayground: () => void
}

const DEFAULT_CONTEXT: ChatContext = { mode: 'concierge', page: { kind: 'unknown' } }

const DockCtx = createContext<DockStore | null>(null)

interface PlaygroundState {
    agent: AgentApplicationRef
    previewRevisionId?: string
}

/**
 * Playground state survives reloads — without this, the dock would
 * restore to concierge mode and the playground's persisted session id
 * would never get picked up.
 */
const PLAYGROUND_STORAGE_KEY = 'agent-console:playground-state'

function readStoredPlayground(): PlaygroundState | null {
    if (typeof window === 'undefined') {
        return null
    }
    const raw = window.localStorage.getItem(PLAYGROUND_STORAGE_KEY)
    if (!raw) {
        return null
    }
    try {
        const parsed = JSON.parse(raw) as Partial<PlaygroundState>
        if (
            parsed &&
            typeof parsed === 'object' &&
            parsed.agent &&
            typeof parsed.agent === 'object' &&
            typeof parsed.agent.slug === 'string' &&
            typeof parsed.agent.id === 'string' &&
            typeof parsed.agent.name === 'string'
        ) {
            return {
                agent: parsed.agent,
                previewRevisionId: typeof parsed.previewRevisionId === 'string' ? parsed.previewRevisionId : undefined,
            }
        }
    } catch {
        // Corrupt entry — fall through and clear it below.
    }
    window.localStorage.removeItem(PLAYGROUND_STORAGE_KEY)
    return null
}

function writeStoredPlayground(state: PlaygroundState | null): void {
    if (typeof window === 'undefined') {
        return
    }
    if (state === null) {
        window.localStorage.removeItem(PLAYGROUND_STORAGE_KEY)
        return
    }
    window.localStorage.setItem(PLAYGROUND_STORAGE_KEY, JSON.stringify(state))
}

export function DockContextProvider({ children }: { children: React.ReactNode }): React.ReactElement {
    // `currentPage` is what the active route reports; `playgroundState` is
    // an orthogonal sticky overlay. The effective context derives from both.
    const [currentPage, setCurrentPage] = useState<ConciergePageContext>({ kind: 'unknown' })
    const [playgroundState, setPlaygroundState] = useState<PlaygroundState | null>(null)

    // Restore the playground overlay on mount so a reload doesn't drop
    // the user back into concierge (which would also bypass the
    // playground's persisted session resume).
    useEffect(() => {
        const stored = readStoredPlayground()
        if (stored) {
            setPlaygroundState(stored)
        }
    }, [])

    const context: ChatContext = useMemo(
        () =>
            playgroundState
                ? {
                      mode: 'playground',
                      agent: playgroundState.agent,
                      previewRevisionId: playgroundState.previewRevisionId,
                  }
                : { mode: 'concierge', page: currentPage },
        [currentPage, playgroundState]
    )

    // Stable setters — they only call the React-stable `setState`s, so the
    // references never need to change. Without this, `value` re-creates
    // `setPage` every time `context` updates, which makes `useSetDockPage`'s
    // useEffect re-fire and loop.
    const setPage = useCallback((page: ConciergePageContext): void => setCurrentPage(page), [])
    const enterPlayground = useCallback((agent: AgentApplicationRef, opts?: PlaygroundOpts): void => {
        const next: PlaygroundState = { agent, previewRevisionId: opts?.previewRevisionId }
        setPlaygroundState(next)
        writeStoredPlayground(next)
    }, [])
    const exitPlayground = useCallback((): void => {
        setPlaygroundState(null)
        writeStoredPlayground(null)
    }, [])

    const value: DockStore = useMemo(
        () => ({ context, setPage, enterPlayground, exitPlayground }),
        [context, setPage, enterPlayground, exitPlayground]
    )

    return <DockCtx.Provider value={value}>{children}</DockCtx.Provider>
}

export function useDockStore(): DockStore {
    const store = useContext(DockCtx)
    if (!store) {
        // Outside the provider — return a safe stub so storybook stories
        // that render leaf components in isolation don't blow up.
        return {
            context: DEFAULT_CONTEXT,
            setPage: () => {},
            enterPlayground: () => {},
            exitPlayground: () => {},
        }
    }
    return store
}

/**
 * Call from a page to tell the dock what's on screen. Idempotent —
 * resets to the same value cause no re-render.
 */
export function useSetDockPage(page: ConciergePageContext): void {
    const { setPage } = useDockStore()
    // Stringify-stable comparison so callers can pass new literals each render
    // without spamming setPage.
    const key = JSON.stringify(page)
    const memoized = useCallback(() => setPage(page), [setPage, key]) // eslint-disable-line react-hooks/exhaustive-deps
    useEffect(memoized, [memoized])
}
