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

// The index route has no segment and redirects to the default page, so it and the inbox hold the splash until the
// inbox loads. Chats and Views show their own loading state at once.
function holdsSplash(segments: readonly string[]): boolean {
    const first = segments.find((segment) => !isGroup(segment))
    return first === undefined || first === 'inbox'
}

export function shouldHideSplash({ sessionReady, firstScreenReady, segments, timedOut }: SplashGateInput): boolean {
    if (!sessionReady) {
        return false
    }
    return firstScreenReady || timedOut || !holdsSplash(segments)
}
