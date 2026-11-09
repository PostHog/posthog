import { useEffect } from 'react'
import { create } from 'zustand'

// A hung request must not trap the user on the splash; after this the first screen shows its own loading state.
export const SPLASH_TIMEOUT_MS = 8_000

interface BootGateState {
    firstScreenReady: boolean
    markFirstScreenReady: () => void
}

export const useBootGate = create<BootGateState>()((set) => ({
    firstScreenReady: false,
    markFirstScreenReady: () => set({ firstScreenReady: true }),
}))

export function useFirstScreenReady(ready: boolean): void {
    useEffect(() => {
        if (!ready) {
            return
        }
        const frame = requestAnimationFrame(() => useBootGate.getState().markFirstScreenReady())
        return () => cancelAnimationFrame(frame)
    }, [ready])
}

export interface SplashGateInput {
    sessionReady: boolean
    firstScreenReady: boolean
    /** The route's file segments from `useSegments()`, so group names such as `(tabs)` are included. */
    segments: readonly string[]
    timedOut: boolean
}

function isGroup(segment: string): boolean {
    return segment.startsWith('(') && segment.endsWith(')')
}

// The index holds the splash through the redirect. Views detail links show their own loading states.
function holdsSplash(segments: readonly string[]): boolean {
    const first = segments.find((segment) => !isGroup(segment))
    return first === undefined || first === 'inbox' || (first === 'views' && segments.includes('(tabs)'))
}

export function shouldHideSplash({ sessionReady, firstScreenReady, segments, timedOut }: SplashGateInput): boolean {
    if (!sessionReady) {
        return false
    }
    return firstScreenReady || timedOut || !holdsSplash(segments)
}
