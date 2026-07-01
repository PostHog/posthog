import { useActions } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { runContextLogic } from '../logics/runContextLogic'
import type { AgentContextItem } from '../types/contextTypes'

export interface UseAgentContextOptions {
    /** The run to attach context to — same key `runStreamLogic` / `runContextLogic` use. */
    streamKey: string
    /** Stable source id; this writer owns that bucket in the store (register replaces it wholesale). */
    sourceId: string
    /** The typed references this source contributes. Re-registered when their content changes. */
    items: AgentContextItem[]
    /** Default true; false deregisters the source without unmounting (parity with `useMaxTool`'s `active`). */
    active?: boolean
}

/**
 * Register a context source on mount and deregister on unmount, mirroring `useMaxTool`'s lifecycle:
 * the source's items are keyed by a `JSON.stringify` content key so identity churn doesn't re-register,
 * and the cleanup drops the bucket so the store never keeps a stale source's context.
 */
export function useAgentContext({ streamKey, sourceId, items, active = true }: UseAgentContextOptions): void {
    const { registerContextSource, deregisterContextSource } = useActions(runContextLogic({ streamKey }))
    // Re-register only when the item content actually changes, not on every render's fresh array identity.
    const itemsKey = useMemo(() => JSON.stringify(items), [items])
    const itemsRef = useRef(items)
    itemsRef.current = items

    useEffect(() => {
        if (!active) {
            deregisterContextSource(sourceId)
            return
        }
        registerContextSource(sourceId, itemsRef.current)
        return () => deregisterContextSource(sourceId)
        // itemsRef is a stable ref; itemsKey stands in for the item content.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [streamKey, sourceId, itemsKey, active])
}

export interface AgentContextProps extends UseAgentContextOptions {
    children?: React.ReactNode
}

/**
 * Render-less declarative writer over `useAgentContext` — drop `<AgentContext streamKey sourceId items />`
 * anywhere in the tree to contribute context for the duration it's mounted. Symmetric with the old
 * `MaxTool` component form, but a pure writer (no button chrome).
 */
export function AgentContext({ children, ...options }: AgentContextProps): JSX.Element {
    useAgentContext(options)
    return <>{children ?? null}</>
}
