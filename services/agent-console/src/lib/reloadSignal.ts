/**
 * Global "the page should refetch" signal.
 *
 * The dock's focus handler bumps this after every navigation so pages
 * pick up the latest data even when the URL didn't change — e.g. the
 * agent just edited `agent.md` and focuses on it while you're already
 * viewing that file. `useResource` subscribes implicitly so every
 * read in the app benefits without per-callsite plumbing.
 *
 * Intentionally global / mutable — there's only ever one tab at a
 * time and the signal is fire-and-forget. If we ever need scoped
 * reloads (e.g. "refresh just this card") add a keyed variant.
 */

'use client'

import { useEffect, useState } from 'react'

let tick = 0
const listeners = new Set<() => void>()

export function bumpReload(): void {
    tick += 1
    for (const listener of listeners) {
        try {
            listener()
        } catch {
            // Listener bug — skip so others still fire.
        }
    }
}

/**
 * Returns the current reload tick. Components re-render when it
 * bumps. `useResource` consumes this and includes it in deps so
 * every read refetches on focus-triggered navigation.
 */
export function useReloadKey(): number {
    const [current, setCurrent] = useState(tick)
    useEffect(() => {
        const sub = (): void => setCurrent(tick)
        listeners.add(sub)
        return () => {
            listeners.delete(sub)
        }
    }, [])
    return current
}
