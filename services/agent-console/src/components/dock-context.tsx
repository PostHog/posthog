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

interface DockStore {
    context: ChatContext
    setPage: (page: ConciergePageContext) => void
    enterPlayground: (agent: AgentApplicationRef) => void
    exitPlayground: () => void
}

const DEFAULT_CONTEXT: ChatContext = { mode: 'concierge', page: { kind: 'unknown' } }

const DockCtx = createContext<DockStore | null>(null)

export function DockContextProvider({ children }: { children: React.ReactNode }): React.ReactElement {
    // `currentPage` is what the active route reports; `playgroundAgent` is
    // an orthogonal sticky overlay. The effective context derives from both.
    const [currentPage, setCurrentPage] = useState<ConciergePageContext>({ kind: 'unknown' })
    const [playgroundAgent, setPlaygroundAgent] = useState<AgentApplicationRef | null>(null)

    const context: ChatContext = useMemo(
        () =>
            playgroundAgent ? { mode: 'playground', agent: playgroundAgent } : { mode: 'concierge', page: currentPage },
        [currentPage, playgroundAgent]
    )

    const value: DockStore = useMemo(
        () => ({
            context,
            setPage: (page) => setCurrentPage(page),
            enterPlayground: (agent) => setPlaygroundAgent(agent),
            exitPlayground: () => setPlaygroundAgent(null),
        }),
        [context]
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
