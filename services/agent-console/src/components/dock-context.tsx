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

/**
 * Per-area concierge agent. Each top-level surface (`/agents`,
 * `/billing`, ...) declares which deployed agent it wants the dock
 * to chat with via `useSetDockConciergeAgent({ slug })` from its
 * route layout. When `null`, the dock falls back to a fixture
 * runner so the chat surface still renders.
 */
export interface DockConciergeAgent {
    slug: string
}

/**
 * Pending "open concierge with this prompt" handoff. Set by the
 * `<EditWithAIButton>`, consumed by the concierge dock's runner.
 *
 * Two stages cover the lifecycle:
 *   - `pending`     — fresh request from the button. The dock decides
 *                     whether to auto-execute (no active session) or
 *                     ask the user via the confirm dialog (turns exist).
 *   - `confirmed`   — user has agreed to start fresh (or no confirm
 *                     needed). The dock resets the runner and dispatches.
 *
 * `seq` increments per invocation so the runner's consumer effect
 * fires even when the prompt repeats — same key clicked twice should
 * still seed the chat both times.
 */
export interface ConciergeSeed {
    seq: number
    prompt: string
    /** Optional slug of the agent the prompt is about; used for the
     *  context envelope when one isn't already set by the route. */
    agentSlug?: string
    stage: 'pending' | 'confirmed'
}

interface DockStore {
    context: ChatContext
    /** Concierge agent the active route has declared, or null. */
    conciergeAgent: DockConciergeAgent | null
    /** Pending prompt + lifecycle stage — see `ConciergeSeed`. */
    conciergeSeed: ConciergeSeed | null
    /** Session id of the active concierge chat, or null. Set by the dock once
     *  `/run` returns; cleared on session reset. Shell chrome reads it to
     *  surface a focus-mode indicator only when there's a live session. */
    activeConciergeSessionId: string | null
    setPage: (page: ConciergePageContext) => void
    setConciergeAgent: (agent: DockConciergeAgent | null) => void
    setActiveConciergeSessionId: (id: string | null) => void
    enterPlayground: (agent: AgentApplicationRef, opts?: PlaygroundOpts) => void
    exitPlayground: () => void
    /**
     * Open the concierge with a pre-filled prompt. If the user is in
     * playground mode, exits it first. The seed lands in `pending`
     * stage; the dock decides between auto-execute and a confirm
     * dialog based on whether the current concierge session has turns.
     */
    startConcierge: (opts: { prompt: string; agentSlug?: string }) => void
    /** Promote the seed past the confirm step — dock will dispatch. */
    confirmConciergeSeed: () => void
    /** Drop a pending seed (user cancelled the confirm). */
    cancelConciergeSeed: () => void
    /** Mark the active seed as delivered to the runner. */
    consumeConciergeSeed: (seq: number) => void
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
    const [conciergeAgent, setConciergeAgentState] = useState<DockConciergeAgent | null>(null)
    const [playgroundState, setPlaygroundState] = useState<PlaygroundState | null>(null)
    const [conciergeSeed, setConciergeSeed] = useState<ConciergeSeed | null>(null)
    const [activeConciergeSessionId, setActiveConciergeSessionIdState] = useState<string | null>(null)

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
    const setConciergeAgent = useCallback((agent: DockConciergeAgent | null): void => setConciergeAgentState(agent), [])
    const setActiveConciergeSessionId = useCallback(
        (id: string | null): void => setActiveConciergeSessionIdState(id),
        []
    )
    const enterPlayground = useCallback((agent: AgentApplicationRef, opts?: PlaygroundOpts): void => {
        const next: PlaygroundState = { agent, previewRevisionId: opts?.previewRevisionId }
        setPlaygroundState(next)
        writeStoredPlayground(next)
    }, [])
    const exitPlayground = useCallback((): void => {
        setPlaygroundState(null)
        writeStoredPlayground(null)
    }, [])

    const startConcierge = useCallback((opts: { prompt: string; agentSlug?: string }): void => {
        // Playground is sticky; an explicit "Edit with AI" should always
        // land in concierge mode. The runner consumer will decide
        // whether to reset the session or just send the prompt.
        setPlaygroundState(null)
        writeStoredPlayground(null)
        setConciergeSeed({
            seq: Date.now(),
            prompt: opts.prompt,
            agentSlug: opts.agentSlug,
            stage: 'pending',
        })
    }, [])

    const confirmConciergeSeed = useCallback((): void => {
        setConciergeSeed((prev) => (prev ? { ...prev, stage: 'confirmed' } : prev))
    }, [])

    const cancelConciergeSeed = useCallback((): void => {
        setConciergeSeed(null)
    }, [])

    const consumeConciergeSeed = useCallback((seq: number): void => {
        // Guard against stale acks — only clear if the seq matches the
        // current seed, otherwise a fast double-click would drop the
        // newer seed when the older runner finally caught up.
        setConciergeSeed((prev) => (prev && prev.seq === seq ? null : prev))
    }, [])

    const value: DockStore = useMemo(
        () => ({
            context,
            conciergeAgent,
            conciergeSeed,
            activeConciergeSessionId,
            setPage,
            setConciergeAgent,
            setActiveConciergeSessionId,
            enterPlayground,
            exitPlayground,
            startConcierge,
            confirmConciergeSeed,
            cancelConciergeSeed,
            consumeConciergeSeed,
        }),
        [
            context,
            conciergeAgent,
            conciergeSeed,
            activeConciergeSessionId,
            setPage,
            setConciergeAgent,
            setActiveConciergeSessionId,
            enterPlayground,
            exitPlayground,
            startConcierge,
            confirmConciergeSeed,
            cancelConciergeSeed,
            consumeConciergeSeed,
        ]
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
            conciergeAgent: null,
            conciergeSeed: null,
            activeConciergeSessionId: null,
            setPage: () => {},
            setConciergeAgent: () => {},
            setActiveConciergeSessionId: () => {},
            enterPlayground: () => {},
            exitPlayground: () => {},
            startConcierge: () => {},
            confirmConciergeSeed: () => {},
            cancelConciergeSeed: () => {},
            consumeConciergeSeed: () => {},
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

/**
 * Call from a route layout to declare which deployed agent the dock
 * should chat with in this area. Pass `null` (or skip the prop) to
 * leave the dock on its fixture fallback.
 *
 * Per-area concierge example:
 *   /agents/* → `useSetDockConciergeAgent({ slug: 'agent-concierge' })`
 *   /billing  → `useSetDockConciergeAgent({ slug: 'billing-bot' })`
 *
 * Clears on unmount so leaving the area returns the dock to its
 * fixture fallback.
 */
export function useSetDockConciergeAgent(agent: DockConciergeAgent | null): void {
    const { setConciergeAgent } = useDockStore()
    const slug = agent?.slug ?? null
    useEffect(() => {
        setConciergeAgent(slug ? { slug } : null)
        return () => setConciergeAgent(null)
    }, [setConciergeAgent, slug])
}
