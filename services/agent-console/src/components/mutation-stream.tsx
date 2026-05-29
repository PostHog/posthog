/**
 * Mutation stream context — opens a single EventSource against
 * `/agent_events/stream/` per app shell, fans out to subscribers.
 *
 * Wraps the per-component subscription so all `useMutationFlair` and
 * `useMutating*` hooks share one HTTP connection. Replaces the
 * in-process `mockApi.subscribeMutation` registry the console used
 * before MSW — the data + the stream both live behind the network
 * boundary now.
 */

'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useRef } from 'react'

import { subscribeMutations, type MutationEvent } from '@/lib/apiClient'

type Listener = (e: MutationEvent) => void

interface Store {
    /** Subscribe to events for a single entityKey. */
    subscribe: (entityKey: string, listener: Listener) => () => void
    /** Most-recent event for an entityKey, if any. */
    getLast: (entityKey: string) => MutationEvent | null
}

const StreamCtx = createContext<Store | null>(null)

/**
 * Single source of mutation events for the app shell. Opens one
 * EventSource on mount and fans events out to per-key subscribers.
 */
export function MutationStreamProvider({ children }: { children: React.ReactNode }): React.ReactElement {
    const listenersRef = useRef<Map<string, Set<Listener>>>(new Map())
    const lastRef = useRef<Map<string, MutationEvent>>(new Map())

    useEffect(() => {
        return subscribeMutations((event) => {
            lastRef.current.set(event.entityKey, event)
            const set = listenersRef.current.get(event.entityKey)
            if (!set) {
                return
            }
            for (const listener of set) {
                try {
                    listener(event)
                } catch {
                    // Listener bug — skip.
                }
            }
        })
    }, [])

    const subscribe = useCallback((entityKey: string, listener: Listener) => {
        let set = listenersRef.current.get(entityKey)
        if (!set) {
            set = new Set()
            listenersRef.current.set(entityKey, set)
        }
        set.add(listener)
        return () => {
            set?.delete(listener)
        }
    }, [])

    const getLast = useCallback((entityKey: string): MutationEvent | null => {
        return lastRef.current.get(entityKey) ?? null
    }, [])

    const value = useMemo<Store>(() => ({ subscribe, getLast }), [subscribe, getLast])
    return <StreamCtx.Provider value={value}>{children}</StreamCtx.Provider>
}

export function useMutationStream(): Store {
    const store = useContext(StreamCtx)
    if (!store) {
        // Stubbed for stories that render leaves without the provider.
        return { subscribe: () => () => {}, getLast: () => null }
    }
    return store
}
